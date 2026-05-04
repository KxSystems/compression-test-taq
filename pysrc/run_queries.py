"""
Script to run queries on NYSE TAQ and collect performance metrics (like execution time)

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
from datetime import datetime, time, timedelta  # time is used in queries
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
        return resolve_device.stdout.split('\n')[0].strip()

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
            None,  # Not Yet Implemented
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
        if runidx == 0:
            subprocess.run([os.getenv('FLUSH'), db_path], check=True, capture_output=True)
        gc.collect()
        io_start = get_io_stat(device)
        t_start = time_mod.perf_counter_ns()
        try:
            res = runner.execute_query(idx, tags, query, parameter, runidx)
            t_end = time_mod.perf_counter_ns()
            io_end = get_io_stat(device)
        except Exception as e:
            logger.error("Query %s failed: %s", idx, e)
            return QueryResult(query, "error")
        if runidx == 0:
            logger.info("[%s]   Shape of the result: %s x %s", idx, res.shape[0], res.shape[1])
            if queryoutput is not None:
                outFile = queryoutput / f"queryoutput_{idx}.csv"
                runner.write_csv(res, outFile)
        times.append(t_end - t_start)
        ios.append(io_end - io_start)

    return QueryResult(query, "success", *times, *ios)


def main(args) -> None:
    start_time: datetime = datetime.now()
    if not args.db.exists():
        logger.error("Database does not exist at %s", args.db)
        sys.exit(1)

    tags = {} if args.tags is None else set(args.tags.strip().split(","))
    args.result.parent.mkdir(parents=True, exist_ok=True)

    device = get_device(args.db)
    logger.info("Loading parameter files...")
    engine = args.engine.lower()

    if engine == "polars":
        from executors.ondisk.polars import QueryExecutorPolars
        import polars as pl
        params = load_parameters(args.paramdir)
        runner = QueryExecutorPolars(params)
        threadnr = pl.thread_pool_size()
    elif engine == "polars_inmemory":
        from executors.inmemory.polars import QueryExecutorPolarsInMemory
        import polars as pl
        params = load_parameters(args.paramdir)
        runner = QueryExecutorPolarsInMemory(params)
        threadnr = pl.thread_pool_size()
    elif engine == "duckdb_inmemory":
        from executors.inmemory.duckdb import QueryExecutorDuckDBInMemory
        import duckdb
        params = load_parameters(args.paramdir)
        runner = QueryExecutorDuckDBInMemory(params)
        threadnr = os.environ['DUCKDB_THREADS']
        duckdb.execute(f"SET threads = {threadnr}")
    elif engine == "pykx":
        from executors.ondisk.pykx import QueryExecutorPyKX
        import pykx as kx
        params = load_parameters(args.paramdir)
        runner = QueryExecutorPyKX(params)
        threadnr = kx.q.system.num_threads
    elif engine == "pykx_inmemory":
        from executors.inmemory.pykx import QueryExecutorPyKXInMemory
        import pykx as kx
        params = load_parameters(args.paramdir)
        runner = QueryExecutorPyKXInMemory(params)
        threadnr = kx.q.system.num_threads
    elif engine == "pykxq":
        from executors.ondisk.pykx import QueryExecutorPyKXQ
        import pykx as kx
        runner = QueryExecutorPyKXQ(args.paramdir)
        threadnr = kx.q.system.num_threads
    elif engine == "pandas":
        from executors.inmemory.pandas import QueryExecutorPandas
        params = load_parameters(args.paramdir)
        runner = QueryExecutorPandas(params)
        threadnr = os.environ['NUMEXPR_NUM_THREADS']
    else:
        raise ValueError(f"Invalid engine parameter: {args.engine}")

    io_load_start = get_io_stat(device)
    t_load_start = time_mod.perf_counter_ns()
    runner.load_resources(args.db)
    t_load_elapsed = time_mod.perf_counter_ns() - t_load_start
    io_load_end = get_io_stat(device)

    headers: List[str] = [
        "compparam", "threadcount", "idx", "tags", "query", "status",
        "run1timeNS", "run2timeNS", "run3timeNS",
        "run1memKB",
        "run1ioKB", "run2ioKB", "run3ioKB"
    ]
    row_start = ["nyi", threadnr]
    with open(args.result, 'w', newline='', encoding='utf-8') as f_out:
        writer = csv.writer(f_out, delimiter='|')
        writer.writerow(headers)
        writer.writerow(row_start + [0, "nyi", "loaddb", "success", t_load_elapsed, None, None,
                         None, io_load_end - io_load_start, None, None])
        f_out.flush()

        if not args.queryfile.exists():
            logger.error("Query file not found: %s", args.queryfile)
            sys.exit(3)

        if args.queryoutput is not None:
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
                f_out.flush()

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
