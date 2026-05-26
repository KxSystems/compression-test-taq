import duckdb
import pandas as pd

import logging
from datetime import timedelta, datetime
from pathlib import Path
from typing import Any, Dict, Optional, Set
import time

logger = logging.getLogger(__name__)


class QueryExecutorDuckDBCon:
    """
    Handles the setup, execution of DuckDB in-memory queries.
    """

    def __init__(self, con, param: Dict[str, Any], indexOnsym: bool=False) -> None:
        self.con: duckdb.DuckDBPyConnection = con
        self.params: Dict[str, Any] = param
        self.params['timeBuckets'] = pd.DataFrame(list(self.params['timeBuckets'].items()), columns=['bucket', 'bound'])
        self.indexOnsym: bool = indexOnsym

    def load_resources(self, db_path: Path, datadate: datetime.date, writer, row_start, ios) -> None:
        logger.info("loading hive-partitioned tables at %s", db_path)

        io_load_start = ios.get_io_stat()
        t_load_start = time.perf_counter_ns()
        self.con.execute("CREATE TABLE exnames AS SELECT * FROM read_parquet($1)", parameters=[str(db_path / "exnames.parquet")])

        self.con.execute("CREATE TABLE master AS SELECT * FROM read_parquet($1, hive_partitioning=True) WHERE date = $2", parameters=[str(db_path / "master/date=*/*.parquet"), datadate])
        self.con.execute("SELECT * EXCLUDE (date) FROM master WHERE date=$1", parameters=[datadate])

        logger.info("loading trade")
        self.con.execute("CREATE TABLE trade AS SELECT * FROM read_parquet($1, hive_partitioning=True) where date = $2", parameters=[str(db_path / "trade/date=*/*.parquet"), datadate])

        logger.info("loading quote")
        self.con.execute("CREATE TABLE quote AS SELECT * FROM read_parquet($1, hive_partitioning=True) where date = $2", parameters=[str(db_path / "quote/date=*/*.parquet"), datadate])
        t_load_elapsed = time.perf_counter_ns() - t_load_start
        io_load_end = ios.get_io_stat()
        writer.writerow(row_start + [0, "load", "load a partition into memory", "success", t_load_elapsed, None, None,
                         None, io_load_end - io_load_start, None, None])


        io_load_start = ios.get_io_stat()
        t_load_start = time.perf_counter_ns()
        logger.info("applying transformations")
        self.con.execute("CREATE TYPE sym_master_enum AS ENUM (SELECT DISTINCT sym FROM master)")
        self.con.execute("ALTER TABLE master ALTER sym TYPE sym_master_enum")
        master=self.con.table("master")
        logger.info("Shape of master: %s x %s", master.shape[0], master.shape[1])

        logger.info("applying transformations")
        self.con.execute("CREATE OR REPLACE TABLE trade AS SELECT make_timestamp_ns(epoch_ns(date)+time) AS time, " +
            "make_timestamp_ns(epoch_ns(date)+participantTimestamp) AS participantTimestamp, " +
            "make_timestamp_ns(epoch_ns(date)+tradeReportingFacilityTRFTimestamp) AS tradeReportingFacilityTRFTimestamp, " +
            "row_number() OVER () AS rn, * EXCLUDE (date, time, participantTimestamp, tradeReportingFacilityTRFTimestamp) FROM trade")  # rowid ensures stable sorting for same-timestamp records
        self.con.execute("CREATE TYPE sym_trade_enum AS ENUM (SELECT DISTINCT sym FROM trade)") # master might not contain all syms in trade
        self.con.execute("ALTER TABLE trade ALTER sym TYPE sym_trade_enum")
        trade=self.con.table("trade")
        logger.info("Shape of trade: %s x %s", trade.shape[0], trade.shape[1])


        logger.info("applying transformations")
        self.con.execute("CREATE OR REPLACE TABLE quote AS SELECT make_timestamp_ns(epoch_ns(date)+time) AS time, " +
            "make_timestamp_ns(epoch_ns(date)+participantTimestamp) AS participantTimestamp, " +
            "make_timestamp_ns(epoch_ns(date)+FINRAADFTimestamp) AS FINRAADFTimestamp, " +
            "row_number() OVER () AS rn, * EXCLUDE (date, time, participantTimestamp, FINRAADFTimestamp) FROM quote WHERE date = $1", parameters=[datadate])  # rowid ensures stable sorting for same-timestamp records
        logger.info("applying transformations")
        self.con.execute("CREATE TYPE sym_quote_enum AS ENUM (SELECT DISTINCT sym FROM quote)")
        self.con.execute("ALTER TABLE quote ALTER sym TYPE sym_quote_enum")
        quote=self.con.table("quote")
        logger.info("Shape of quote: %s x %s", quote.shape[0], quote.shape[1])
        t_load_elapsed = time.perf_counter_ns() - t_load_start
        io_load_end = ios.get_io_stat()
        writer.writerow(row_start + [-1, "load", "transform", "success", t_load_elapsed, None, None,
                         None, io_load_end - io_load_start, None, None])


        io_load_start = ios.get_io_stat()
        t_load_start = time.perf_counter_ns()
        logger.info("ordering trade by time and row number")
        self.con.execute("CREATE OR REPLACE TABLE trade AS SELECT * EXCLUDE (rn) FROM trade ORDER BY time, rn")
        logger.info("ordering quote by time and row number")
        self.con.execute("CREATE OR REPLACE TABLE quote AS SELECT * EXCLUDE (rn) FROM quote ORDER BY time, rn")

        t_load_elapsed = time.perf_counter_ns() - t_load_start
        io_load_end = ios.get_io_stat()
        writer.writerow(row_start + [-2, "load", "sort by time", "success", t_load_elapsed, None, None,
                         None, io_load_end - io_load_start, None, None])

        if self.indexOnsym:
            io_load_start = ios.get_io_stat()
            t_load_start = time.perf_counter_ns()
            logger.info("adding index on sym")
            self.con.execute("CREATE INDEX IF NOT EXISTS idx_trade_sym ON trade (sym)")
            logger.info("adding index on sym")
            self.con.execute("CREATE INDEX IF NOT EXISTS idx_quote_sym ON quote (sym)")

            t_load_elapsed = time.perf_counter_ns() - t_load_start
            io_load_end = ios.get_io_stat()
            writer.writerow(row_start + [-3, "load", "index", "success", t_load_elapsed, None, None,
                             None, io_load_end - io_load_start, None, None])

    def getTableStats(self) -> Dict[str, Any]:
        table_stats_dict = {}
        for tNames in ["master", "trade", "quote"]:
            df = self.con.table(tNames)
            table_stats = {
                "name": tNames,
                "size (MB)": None,
                "rowCount": df.shape[0],
                "columnCount": df.shape[1],
                "columns": [
                    {"name": col, "type": str(dtype)}
                    for col, dtype in zip(df.columns, df.dtypes)
                    ],
            }
            table_stats_dict[tNames] = table_stats
        return table_stats_dict


    def execute_query(self, idx: int, tags: Set, query_str: str, parameter: str, runidx: int):
        eval_context = {
            "duckdb": duckdb,
            "timedelta": timedelta,
            "con": self.con,
            **self.params
        }
        try:
            eval(f"con.sql(\"CREATE OR REPLACE TABLE res AS {query_str}\", params=[{parameter}])", eval_context)
        except Exception:
            self.con.rollback()
            raise
        return self.con.table('res')

    def write_csv(self, res, outFile: Path) -> None:
        tscols = [row[0] for row in self.con.sql("SELECT column_name FROM (DESCRIBE res) WHERE column_type = 'TIMESTAMP_NS'").fetchall()]
        for col in tscols:
            self.con.sql(f"CREATE OR REPLACE TABLE res AS SELECT * REPLACE (format('0D{{:02d}}:{{:02d}}:{{:02d}}.{{:09d}}', hour({col}), minute({col}), second({col}), (epoch_ns({col}) % 1000000000)) AS {col}) FROM res")

        bcols = [row[0] for row in self.con.sql("SELECT column_name FROM (DESCRIBE res) WHERE column_type = 'BOOLEAN'").fetchall()]
        for col in bcols:
            self.con.sql(f"CREATE OR REPLACE TABLE res AS SELECT * REPLACE ({col}::INTEGER AS {col}) FROM res")
        self.con.table('res').write_csv(str(outFile))
