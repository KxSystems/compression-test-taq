import duckdb
import pandas as pd

import logging
from datetime import timedelta, datetime
from pathlib import Path
from typing import Any, Dict, Optional, Set
import time

logger = logging.getLogger(__name__)


class QueryExecutorDuckDBRelation:
    """
    Handles the setup, execution of DuckDB in-memory queries.
    """

    def __init__(self, param: Dict[str, Any]) -> None:
        self.datadate: Optional[Any] = None
        self.master: Optional[duckdb.DuckDBPyRelation] = None
        self.trade: Optional[duckdb.DuckDBPyRelation] = None
        self.quote: Optional[duckdb.DuckDBPyRelation] = None
        self.params: Dict[str, Any] = param
        self.params['timeBuckets'] = pd.DataFrame(list(self.params['timeBuckets'].items()), columns=['bucket', 'bound'])

    def load_resources(self, db_path: Path, datadate: datetime.date, writer, row_start, ios) -> None:
        logger.info("loading hive-partitioned tables at %s", db_path)

        io_load_start = ios.get_io_stat()
        t_load_start = time.perf_counter_ns()
        self.params["exnames"] = pd.read_parquet(db_path / "exnames.parquet")
        master = duckdb.read_parquet(str(db_path / "master/date=*/*.parquet"), hive_partitioning=True)
        self.master = duckdb.sql("SELECT * EXCLUDE (date) FROM master WHERE date=$1", params=[datadate])
        logger.info("Shape of master: %s x %s", self.master.shape[0], self.master.shape[1])

        logger.info("loading trade")
        trade = duckdb.read_parquet(str(db_path / "trade/date=*/*.parquet"), hive_partitioning=True)
        self.trade = duckdb.sql("SELECT * EXCLUDE (date) FROM trade WHERE date=$1", params=[datadate])

        logger.info("loading quote")
        quote = duckdb.read_parquet(str(db_path / "quote/date=*/*.parquet"), hive_partitioning=True)
        self.quote = duckdb.sql("SELECT * EXCLUDE (date) FROM quote WHERE date=$1", params=[datadate])
        t_load_elapsed = time.perf_counter_ns() - t_load_start
        io_load_end = ios.get_io_stat()
        writer.writerow(row_start + [0, "load", "load a partition into memory", "success", t_load_elapsed, None, None,
                         None, io_load_end - io_load_start, None, None])


        io_load_start = ios.get_io_stat()
        t_load_start = time.perf_counter_ns()
        logger.info("applying transformations")
        trade = duckdb.sql("SELECT make_timestamp_ns(epoch_ns(date)+time) AS time, " +
            "make_timestamp_ns(epoch_ns(date)+participantTimestamp) AS participantTimestamp, " +
            "make_timestamp_ns(epoch_ns(date)+tradeReportingFacilityTRFTimestamp) AS tradeReportingFacilityTRFTimestamp, " +
            "row_number() OVER () AS rn, * EXCLUDE (date, time, participantTimestamp, tradeReportingFacilityTRFTimestamp) FROM trade")  # rowid ensures stable sorting for same-timestamp records
        logger.info("Shape of trade: %s x %s", self.trade.shape[0], self.trade.shape[1])

        logger.info("applying transformations")
        quote = duckdb.sql("SELECT make_timestamp_ns(epoch_ns(date)+time) AS time, " +
            "make_timestamp_ns(epoch_ns(date)+participantTimestamp) AS participantTimestamp, " +
            "make_timestamp_ns(epoch_ns(date)+FINRAADFTimestamp) AS FINRAADFTimestamp, " +
            "row_number() OVER () AS rn, * EXCLUDE (date, time, participantTimestamp, FINRAADFTimestamp) FROM quote")  # rowid ensures stable sorting for same-timestamp records
        logger.info("Shape of quote: %s x %s", self.quote.shape[0], self.quote.shape[1])

        t_load_elapsed = time.perf_counter_ns() - t_load_start
        io_load_end = ios.get_io_stat()
        writer.writerow(row_start + [-1, "load", "transform", "success", t_load_elapsed, None, None,
                         None, io_load_end - io_load_start, None, None])


        io_load_start = ios.get_io_stat()
        t_load_start = time.perf_counter_ns()
        logger.info("ordering by time and row number")
        self.trade = duckdb.sql("SELECT * EXCLUDE (rn) FROM trade ORDER BY time, rn")
        logger.info("ordering by time and row number")
        self.quote = duckdb.sql("SELECT * EXCLUDE (rn) FROM quote ORDER BY time, rn")
        t_load_elapsed = time.perf_counter_ns() - t_load_start
        io_load_end = ios.get_io_stat()
        writer.writerow(row_start + [-2, "load", "sort by time", "success", t_load_elapsed, None, None,
                         None, io_load_end - io_load_start, None, None])


    def execute_query(self, idx: int, tags: Set, query_str: str, parameter: str, runidx: int):
        eval_context = {
            "duckdb": duckdb,
            "timedelta": timedelta,
            "master": self.master,
            "trade": self.trade,
            "quote": self.quote,
            **self.params
        }
        return eval(f"duckdb.sql(\"{query_str}\", params=[{parameter}])", eval_context)

    def write_csv(self, res, outFile: Path) -> None:
        tscols = [row[0] for row in duckdb.sql("SELECT column_name FROM (DESCRIBE res) WHERE column_type = 'TIMESTAMP_NS'").fetchall()]
        for col in tscols:
            res=duckdb.sql(f"SELECT * REPLACE (format('0D{{:02d}}:{{:02d}}:{{:02d}}.{{:09d}}', hour({col}), minute({col}), second({col}), (epoch_ns({col}) % 1000000000)) AS {col}) FROM res")

        bcols = [row[0] for row in duckdb.sql("SELECT column_name FROM (DESCRIBE res) WHERE column_type = 'BOOLEAN'").fetchall()]
        for col in bcols:
            res=duckdb.sql(f"SELECT * REPLACE ({col}::INTEGER AS {col}) FROM res")
        res.write_csv(str(outFile))
