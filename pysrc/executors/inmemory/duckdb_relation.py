import duckdb
import pandas as pd

import logging
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Set

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

    def load_resources(self, db_path: Path) -> None:
        logger.info("loading first partition of hive-partitioned tables at %s into memory", db_path)
        master = duckdb.read_parquet(str(db_path / "master/date=*/*.parquet"), hive_partitioning=True)
        self.datadate = master['date'].fetchone()[0]
        self.master = duckdb.sql("SELECT * EXCLUDE (date) FROM master WHERE date=$1", params=[self.datadate])
        logger.info("Shape of master: %s x %s", self.master.shape[0], self.master.shape[1])

        self.params["exnames"] = pd.read_parquet(db_path / "exnames.parquet")

        logger.info("loading trade")
        trade = duckdb.read_parquet(str(db_path / "trade/date=*/*.parquet"), hive_partitioning=True)
        logger.info("applying transformations")
        trade = duckdb.sql("SELECT make_timestamp_ns(epoch_ns(date)+time) AS time, " +
            "make_timestamp_ns(epoch_ns(date)+participantTimestamp) AS participantTimestamp, " +
            "make_timestamp_ns(epoch_ns(date)+tradeReportingFacilityTRFTimestamp) AS tradeReportingFacilityTRFTimestamp, " +
            "row_number() OVER () AS rn, * EXCLUDE (date, time, participantTimestamp, tradeReportingFacilityTRFTimestamp) FROM trade WHERE date = $1", params=[self.datadate])  # rowid ensures stable sorting for same-timestamp records
        logger.info("ordering by time and row number")
        self.trade = duckdb.sql("SELECT * EXCLUDE (rn) FROM trade ORDER BY time, rn")
        logger.info("Shape of trade: %s x %s", self.trade.shape[0], self.trade.shape[1])

        logger.info("loading quote")
        quote = duckdb.read_parquet(str(db_path / "quote/date=*/*.parquet"), hive_partitioning=True)
        logger.info("applying transformations")
        quote = duckdb.sql("SELECT make_timestamp_ns(epoch_ns(date)+time) AS time, " +
            "make_timestamp_ns(epoch_ns(date)+participantTimestamp) AS participantTimestamp, " +
            "make_timestamp_ns(epoch_ns(date)+FINRAADFTimestamp) AS FINRAADFTimestamp, " +
            "row_number() OVER () AS rn, * EXCLUDE (date, time, participantTimestamp, FINRAADFTimestamp) FROM quote WHERE date = $1", params=[self.datadate])  # rowid ensures stable sorting for same-timestamp records
        logger.info("ordering by time and row number")
        self.quote = duckdb.sql("SELECT * EXCLUDE (rn) FROM quote ORDER BY time, rn")
        logger.info("Shape of quote: %s x %s", self.quote.shape[0], self.quote.shape[1])

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
