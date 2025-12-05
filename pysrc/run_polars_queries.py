"""
Script to run polars queries on NYSE TAQ and collect performance metrics (like execution time)

Environment variables:
    SCANAPI_CACHE   True/False, Passed to polars.scan_parquet cache parameter
"""
import argparse
import csv
import gc
import logging
import os
import subprocess
import sys
from datetime import time # time is used in queries
import time as time_mod   # alias to avoid naming conflict
from dataclasses import dataclass, field

from pathlib import Path
from typing import Any, Dict, List, Optional

import polars as pl

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


@dataclass
class QueryResult:
    """Data class to hold the results of a query benchmark."""
    thread_count: int
    idx: str
    query_raw: str
    run1_time_ms: float
    run2_time_ms: float
    run3_time_ms: float
    # Placeholder for future memory/IO implementation
    metrics: List[Optional[float]] = field(default_factory=lambda: [None] * 6)

    def to_csv_row(self) -> List[Any]:
        return [
            self.thread_count,
            self.idx,
            self.query_raw,
            self.run1_time_ms,
            self.run2_time_ms,
            self.run3_time_ms,
            *self.metrics
        ]


class BenchmarkRunner:
    """
    Handles the setup, execution, and reporting of Polars queries
    on NYSE TAQ hive-partitioned parquet files.
    """

    def __init__(self, db_path: Path, param_dir: Path):
        self.db_path = db_path
        self.param_dir = param_dir

        # Dataframes (Lazy)
        self.master: Optional[pl.LazyFrame] = None
        self.trade: Optional[pl.LazyFrame] = None
        self.quote: Optional[pl.LazyFrame] = None

        # Parameters
        self.params: Dict[str, Any] = {}

    def load_resources(self) -> None:
        """Loads database schemas and parameter files."""
        t0 = time_mod.perf_counter()
        logger.info("Initializing database connections...")

        scan_parquet_args = {}
        if os.getenv('SCANAPI_CACHE'):
            scan_parquet_args['cache'] = os.getenv('SCANAPI_CACHE').strip().lower in ["true", "1", "yes", "y"]
            logger.info(f"cache parameter of scan_parquet was set to {scan_parquet_args['cache']}")

        # Load Polars Scans
        self.master = pl.scan_parquet(self.db_path / "master/date=*/*.parquet", hive_partitioning=True, **scan_parquet_args)
        self.trade = pl.scan_parquet(self.db_path / "trade/date=*/*.parquet", hive_partitioning=True, **scan_parquet_args)
        self.quote = pl.scan_parquet(self.db_path / "quote/date=*/*.parquet", hive_partitioning=True, **scan_parquet_args)

        logger.info("Loading parameter files...")
        try:
            self._load_parameters()
        except FileNotFoundError as e:
            logger.error(f"Failed to load parameters: {e}")
            sys.exit(1)

        duration = (time_mod.perf_counter() - t0) * 1000
        logger.info(f"Resources loaded in {duration:.2f} ms")

    def _load_parameters(self) -> None:
        """Reads parameter text files into the params dictionary."""
        def read_single(filename: str) -> str:
            return (self.param_dir / filename).read_text(encoding='utf-8').strip()

        def read_list(filename: str) -> List[str]:
            content = (self.param_dir / filename).read_text(encoding='utf-8')
            return [line.strip() for line in content.splitlines() if line.strip()]

        self.params = {
            "aFreqSym": read_single("aFreqSym.txt"),
            "anInfreqSym": read_single("anInfreqSym.txt"),
            "someSyms1": read_list("someSyms1.txt"),
            "someSyms2": read_list("someSyms2.txt"),
            "infreqIdList": read_list("infreqIdList.txt"),
        }

    @staticmethod
    def clear_system_cache() -> None:
        """
        Attempts to clear the OS page cache.
        Requires sudo privileges on Linux. Fails gracefully otherwise.
        """
        if sys.platform != "linux":
            logger.warning("Cache clearing is only supported on Linux. Skipping.")
            return

        try:
            # Sync first to ensure data is written to disk
            subprocess.run(['sync'], check=True)
            # Drop caches
            subprocess.run(
                ['sudo', 'bash', '-c', "echo 3 > /proc/sys/vm/drop_caches"],
                check=True,
                capture_output=True
            )
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to clear page cache (needs sudo): {e}")
        except Exception as e:
            logger.warning(f"Unexpected error clearing cache: {e}")

    def _execute_query(self, query_str: str) -> pl.DataFrame:
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

        # We use eval here because the requirement is to run arbitrary queries
        # defined in a text file.
        # .collect() triggers the actual computation for LazyFrames
        return eval(query_str, {"__builtins__": None}, eval_context).collect()

    def run_query(self, idx: str, query_str: str) -> QueryResult:
        """
        Runs a specific query 3 times (Cold, Warm, Warm) and records timing.
        """
        times: List[float] = []

        for i in range(3):
            iteration_label = "Cold" if i == 0 else f"Warm-{i}"
            logger.info(f"[{idx}] Run {i+1}/3 ({iteration_label}): {query_str[:50]}...")

            # Prepare environment
            if i == 0:
                self.clear_system_cache()

            gc.collect()

            # Execute and Time
            t_start = time_mod.perf_counter()
            try:
                if i == 0:
                    res = self._execute_query(query_str)
                    t_end = time_mod.perf_counter()
                    logger.info(f"[{idx}]   Shape of the result: {res.shape[0]} x {res.shape[1]}")
                    del res
                else:
                    self._execute_query(query_str)
                    t_end = time_mod.perf_counter()
            except Exception as e:
                logger.error(f"Query {idx} failed: {e}")
                # Return 0.0 or -1.0 to indicate failure in results
                return QueryResult(pl.thread_pool_size(), idx, query_str, -1.0, -1.0, -1.0)
            times.append((t_end - t_start) * 1000)

        return QueryResult(
            thread_count=pl.thread_pool_size(),
            idx=idx,
            query_raw=query_str,
            run1_time_ms=times[0],
            run2_time_ms=times[1],
            run3_time_ms=times[2]
        )


def main():
    parser = argparse.ArgumentParser(
        description="Polars Query Runner & Benchmarker using NYSE TAQ data in parquet format",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument('-db', type=Path, required=True, help="Path to hive-partitioned parquet DB root")
    parser.add_argument('-queryfile', type=Path, required=True, help="PSV file containing queries")
    parser.add_argument('-paramdir', type=Path, required=True, help="Directory containing parameter txt files")

    default_result = Path(f"results/polars_{pl.thread_pool_size()}Threads.psv")
    parser.add_argument('-result', type=Path, default=default_result, help="Output PSV file path")

    args = parser.parse_args()

    # Ensure output directory exists
    args.result.parent.mkdir(parents=True, exist_ok=True)

    # Initialize Runner
    runner = BenchmarkRunner(args.db, args.paramdir)

    # Load DB and Params (Time this operation for the first CSV row)
    t_load_start = time_mod.perf_counter()
    runner.load_resources()
    t_load_end = time_mod.perf_counter()
    load_time_ms = (t_load_end - t_load_start) * 1000

    # Initialize Result File
    headers = [
        "threadcount", "idx", "query",
        "run1timeMS", "run2timeMS", "run3timeMS",
        "run1memKB", "run2memKB", "run3memKB",
        "run1ioKB", "run2ioKB", "run3ioKB"
    ]

    # Write Mode: Overwrite existing
    with open(args.result, 'w', newline='', encoding='utf-8') as f_out:
        writer = csv.writer(f_out, delimiter='|')
        writer.writerow(headers)

        # Log DB Load time as idx 0
        writer.writerow([pl.thread_pool_size(), 0, "loaddb", load_time_ms] + [None] * 8)
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

                if not idx or idx.startswith("#"):
                    continue

                result = runner.run_query(idx, query)
                writer.writerow(result.to_csv_row())
                f_out.flush() # Write immediately to disk

    logger.info(f"Benchmarking complete. Results saved to {args.result}")


if __name__ == '__main__':
    main()