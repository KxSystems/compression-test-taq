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
from datetime import datetime,time, timedelta # time is used in queries
import time as time_mod   # alias to avoid naming conflict

from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import polars as pl
os.environ['PYKX_4_1_ENABLED'] = 'True'  # needed for change_dir parameter below
import pykx as kx

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

    with open(param_dir / "timeBuckets.txt", "r", encoding="utf-8") as f:
        params["timeBuckets"] = {line.split("=")[0].strip():
                                 datetime.strptime(line.split("=")[1].strip()[2:], "%H:%M:%S.%f").time()
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

def run_query(runner, db_path: Path, device: str, idx: str, tags: Set, query: str) -> QueryResult:
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
        io_Start = get_io_stat(device)
        t_start = time_mod.perf_counter_ns()
        try:
            t_end = runner.execute_query(idx, tags, query, runidx)
        except Exception as e:
            logger.error("Query %s failed: %s", idx, e)
            # Return 0.0 or -1.0 to indicate failure in results
            return QueryResult(query, "error")
        io_End = get_io_stat(device)
        times.append(t_end - t_start)
        ios.append(io_End-io_Start)

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

    def execute_query(self, idx: int, tags: Set, query_str: str, runidx: int) -> int:
        """
        Safely executes the query string using the loaded data and parameters.
        """
        # Create a restricted execution context
        eval_context = {
            "kx":kx,
            "time": time,
            "db": self.db,
            **self.params
        }
        if runidx == 0:
            res = eval(query_str, eval_context)
            t_end = time_mod.perf_counter_ns()
            logger.info("[%s]   Shape of the result: %s x %s", idx, res.shape[0], res.shape[1])
        else:
            eval(query_str, eval_context)
            t_end = time_mod.perf_counter_ns()
        return t_end

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

    def execute_query(self, idx: int, tags: Set, query_str: str, runidx: int) -> int:
        """
        Safely executes the query string using the loaded data and parameters.
        """
        if runidx == 0:
            res = kx.q(query_str)
            t_end = time_mod.perf_counter_ns()
            logger.info("[%s]   Shape of the result: %s x %s", idx, res.shape[0], res.shape[1])
        else:
            kx.q(query_str)
            t_end = time_mod.perf_counter_ns()
        return t_end


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

    def execute_query(self, idx: int, tags: Set, query_str: str, runidx: int) -> int:
        """
        Safely executes the query string using the loaded data and parameters.
        """
        # Create a restricted execution context
        eval_context = {
            "pl": pl,
            "time": time,
            "master": self.master,
            "trade": self.trade,
            "quote": self.quote,
            **self.params
        }
        res = eval(query_str, eval_context) if "dataframeresult" in tags else eval(query_str, eval_context).collect()
        t_end = time_mod.perf_counter_ns()

        if runidx == 0:
            # .collect() triggers the actual computation for LazyFrames
            logger.info("[%s]   Shape of the result: %s x %s", idx, res.shape[0], res.shape[1])

        return t_end

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

    if args.engine.lower() == "polars":
        params = load_parameters(args.paramdir)
        runner = QueryExecutorPolars(params)
    elif args.engine.lower() == "pykx":
        params = load_parameters(args.paramdir)
        runner = QueryExecutorPyKX(params)
    elif args.engine.lower() == "pykxq":
        runner = QueryExecutorPyKXQ(args.paramdir)
    else:
        raise ValueError(f"Invalid engine parameter: {args.engine}")

    # Load DB and Params (Time this operation for the first CSV row)
    io_load_Start = get_io_stat(device)
    t_load_start = time_mod.perf_counter_ns()
    runner.load_resources(args.db)
    t_load_elapsed = time_mod.perf_counter_ns() - t_load_start
    io_load_End = get_io_stat(device)

    # Initialize Result File
    headers: List[str] = [
        "compparam", "threadcount", "idx", "tags", "query", "status",
        "run1timeNS", "run2timeNS", "run3timeNS",
        "run1memKB",
        "run1ioKB", "run2ioKB", "run3ioKB"
    ]
    row_start = ["nyi", pl.thread_pool_size()]
    # Write Mode: Overwrite existing
    with open(args.result, 'w', newline='', encoding='utf-8') as f_out:
        writer = csv.writer(f_out, delimiter='|')
        writer.writerow(headers)

        # Log DB Load time as idx 0
        writer.writerow(row_start +[0, "nyi", "loaddb", "success", t_load_elapsed, None, None,
                         None, io_load_End - io_load_Start, None, None])
        f_out.flush() # Ensure header is written

        # Process Queries
        if not args.queryfile.exists():
            logger.error("Query file not found: %s", args.queryfile)
            sys.exit(3)

        with open(args.queryfile, 'r', encoding='utf-8') as queryfile, \
             open(args.querymetafile, "r", encoding="utf-8") as querymetafile:
            queryreader = csv.DictReader(queryfile, delimiter='|')
            querymetareader = csv.DictReader(querymetafile, delimiter='|')

            for row, rowmeta in zip(queryreader, querymetareader):
                idx = row['idx'].strip()
                query = row['query'].strip()
                querytags = set(row['tags'].strip().split(",") + rowmeta['tags'].strip().split(","))
                if idx.startswith("#"):
                    idx = idx[1:]
                    result = QueryResult(query, "skip")
                elif query == '':
                    result = QueryResult(query, "emptyquery")
                elif len(tags) > 0 and len(tags & querytags) == 0:
                    result = QueryResult(query, "tagfiltered")
                else:
                    result = run_query(runner, args.db, device, idx, querytags, query)

                writer.writerow(row_start + [idx, row['tags'].strip()] + result.to_csv_row())
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
parser.add_argument('-engine', type=str, choices=["polars", "pykx", "pykxq"], required=True, help="Query engine. Currently supported polars and PyKX")
parser.add_argument('-queryfile', type=Path, required=True, help="PSV file containing queries")
parser.add_argument('-querymetafile', type=Path, required=True, help="PSV file containing the query metas")
parser.add_argument('-paramdir', type=Path, required=True, help="Directory containing parameter txt files")
parser.add_argument('-tags', type=str, required=False, help="Comma separated tags for filtering queries.")

default_result = Path(f"results/nysetaq_query_results.psv")
parser.add_argument('-result', type=Path, default=default_result, help="Output PSV file path")

args = parser.parse_args()

if __name__ == '__main__':
    main(args)