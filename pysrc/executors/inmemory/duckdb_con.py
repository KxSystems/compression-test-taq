import duckdb
import pandas as pd

import logging
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Set

logger = logging.getLogger(__name__)


class QueryExecutorDuckDBCon:
    """
    Handles the setup, execution of DuckDB in-memory queries.
    """

    def __init__(self, con, param: Dict[str, Any]) -> None:
        self.con: duckdb.DuckDBPyConnection = con
        self.params: Dict[str, Any] = param
        self.params['timeBuckets'] = pd.DataFrame(list(self.params['timeBuckets'].items()), columns=['bucket', 'bound'])

    def load_resources(self, db_path: Path) -> None:
        logger.info("loading first partition of hive-partitioned tables at %s into memory", db_path)
        self.con.execute("CREATE TABLE master AS SELECT * FROM read_parquet($1, hive_partitioning=True)", parameters=[str(db_path / "master/date=*/*.parquet")])
        datadate = self.con.execute("SELECT DISTINCT date FROM master").fetchone()[0]    # first date only
        self.con.execute("SELECT * EXCLUDE (date) FROM master WHERE date=$1", parameters=[datadate])
        master=self.con.table("master")
        logger.info("Shape of master: %s x %s", master.shape[0], master.shape[1])

        self.con.execute("CREATE TABLE exnames AS SELECT * FROM read_parquet($1)", parameters=[str(db_path / "exnames.parquet")])

        logger.info("loading trade")
        self.con.execute("CREATE TABLE trade AS SELECT * FROM read_parquet($1, hive_partitioning=True) where date = $2", parameters=[str(db_path / "trade/date=*/*.parquet"), datadate])
        logger.info("applying transformations")
        self.con.execute("CREATE OR REPLACE TABLE trade AS SELECT make_timestamp_ns(epoch_ns(date)+time) AS time, " +
            "make_timestamp_ns(epoch_ns(date)+participantTimestamp) AS participantTimestamp, " +
            "make_timestamp_ns(epoch_ns(date)+tradeReportingFacilityTRFTimestamp) AS tradeReportingFacilityTRFTimestamp, " +
            "row_number() OVER () AS rn, * EXCLUDE (date, time, participantTimestamp, tradeReportingFacilityTRFTimestamp) FROM trade")  # rowid ensures stable sorting for same-timestamp records
        logger.info("ordering by time and row number")
        self.con.execute("CREATE OR REPLACE TABLE trade AS SELECT * EXCLUDE (rn) FROM trade ORDER BY time, rn")
        trade=self.con.table("trade")
        logger.info("Shape of trade: %s x %s", trade.shape[0], trade.shape[1])

        logger.info("loading quote")
        self.con.execute("CREATE TABLE quote AS SELECT * FROM read_parquet($1, hive_partitioning=True) where date = $2", parameters=[str(db_path / "quote/date=*/*.parquet"), datadate])
        logger.info("applying transformations")
        self.con.execute("CREATE OR REPLACE TABLE quote AS SELECT make_timestamp_ns(epoch_ns(date)+time) AS time, " +
            "make_timestamp_ns(epoch_ns(date)+participantTimestamp) AS participantTimestamp, " +
            "make_timestamp_ns(epoch_ns(date)+FINRAADFTimestamp) AS FINRAADFTimestamp, " +
            "row_number() OVER () AS rn, * EXCLUDE (date, time, participantTimestamp, FINRAADFTimestamp) FROM quote WHERE date = $1", parameters=[datadate])  # rowid ensures stable sorting for same-timestamp records
        logger.info("ordering by time and row number")
        self.con.execute("CREATE OR REPLACE TABLE quote AS SELECT * EXCLUDE (rn) FROM quote ORDER BY time, rn")
        quote=self.con.table("quote")
        logger.info("Shape of quote: %s x %s", quote.shape[0], quote.shape[1])

    def execute_query(self, idx: int, tags: Set, query_str: str, parameter: str, runidx: int):
        eval_context = {
            "duckdb": duckdb,
            "timedelta": timedelta,
            "con": self.con,
#            "master": self.master,
#            "trade": self.trade,
#            "quote": self.quote,
            **self.params
        }
        eval(f"con.sql(\"CREATE OR REPLACE TABLE res AS {query_str}\", params=[{parameter}])", eval_context)
        return self.con.table('res')

    def write_csv(self, res, outFile: Path) -> None:
        tscols = [row[0] for row in self.con.sql("SELECT column_name FROM (DESCRIBE res) WHERE column_type = 'TIMESTAMP_NS'").fetchall()]
        for col in tscols:
            self.con.sql(f"CREATE OR REPLACE TABLE res AS SELECT * REPLACE (format('0D{{:02d}}:{{:02d}}:{{:02d}}.{{:09d}}', hour({col}), minute({col}), second({col}), (epoch_ns({col}) % 1000000000)) AS {col}) FROM res")

        bcols = [row[0] for row in self.con.sql("SELECT column_name FROM (DESCRIBE res) WHERE column_type = 'BOOLEAN'").fetchall()]
        for col in bcols:
            self.con.sql(f"CREATE OR REPLACE TABLE res AS SELECT * REPLACE ({col}::INTEGER AS {col}) FROM res")
        self.con.table('res').write_csv(str(outFile))
