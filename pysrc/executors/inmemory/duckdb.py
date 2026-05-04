import duckdb
import pandas as pd

import logging
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Set

logger = logging.getLogger(__name__)


class QueryExecutorDuckDBInMemory:
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
        self.trade = duckdb.sql("SELECT * EXCLUDE (rn) FROM (SELECT make_timestamp_ns(epoch_ns(date)+time) AS time, row_number() OVER () AS rn, * EXCLUDE (date, time) FROM trade WHERE date = $1 ORDER BY time, rn)", params=[self.datadate])  # rowid ensures stable sorting for same-timestamp records
        logger.info("Shape of trade: %s x %s", self.trade.shape[0], self.trade.shape[1])

        logger.info("loading quote")
        quote = duckdb.read_parquet(str(db_path / "quote/date=*/*.parquet"), hive_partitioning=True)
        self.quote = duckdb.sql("SELECT * EXCLUDE (rn) FROM (SELECT make_timestamp_ns(epoch_ns(date)+time) AS time, row_number() OVER () AS rn, * EXCLUDE (date, time) FROM quote WHERE date = $1 ORDER BY time, rn)", params=[self.datadate])  # rowid ensures stable sorting for same-timestamp records
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
        res.write_csv(str(outFile))
