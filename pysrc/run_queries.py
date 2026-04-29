"""
Script to run polars queries on NYSE TAQ and collect performance metrics (like execution time)

Environment variables:
"""
import argparse
import csv
import gc
import os
import logging
from dataclasses import dataclass

import psutil
import subprocess
import sys
from datetime import datetime, time, timedelta # time is used in queries
import time as time_mod   # alias to avoid naming conflict

from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger: logging.Logger = logging.getLogger(__name__)

def get_device(db: str) -> str:
    resolve_device: subprocess.CompletedProcess[str] = subprocess.run(["./src/resolve_device.sh", db],
                                    capture_output=True, text=True, check=False)
    if resolve_device.returncode != 0:
        logger.error("Error occurred while mapping DB dir to a device: %s", resolve_device.stderr)
        logger.error("IO statistics will not be captured")
        return None
    else:
        return resolve_device.stdout.split('\n')[0].strip()  # TODO: add error handling

def get_io_stat(device: str) -> int:
    return None if device is None else psutil.disk_io_counters(perdisk=True)[device].read_bytes // 1000

def load_parameters(param_dir: Path) -> Dict[str, Any]:
    """Reads parameter text files into the params dictionary."""
    params: Dict[str, Any] = {}
    def read_single(filename: str) -> str:
        return (param_dir / filename).read_text(encoding='utf-8').strip()
    def read_list(filename: str) -> List[str]:
        content = (param_dir / filename).read_text(encoding='utf-8')
        return [line.strip() for line in content.splitlines() if line.strip()]
    params.update({
        "aFreqInstr": read_single("aFreqInstr.txt"),
        "mostFreqInstr": read_single("mostFreqInstr.txt"),
        "anInfreqInstr": read_single("anInfreqInstr.txt"),
        "twentyInstrs": read_list("twentyInstrs.txt"),
        "hundredInstrs": read_list("hundredInstrs.txt"),
        "fivehundredInfreqInstrs": read_list("fivehundredInfreqInstrs.txt"),
    })

    def _to_timedelta(s: str) -> timedelta:
        t = datetime.strptime(s[2:], "%H:%M:%S.%f")
        return timedelta(hours=t.hour, minutes=t.minute, seconds=t.second, microseconds=t.microsecond)

    with open(param_dir / "timeBuckets.txt", "r", encoding="utf-8") as f:
        params["timeBuckets"] = {line.split("=")[0].strip():
                                 _to_timedelta(line.split("=")[1].strip())
                                 for line in f}

    return params

@dataclass
class QueryResult:
    """Data class to hold the results of a query benchmark."""
    query: str
    status: str
    run1_time_ns: int = None
    run2_time_ns: int = None
    run3_time_ns: int = None
    run1_io_KB: int = None
    run2_io_KB: int = None
    run3_io_KB: int = None

    def to_csv_row(self) -> List[Any]:
        return [
            self.query, self.status,
            self.run1_time_ns, self.run2_time_ns, self.run3_time_ns,
            None, # Not Yet Implemented
            self.run1_io_KB, self.run2_io_KB, self.run3_io_KB
        ]

def run_query(runner, db_path: Path, device: str, idx: str, tags: Set, query: str, parameter: str, queryoutput: Path) -> QueryResult:
    """
    Runs a specific query 3 times (Cold, Warm, Warm) and records timing.
    """
    times: List[float] = []
    ios: List[float] = []
    for runidx in range(3):
        iteration_label = "Cold" if runidx == 0 else f"Warm-{runidx}"
        logger.info("[%s] Run %s/3 (%s): %s ...", idx, runidx+1, iteration_label, query[:50])
        # Prepare environment
        if runidx == 0:
            subprocess.run([os.getenv('FLUSH'), db_path], check=True,capture_output=True)
        gc.collect()
        # Execute and Time
        io_start = get_io_stat(device)
        t_start = time_mod.perf_counter_ns()
        try:
            res = runner.execute_query(idx, tags, query, parameter, runidx)
            t_end = time_mod.perf_counter_ns()
            io_end = get_io_stat(device)
        except Exception as e:
            logger.error("Query %s failed: %s", idx, e)
            # Return 0.0 or -1.0 to indicate failure in results
            return QueryResult(query, "error")
        if runidx == 0:
            logger.info("[%s]   Shape of the result: %s x %s", idx, res.shape[0], res.shape[1])
            if not queryoutput is None:
                outFile = queryoutput / f"queryoutput_{idx}.csv"
                runner.write_csv(res, outFile)
        times.append(t_end - t_start)
        ios.append(io_end-io_start)

    return QueryResult(query, "success", *times, *ios)

class QueryExecutorPyKX:
    """
    Handles the setup, execution of PyKX Python queries
    on NYSE TAQ kdb+ database.
    """
    def __init__(self, param:Dict[str, Any]) -> None:
        self.db: kx.DB = None
        # Parameters available for queries
        self.params: Dict[str, Any] = param

    def load_resources(self, db_path: Path) -> None:
        """Loads kdb+ database"""
        logger.info("loading kdb DB %s", db_path)
        self.db = kx.DB(path=db_path, change_dir=False)

    def execute_query(self, idx: int, tags: Set, query_str: str, parameter: str, runidx: int) -> int:
        """
        Safely executes the query string using the loaded data and parameters.
        """
        # Create a restricted execution context
        eval_context = {
            "kx":kx,
            "timedelta": timedelta,
            "db": self.db,
            **self.params
        }
        return eval(query_str, eval_context)

    def write_csv(self, res, outFile: Path) -> None:
        kx.q.write.csv(outFile, res)

class QueryExecutorPyKXInMemory:
    """
    Handles the setup, execution of PyKX Python queries
    on NYSE TAQ kdb+ database.
    """
    def __init__(self, param:Dict[str, Any]) -> None:
        self.master: kx.Table = None
        self.quote: kx.Table = None
        self.trade: kx.Table = None
        # Parameters available for queries
        self.params: Dict[str, Any] = param
        kx.q['timeBucketsStep'] = kx.q('{`s#value[x]!key x}', param['timeBuckets'])

    def load_resources(self, db_path: Path) -> None:
        """Loads kdb+ database"""
        logger.info("loading first partition's tables of the kdb+ database at %s into memory", db_path)
        db = kx.DB(path=db_path, change_dir=False)
        self.master = db.master.select(where=kx.Column('date') == kx.Column('date').min()).delete(columns=kx.Column('date')).select(where=kx.Column('i') > -1)
        self.quote = db.quote.select(where=kx.Column('date') == kx.Column('date').min()).delete(columns=kx.Column('date')).select(where=kx.Column('i') > -1)
        self.quote = self.quote.sort_values(by='time').grouped('sym')
        self.trade = db.trade.select(where=kx.Column('date') == kx.Column('date').min()).delete(columns=kx.Column('date')).select(where=kx.Column('i') > -1)
        self.trade = self.trade.sort_values(by='time').grouped('sym')

    def execute_query(self, idx: int, tags: Set, query_str: str, parameter: str, runidx: int) -> int:
        """
        Safely executes the query string using the loaded data and parameters.
        """
        # Create a restricted execution context
        eval_context = {
            "kx":kx,
            "timedelta": timedelta,
            "master": self.master,
            "trade": self.trade,
            "quote": self.quote,
            **self.params
        }
        return eval(query_str, eval_context)

    def write_csv(self, res, outFile: Path) -> None:
        kx.q.write.csv(outFile, res)

class QueryExecutorPyKXQ:
    """
    Handles the setup, execution of PyKX q queries
    on NYSE TAQ kdb+ database.
    """
    def __init__(self, paramdir: Path) -> None:
        self.db: kx.DB = None
        self.paramdir: Path = paramdir


    def load_resources(self, db_path: Path) -> None:
        """Loads kdb+ database"""
        logger.info("loading kdb DB %s", db_path)
        self.db = kx.DB(path=db_path, change_dir=False)
        kx.q.system.load("src/getQueryParameters.q")
        kx.q('getQueryParameters', kx.q.hsym(kx.SymbolAtom(self.paramdir)))

    def execute_query(self, idx: int, tags: Set, query_str: str, parameter: str, runidx: int) -> int:
        """
        Safely executes the query string using the loaded data and parameters.
        """
        return kx.q(query_str)

    def write_csv(self, res, outFile: Path) -> None:
        kx.q.write.csv(outFile, res)


class QueryExecutorPolars:
    """
    Handles the setup, execution of Polars queries
    on NYSE TAQ hive-partitioned parquet files.
    """

    def __init__(self, param:Dict[str, Any]) -> None:
        # Dataframes (Lazy)
        self.master: Optional[pl.LazyFrame] = None
        self.trade: Optional[pl.LazyFrame] = None
        self.quote: Optional[pl.LazyFrame] = None

        # Parameters available for queries
        time_bucket_expr = pl.lit(None) # Initial state
        for bucket, bound in param['timeBuckets'].items():
            time_bucket_expr = pl.when(pl.col("time") >= bound).then(
                pl.lit(bucket)).otherwise(time_bucket_expr)
        param['time_bucket_expr'] = time_bucket_expr

        time_bucket_idx_expr = pl.lit(None) # Initial state
        for index, bound in enumerate(param['timeBuckets'].values()):
            time_bucket_idx_expr = pl.when(pl.col("time") >= bound).then(
                pl.lit(index)).otherwise(time_bucket_idx_expr)
        param['time_bucket_idx_expr'] = time_bucket_idx_expr

        self.params: Dict[str, Any] = param

    def load_resources(self, db_path: Path) -> None:
        """Loads database schemas."""
        logger.info("loading hive-partitioned tables at %s", db_path)

        self.master = pl.scan_parquet(db_path / "master/date=*/*.parquet", hive_partitioning=True)

        exnames = pl.scan_parquet(db_path / "exnames.parquet").collect()
        self.params["exnames"] = dict(zip(exnames["ex"], exnames["name"]))

        self.trade = pl.scan_parquet(db_path / "trade/date=*/*.parquet", hive_partitioning=True)
        self.quote = pl.scan_parquet(db_path / "quote/date=*/*.parquet", hive_partitioning=True)

    def execute_query(self, idx: int, tags: Set, query_str: str, parameter: str, runidx: int) -> int:
        """
        Safely executes the query string using the loaded data and parameters.
        """
        # Create a restricted execution context
        eval_context = {
            "pl": pl,
            "timedelta": timedelta,
            "master": self.master,
            "trade": self.trade,
            "quote": self.quote,
            **self.params
        }
        return eval(query_str, eval_context) if "dataframeresult" in tags else eval(query_str, eval_context).collect()

    def write_csv(self, res, outFile: Path) -> None:
        res.with_columns(pl.col(pl.Boolean).cast(pl.Int8)).fill_nan(None).write_csv(outFile, float_precision=6)

class QueryExecutorPolarsInMemory:
    """
    Handles the setup, execution of Polars in-memory queries
    """

    def __init__(self, param:Dict[str, Any]) -> None:
        # Dataframes
        self.datadate: Optional[datetime.date] = None
        self.master: Optional[pl.DataFrame] = None
        self.trade: Optional[pl.DataFrame] = None
        self.quote: Optional[pl.DataFrame] = None

        # Parameters available for queries
        time_bucket_expr = pl.lit(None) # Initial state
        for bucket, bound in param['timeBuckets'].items():
            time_bucket_expr = pl.when(pl.col("time") >= bound).then(
                pl.lit(bucket)).otherwise(time_bucket_expr)
        param['time_bucket_expr'] = time_bucket_expr

        time_bucket_idx_expr = pl.lit(None) # Initial state
        for index, bound in enumerate(param['timeBuckets'].values()):
            time_bucket_idx_expr = pl.when(pl.col("time") >= bound).then(
                pl.lit(index)).otherwise(time_bucket_idx_expr)
        param['time_bucket_idx_expr'] = time_bucket_idx_expr

        self.params: Dict[str, Any] = param

    def load_resources(self, db_path: Path) -> None:
        """Loads database schemas."""
        logger.info("loading first partition of hive-partitioned tables at %s into memory", db_path)
        master = pl.scan_parquet(db_path / "master/date=*/*.parquet", hive_partitioning=True)
        self.datadate = master.select(pl.first("date")).collect().item()
        self.master = master.filter(pl.col("date") == self.datadate).drop("date").with_columns(pl.col("sym").cast(pl.Categorical)).collect()
        logger.info("Shape of master: %s x %s", self.master.shape[0], self.master.shape[1])

        exnames = pl.scan_parquet(db_path / "exnames.parquet").collect()
        self.params["exnames"] = dict(zip(exnames["ex"], exnames["name"]))

        logger.info("loading trade")
        self.trade = pl.scan_parquet(db_path / "trade/date=*/*.parquet",
            hive_partitioning=True).filter(pl.col("date") == self.datadate).drop("date").with_columns(pl.col("sym").cast(pl.Categorical)).sort("time").collect()
        logger.info("Shape of trade: %s x %s", self.trade.shape[0], self.trade.shape[1])
        logger.info("loading quote")
        self.quote = pl.scan_parquet(db_path / "quote/date=*/*.parquet",
            hive_partitioning=True).filter(pl.col("date") == self.datadate).drop("date").with_columns(pl.col("sym").cast(pl.Categorical)).sort("time").collect()
        logger.info("Shape of quote: %s x %s", self.quote.shape[0], self.quote.shape[1])

    def execute_query(self, idx: int, tags: Set, query_str: str, parameter: str, runidx: int) -> int:
        """
        Safely executes the query string using the loaded data and parameters.
        """
        # Create a restricted execution context
        eval_context = {
            "pl": pl,
            "timedelta": timedelta,
            "datadate": self.datadate,
            "master": self.master,
            "trade": self.trade,
            "quote": self.quote,
            **self.params
        }
        return eval(query_str, eval_context)

    def write_csv(self, res, outFile: Path) -> None:
        res.write_csv(outFile)


class QueryExecutorDuckDBInMemory:
    """
    Handles the setup, execution of DuckDB in-memory queries.
    """

    def __init__(self, param:Dict[str, Any]) -> None:
        self.datadate: Optional[datetime.date] = None
        self.master: Optional[duckdb.DuckDBPyRelation] = None
        self.trade: Optional[duckdb.DuckDBPyRelation] = None
        self.quote: Optional[duckdb.DuckDBPyRelation] = None

        self.params: Dict[str, Any] = param

    def load_resources(self, db_path: Path) -> None:
        """Loads database schemas."""
        logger.info("loading first partition of hive-partitioned tables at %s into memory", db_path)
        master = duckdb.read_parquet(str(db_path / "master/date=*/*.parquet"), hive_partitioning=True)
        self.datadate = master['date'].fetchone()[0]
        self.master = duckdb.sql("select * EXCLUDE (date) from master where date=$1", params=[self.datadate])
        logger.info("Shape of master: %s x %s", self.master.shape[0], self.master.shape[1])

        exnames = duckdb.read_parquet(str(db_path / "exnames.parquet"))
        self.params["exnames"] = dict(zip(exnames["ex"].fetchall(), exnames["name"].fetchall()))

        logger.info("loading trade")
        trade = duckdb.read_parquet(str(db_path / "trade/date=*/*.parquet"),
            hive_partitioning=True)
        self.trade = duckdb.sql("SELECT * EXCLUDE (date) FROM trade WHERE date = $1 ORDER BY time", params=[self.datadate])
        logger.info("Shape of trade: %s x %s", self.trade.shape[0], self.trade.shape[1])

        logger.info("loading quote")
        quote = duckdb.read_parquet(str(db_path / "quote/date=*/*.parquet"),
            hive_partitioning=True)
        self.quote = duckdb.sql("SELECT * EXCLUDE (date) FROM quote WHERE date = $1 ORDER BY time", params=[self.datadate])
        logger.info("Shape of quote: %s x %s", self.quote.shape[0], self.quote.shape[1])

    def execute_query(self, idx: int, tags: Set, query_str: str, parameter: str, runidx: int) -> int:
        """
        Safely executes the query string using the loaded data and parameters.
        """
        # Create a restricted execution context
        eval_context = {
            "duckdb": duckdb,
            "timedelta": timedelta,
            "master": self.master,
            "trade": self.trade,
            "quote": self.quote,
            **self.params
        }
        return eval(f"duckdb.sql('{query_str}', params=[{parameter}])", eval_context)

    def write_csv(self, res, outFile: Path) -> None:
        res.write_csv(outFile)

class QueryExecutorPandas:
    """
    Handles the setup, execution of Pandas queries
    on NYSE TAQ hive-partitioned parquet files.
    """

    def __init__(self, param: Dict[str, Any]) -> None:
        # Dataframes
        self.master: Optional[pd.DataFrame] = None
        self.trade: Optional[pd.DataFrame] = None
        self.quote: Optional[pd.DataFrame] = None

        # Parameters available for queries

        self.params: Dict[str, Any] = param

    def load_resources(self, db_path: Path) -> None:
        """Loads database schemas."""
        logger.info("loading hive-partitioned tables at %s", db_path)

        import pyarrow.dataset as ds
        master_ds=ds.dataset(db_path / "master", format="parquet", partitioning="hive")
        datadate = master_ds.head(1).column("date")[0].as_py()
        master = master_ds.to_table(filter=(ds.field("date") == datadate)).drop("date")
        master = master.set_column(master.schema.get_field_index("sym"), "sym", master.column("sym").dictionary_encode())
        self.master = master.to_pandas()
        logger.info("Shape of master: %s x %s", self.master.shape[0], self.master.shape[1])
        self.master['ex'] = pd.Categorical(self.master['ex'], categories=sorted(self.master['ex'].unique()), ordered=True)
        exnames = pd.read_parquet(db_path / "exnames.parquet")
        self.params["exnames"] = dict(zip(exnames["ex"], exnames["name"]))

        logger.info("loading trade as a pyarrow dataset")
        trade_ds=ds.dataset(db_path / "trade", format="parquet", partitioning="hive")
        trade = trade_ds.to_table(filter=(ds.field("date") == datadate)).drop("date")
        trade = trade.set_column(trade.schema.get_field_index("sym"), "sym", trade.column("sym").dictionary_encode())
        logger.info("converting to pandas")
        self.trade = trade.to_pandas().sort_values(by="time", kind='stable')
        self.trade['ex'] = pd.Categorical(self.trade['ex'], categories=sorted(self.trade['ex'].unique()), ordered=True)
        logger.info("Shape of trade: %s x %s", self.trade.shape[0], self.trade.shape[1])

        logger.info("loading quote as a pyarrow dataset")
        quote_ds=ds.dataset(db_path / "quote", format="parquet", partitioning="hive")
        quote = quote_ds.to_table(filter=(ds.field("date") == datadate)).drop("date")
        quote = quote.set_column(quote.schema.get_field_index("sym"), "sym", quote.column("sym").dictionary_encode())
        logger.info("converting to pandas")
        self.quote = quote.to_pandas().sort_values(by="time", kind='stable')
        self.quote['ex'] = pd.Categorical(self.quote['ex'], categories=sorted(self.quote['ex'].unique()), ordered=True)
        logger.info("Shape of quote: %s x %s", self.quote.shape[0], self.quote.shape[1])

    def execute_query(self, idx: int, tags: Set, query_str: str, parameter: str, runidx: int) -> int:
        """
        Safely executes the query string using the loaded data and parameters.
        """
        # Create a restricted execution context
        eval_context = {
            "pd": pd,
            "np": np,
            "timedelta": timedelta,
            "master": self.master,
            "trade": self.trade,
            "quote": self.quote,
            **self.params
        }
        return eval(query_str, eval_context)

    def write_csv(self, res, outFile: Path) -> None:
        if isinstance(res.index, pd.MultiIndex):
            res.reset_index(inplace=True)
        for col in res.select_dtypes(include=['timedelta64']).columns:
            if col == 'minute':
                res = res.assign(**{col: res[col].apply(lambda td: "" if pd.isnull(td) else f"{td.seconds//3600:02}:{(td.seconds%3600)//60:02}")})
            else:
                res = res.assign(**{col: res[col].apply(lambda td: "" if pd.isnull(td) else f"{td.days}D{td.seconds//3600:02}:{(td.seconds%3600)//60:02}:{td.seconds%60:02}.{td.microseconds:06}{td.nanoseconds:03}")})
        for col in res.select_dtypes(include=['bool']).columns:
            res = res.assign(**{col: np.where(res[col], '1', '0')}) # Convert boolean to '1'/'0' strings for better kdb+ compatibility

        res.to_csv(outFile, index=False)


def main(args) -> None:
    start_time: datetime = datetime.now()
    if not args.db.exists():
        logger.error("Database does not exist at %s", args.db)
        sys.exit(1)

    tags = {} if args.tags is None else set(args.tags.strip().split(","))
    # Ensure output directory exists
    args.result.parent.mkdir(parents=True, exist_ok=True)

    # Initialize Runner
    device = get_device(args.db)
    logger.info("Loading parameter files...")
    engine = args.engine.lower()
    if engine == "polars":
        import polars as pl
        globals()['pl'] = pl
        params = load_parameters(args.paramdir)
        runner = QueryExecutorPolars(params)
        threadnr = pl.thread_pool_size()
    elif engine == "polars_inmemory":
        import polars as pl
        globals()['pl'] = pl
        params = load_parameters(args.paramdir)
        runner = QueryExecutorPolarsInMemory(params)
        threadnr = pl.thread_pool_size()
    elif engine == "duckdb_inmemory":
        import duckdb
        globals()['duckdb'] = duckdb
        params = load_parameters(args.paramdir)
        runner = QueryExecutorDuckDBInMemory(params)
        threadnr = os.environ['DUCKDB_THREADS']
        duckdb.execute(f"SET threads = {threadnr}")
    elif engine == "pykx":
        os.environ['PYKX_4_1_ENABLED'] = 'True'  # needed for change_dir parameter below
        import pykx as kx
        globals()['kx'] = kx
        params = load_parameters(args.paramdir)
        runner = QueryExecutorPyKX(params)
        threadnr = kx.q.system.num_threads
    elif engine == "pykx_inmemory":
        os.environ['PYKX_4_1_ENABLED'] = 'True'  # needed for change_dir parameter below
        import pykx as kx
        globals()['kx'] = kx
        params = load_parameters(args.paramdir)
        runner = QueryExecutorPyKXInMemory(params)
        threadnr = kx.q.system.num_threads
    elif engine == "pykxq":
        os.environ['PYKX_4_1_ENABLED'] = 'True'  # needed for change_dir parameter below
        import pykx as kx
        globals()['kx'] = kx
        runner = QueryExecutorPyKXQ(args.paramdir)
        threadnr = kx.q.system.num_threads
    elif engine == "pandas":
        import numpy as np
        import pandas as pd
        globals()['np'] = np
        globals()['pd'] = pd
        params = load_parameters(args.paramdir)
        runner = QueryExecutorPandas(params)
        threadnr = os.environ['NUMEXPR_NUM_THREADS']
    else:
        raise ValueError(f"Invalid engine parameter: {args.engine}")

    # Load DB and Params (Time this operation for the first CSV row)
    io_load_start = get_io_stat(device)
    t_load_start = time_mod.perf_counter_ns()
    runner.load_resources(args.db)
    t_load_elapsed = time_mod.perf_counter_ns() - t_load_start
    io_load_end = get_io_stat(device)

    # Initialize Result File
    headers: List[str] = [
        "compparam", "threadcount", "idx", "tags", "query", "status",
        "run1timeNS", "run2timeNS", "run3timeNS",
        "run1memKB",
        "run1ioKB", "run2ioKB", "run3ioKB"
    ]
    row_start = ["nyi", threadnr]
    # Write Mode: Overwrite existing
    with open(args.result, 'w', newline='', encoding='utf-8') as f_out:
        writer = csv.writer(f_out, delimiter='|')
        writer.writerow(headers)

        # Log DB Load time as idx 0
        writer.writerow(row_start +[0, "nyi", "loaddb", "success", t_load_elapsed, None, None,
                         None, io_load_end - io_load_start, None, None])
        f_out.flush() # Ensure header is written

        # Process Queries
        if not args.queryfile.exists():
            logger.error("Query file not found: %s", args.queryfile)
            sys.exit(3)

        if not args.queryoutput is None:
            args.queryoutput.mkdir(parents=True, exist_ok=True)

        with open(args.queryfile, 'r', encoding='utf-8') as queryfile, \
             open(args.querymeta, "r", encoding="utf-8") as querymeta:
            queryreader = csv.DictReader(queryfile, delimiter='|')
            querymetareader = csv.DictReader(querymeta, delimiter='|')

            for row, rowmeta in zip(queryreader, querymetareader):
                idx = row['idx'].strip()
                if idx != rowmeta['idx'].strip():
                    logger.error("Index mismatch between the query and the query meta files: %s vs %s", idx, rowmeta['idx'].strip())
                    sys.exit(4)
                query = row['query'].strip()
                querytags = set(row['tags'].strip().split(",") + rowmeta['tags'].strip().split(","))
                querytags.discard("")
                if idx.startswith("#"):
                    idx = idx[1:]
                    result = QueryResult(query, "skip")
                elif query == '':
                    result = QueryResult(query, "emptyquery")
                elif len(tags) > 0 and len(tags & querytags) == 0:
                    result = QueryResult(query, "tagfiltered")
                else:
                    result = run_query(runner, args.db, device, idx, querytags, query, row['parameter'].strip(), args.queryoutput)

                writer.writerow(row_start + [idx, ",".join(querytags)] + result.to_csv_row())
                f_out.flush() # Write immediately to disk

    elapsed = datetime.now() - start_time
    logger.info("Benchmarking completed in %s. Results saved to %s", elapsed, args.result)


if os.getenv('FLUSH') is None:
    logger.error("Environment variable FLUSH is not set. Maybe config/queryenv was not loaded.")
    sys.exit(2)

parser = argparse.ArgumentParser(
        description="Query Runner & Benchmarker using NYSE TAQ data",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )


parser.add_argument('-db', type=Path, required=True, help="Path to hive-partitioned parquet DB root")
parser.add_argument('-engine', type=str, choices=["polars", "polars_inmemory", "duckdb_inmemory", "pykx", "pykx_inmemory", "pykxq", "pandas"],
    required=True, help="Query engine. Currently supported polars and PyKX")
parser.add_argument('-queryfile', type=Path, required=True, help="PSV file containing queries")
parser.add_argument('-querymeta', type=Path, required=True, help="PSV file containing the query metas")
parser.add_argument('-paramdir', type=Path, required=True, help="Directory containing parameter txt files")
parser.add_argument('-tags', type=str, required=False, help="Comma separated tags for filtering queries.")
parser.add_argument('-queryoutput', type=Path, required=False, help="Directory to save query results.")

default_result = Path(f"results/nysetaq_query_results.psv")
parser.add_argument('-result', type=Path, default=default_result, help="Output PSV file path")

args = parser.parse_args()

if __name__ == '__main__':
    main(args)