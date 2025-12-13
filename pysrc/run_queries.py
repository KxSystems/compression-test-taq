"""
Script to run polars queries on NYSE TAQ and collect performance metrics (like execution time)

Environment variables:
"""
import argparse
import csv
import gc
import os
import logging
import psutil
import subprocess
import sys
from datetime import datetime,time # time is used in queries
import time as time_mod   # alias to avoid naming conflict
from dataclasses import dataclass, field

from pathlib import Path
from typing import Any, Dict, List, Optional

import polars as pl
os.environ['PYKX_4_1_ENABLED'] = 'True'  # needed for change_dir parameter below
import pykx as kx

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def load_parameters(param_dir: Path) -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    """Reads parameter text files into the params dictionary."""
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
    return params

@dataclass
class QueryResult:
    """Data class to hold the results of a query benchmark."""
    thread_count: int
    idx: str
    query_raw: str
    run1_time_ms: int
    run2_time_ms: int
    run3_time_ms: int
    run1_mem_KB: int   # Not Yet Implemented
    run1_io_KB: int
    run2_io_KB: int
    run3_io_KB: int

    def to_csv_row(self) -> List[Any]:
        return [
            self.thread_count,
            self.idx,
            self.query_raw,
            self.run1_time_ms,
            self.run2_time_ms,
            self.run3_time_ms,
            self.run1_mem_KB,
            self.run1_io_KB,
            self.run2_io_KB,
            self.run3_io_KB
        ]

def run_query(runner, db_path: Path, device: str, idx: str, query: str) -> QueryResult:
    """
    Runs a specific query 3 times (Cold, Warm, Warm) and records timing.
    """
    times: List[float] = []
    ios: List[float] = []
    for runidx in range(3):
        iteration_label = "Cold" if runidx == 0 else f"Warm-{runidx}"
        logger.info(f"[{idx}] Run {runidx+1}/3 ({iteration_label}): {query[:50]}...")
        # Prepare environment
        if runidx == 0:
            subprocess.run([os.getenv('FLUSH'), db_path], check=True,capture_output=True)
        gc.collect()
        # Execute and Time
        io_Start = psutil.disk_io_counters(perdisk=True)[device].read_bytes // 1000
        t_start = time_mod.perf_counter_ns()
        try:
            t_end = runner.execute_query(query, idx, runidx)
        except Exception as e:
            logger.error(f"Query {idx} failed: {e}")
            # Return 0.0 or -1.0 to indicate failure in results
            return QueryResult(pl.thread_pool_size(), idx, query, -1.0, -1.0, -1.0)
        io_End = psutil.disk_io_counters(perdisk=True)[device].read_bytes // 1000
        times.append(t_end - t_start)
        ios.append(io_End-io_Start)

    return QueryResult(
        thread_count=pl.thread_pool_size(),
        idx=idx, query_raw=query,
        run1_time_ms=times[0], run2_time_ms=times[1], run3_time_ms=times[2],
        run1_mem_KB=None, run1_io_KB=ios[0], run2_io_KB=ios[1], run3_io_KB=ios[2]
    )

class QueryExecutorPyKX:
    """
    Handles the setup, execution of PyKX Python queries
    on NYSE TAQ kdb+ database.
    """
    def __init__(self, param:Dict[str, Any]):
        self.db: kx.DB = None
        # Parameters available for queries
        self.params: Dict[str, Any] = param

    def load_resources(self, db_path: Path) -> None:
        """Loads kdb+ database"""
        logger.info(f"loading kdb DB {db_path}")
        self.db = kx.DB(path=db_path, change_dir=False)

    def execute_query(self, query_str: str, idx: int, runidx: int) -> int:
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
            # We use eval here because the requirement is to run arbitrary queries
            # defined in a text file.
            # .collect() triggers the actual computation for LazyFrames
            res = eval(query_str, {"__builtins__": None}, eval_context)
            t_end = time_mod.perf_counter_ns()
            logger.info(f"[{idx}]   Shape of the result: {res.shape[0]} x {res.shape[1]}")
        else:
                eval(query_str, {"__builtins__": None}, eval_context)
                t_end = time_mod.perf_counter_ns()
        return t_end

class QueryExecutorPyKXQ:
    """
    Handles the setup, execution of PyKX q queries
    on NYSE TAQ kdb+ database.
    """
    def __init__(self, paramdir: Path):
        self.db: kx.DB = None
        self.paramdir: Path = paramdir


    def load_resources(self, db_path: Path) -> None:
        """Loads kdb+ database"""
        logger.info(f"loading kdb DB {db_path}")
        self.db = kx.DB(path=db_path, change_dir=False)
        kx.q('system "l src/getQueryParameters.q"')
        kx.q(f'getQueryParameters hsym `$"{self.paramdir}"')

    def execute_query(self, query_str: str, idx: int, runidx: int) -> int:
        """
        Safely executes the query string using the loaded data and parameters.
        """
        if runidx == 0:
            # We use eval here because the requirement is to run arbitrary queries
            # defined in a text file.
            # .collect() triggers the actual computation for LazyFrames
            res = kx.q(query_str)
            t_end = time_mod.perf_counter_ns()
            logger.info(f"[{idx}]   Shape of the result: {res.shape[0]} x {res.shape[1]}")
        else:
                kx.q(query_str)
                t_end = time_mod.perf_counter_ns()
        return t_end


class QueryExecutorPolars:
    """
    Handles the setup, execution of Polars queries
    on NYSE TAQ hive-partitioned parquet files.
    """

    def __init__(self, param:Dict[str, Any]):
        # Dataframes (Lazy)
        self.master: Optional[pl.LazyFrame] = None
        self.trade: Optional[pl.LazyFrame] = None
        self.quote: Optional[pl.LazyFrame] = None

        # Parameters available for queries
        self.params: Dict[str, Any] = param

    def load_resources(self, db_path: Path) -> None:
        """Loads database schemas."""
        logger.info(f"loading hive-partitioned tables at {db_path}")
        # Load Polars Scans
        self.master = pl.scan_parquet(db_path / "master/date=*/*.parquet", hive_partitioning=True)

        exnames = pl.scan_parquet(db_path / "exnames.parquet").collect()
        self.params["exnames"] = dict(zip(exnames["ex"], exnames["name"]))

        self.trade = pl.scan_parquet(db_path / "trade/date=*/*.parquet", hive_partitioning=True)
        self.quote = pl.scan_parquet(db_path / "quote/date=*/*.parquet", hive_partitioning=True)

    def execute_query(self, query_str: str, idx: int, runidx: int) -> int:
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
        if runidx == 0:
            # We use eval here because the requirement is to run arbitrary queries
            # defined in a text file.
            # .collect() triggers the actual computation for LazyFrames
            res = eval(query_str, {"__builtins__": None}, eval_context).collect()
            t_end = time_mod.perf_counter_ns()
            logger.info(f"[{idx}]   Shape of the result: {res.shape[0]} x {res.shape[1]}")
        else:
                eval(query_str, {"__builtins__": None}, eval_context).collect()
                t_end = time_mod.perf_counter_ns()
        return t_end

def main(args):
    start_time = datetime.now()

    # Ensure output directory exists
    args.result.parent.mkdir(parents=True, exist_ok=True)

    # Initialize Runner
    device = subprocess.run(["./src/resolve_device.sh", args.db],
                                     capture_output=True, text=True).stdout.split('\n')[0].strip()  # TODO: add error handling

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
    io_load_Start = psutil.disk_io_counters(perdisk=True)[device].read_bytes // 1000
    t_load_start = time_mod.perf_counter_ns()
    runner.load_resources(args.db)
    t_load_elapsed = time_mod.perf_counter_ns() - t_load_start
    io_load_End = psutil.disk_io_counters(perdisk=True)[device].read_bytes // 1000

    # Initialize Result File
    headers = [
        "threadcount", "idx", "query",
        "run1timeNS", "run2timeNS", "run3timeNS",
        "run1memKB",
        "run1ioKB", "run2ioKB", "run3ioKB"
    ]

    # Write Mode: Overwrite existing
    with open(args.result, 'w', newline='', encoding='utf-8') as f_out:
        writer = csv.writer(f_out, delimiter='|')
        writer.writerow(headers)

        # Log DB Load time as idx 0
        writer.writerow([pl.thread_pool_size(), 0, "loaddb", t_load_elapsed, None, None,
                         None, io_load_End - io_load_Start, None, None])
        f_out.flush() # Ensure header is written

        # Process Queries
        if not args.queryfile.exists():
            logger.error(f"Query file not found: {args.queryfile}")
            sys.exit(1)

        with open(args.queryfile, 'r', encoding='utf-8') as f_in:
            # Using DictReader to handle pipe delimiter
            reader = csv.DictReader(f_in, delimiter='|')

            for row in reader:
                idx = row.get('idx', '').strip()
                query = row.get('query', '').strip()
                if idx.startswith("#"):
                    result = QueryResult(thread_count=pl.thread_pool_size(), idx=idx[1:], query_raw=query,
                               run1_time_ms=None, run2_time_ms=None, run3_time_ms=None,
                               run1_mem_KB=None, run1_io_KB=None, run2_io_KB=None, run3_io_KB=None)
                elif query == '':
                    result = QueryResult(thread_count=pl.thread_pool_size(), idx=idx, query_raw=query,
                               run1_time_ms=None, run2_time_ms=None, run3_time_ms=None,
                               run1_mem_KB=None, run1_io_KB=None, run2_io_KB=None, run3_io_KB=None)
                else:
                    result = run_query(runner, args.db, device, idx, query)

                writer.writerow(result.to_csv_row())
                f_out.flush() # Write immediately to disk

    elapsed = datetime.now() - start_time
    logger.info(f"Benchmarking completed in {elapsed}. Results saved to {args.result}")


if os.getenv('FLUSH') is None:
    logger.error("Environment variable FLUSH is not set. Maybe config/env was not loaded.")
    sys.exit(2)

parser = argparse.ArgumentParser(
        description="Query Runner & Benchmarker using NYSE TAQ data",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )


parser.add_argument('-db', type=Path, required=True, help="Path to hive-partitioned parquet DB root")
parser.add_argument('-engine', type=str, choices=["polars", "pykx", "pykxq"], required=True, help="Query engine. Currently supported polars and PyKX")
parser.add_argument('-queryfile', type=Path, required=True, help="PSV file containing queries")
parser.add_argument('-paramdir', type=Path, required=True, help="Directory containing parameter txt files")

default_result = Path(f"results/nysetaq_query_results.psv")
parser.add_argument('-result', type=Path, default=default_result, help="Output PSV file path")

args = parser.parse_args()

if __name__ == '__main__':
    main(args)