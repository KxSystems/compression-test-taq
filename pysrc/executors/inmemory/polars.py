import polars as pl

import logging
from datetime import timedelta, datetime
from pathlib import Path
from typing import Any, Dict, Optional, Set

import time

logger = logging.getLogger(__name__)



class QueryExecutorPolarsInMemory:
    """
    Handles the setup, execution of Polars in-memory queries
    (single partition loaded into memory).
    """

    def __init__(self, param: Dict[str, Any], datadate: datetime.date) -> None:
        self.datadate: Optional[Any] = datadate
        self.master: Optional[pl.DataFrame] = None
        self.trade: Optional[pl.DataFrame] = None
        self.quote: Optional[pl.DataFrame] = None
        self.params: Dict[str, Any] = param
        self.params['timeBuckets'] = pl.DataFrame(list(self.params['timeBuckets'].items()), schema=['bucket', 'bound'])
        self.params['timeBuckets'] = self.params['timeBuckets'].with_columns(pl.col('bound').cast(pl.Duration('ns')))

    def load_resources(self, db_path: Path, datadate: datetime.date, writer, row_start, ios) -> None:
        logger.info("loading hive-partitioned tables at %s", db_path)

        io_load_start = ios.get_io_stat()
        t_load_start = time.perf_counter_ns()
        exnames = pl.scan_parquet(db_path / "exnames.parquet").collect()
        self.params["exnames"] = dict(zip(exnames["ex"], exnames["name"]))
        master = pl.scan_parquet(db_path / "master/date=*/*.parquet", hive_partitioning=True)
        self.master = master.filter(pl.col("date") == datadate).drop("date").collect()
        logger.info("loading trade")
        self.trade = pl.scan_parquet(db_path / "trade/date=*/*.parquet",
            hive_partitioning=True).filter(pl.col("date") == datadate).drop("date").collect()
        logger.info("loading quote")
        self.quote = pl.scan_parquet(db_path / "quote/date=*/*.parquet",
            hive_partitioning=True).filter(pl.col("date") == datadate).drop("date").collect()
        t_load_elapsed = time.perf_counter_ns() - t_load_start
        io_load_end = ios.get_io_stat()
        writer.writerow(row_start + [0, "load", "load a partition into memory", "success", t_load_elapsed, None, None,
                         None, io_load_end - io_load_start, None, None])


        io_load_start = ios.get_io_stat()
        t_load_start = time.perf_counter_ns()
        self.master = self.master.with_columns(pl.col("sym").cast(pl.Categorical))
        logger.info("Shape of master: %s x %s", self.master.shape[0], self.master.shape[1])
        self.trade = self.trade.with_columns(pl.col("sym").cast(pl.Categorical))
        logger.info("Shape of trade: %s x %s", self.trade.shape[0], self.trade.shape[1])
        self.quote = self.quote.with_columns(pl.col("sym").cast(pl.Categorical))
        logger.info("Shape of quote: %s x %s", self.quote.shape[0], self.quote.shape[1])
        t_load_elapsed = time.perf_counter_ns() - t_load_start
        io_load_end = ios.get_io_stat()
        writer.writerow(row_start + [-1, "load", "transform", "success", t_load_elapsed, None, None,
                         None, io_load_end - io_load_start, None, None])


        io_load_start = ios.get_io_stat()
        t_load_start = time.perf_counter_ns()
        self.trade = self.trade.sort("time")
        self.quote = self.quote.sort("time")
        t_load_elapsed = time.perf_counter_ns() - t_load_start
        io_load_end = ios.get_io_stat()
        writer.writerow(row_start + [-2, "load", "sort by time", "success", t_load_elapsed, None, None,
                         None, io_load_end - io_load_start, None, None])

    def getTableStats(self) -> Dict[str, Any]:
        table_stats_dict = {}
        for tNames in ["master", "trade", "quote"]:
            df = getattr(self, tNames)
            table_stats = {
                "name": tNames,
                "size (MB)": int(df.estimated_size("mb")),
                "rowCount": df.shape[0],
                "columnCount": df.shape[1],
                "columns": [
                    {"name": col, "type": str(df.schema[col])}
                    for col in df.columns
                ],
            }
            table_stats_dict[tNames] = table_stats
        return table_stats_dict



    def execute_query(self, idx: int, tags: Set, query_str: str, parameter: str, runidx: int):
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

    @staticmethod
    def _fmt_minute(col: str) -> pl.Expr:
        ns = pl.col(col).dt.total_nanoseconds()
        hh = ((ns // 3_600_000_000_000) % 24).cast(pl.String).str.zfill(2)
        mm = ((ns // 60_000_000_000) % 60).cast(pl.String).str.zfill(2)
        return pl.concat_str([hh, pl.lit(":"), mm]).alias(col)

    @staticmethod
    def _fmt_duration(col: str) -> pl.Expr:
        ns = pl.col(col).dt.total_nanoseconds()
        days = (ns // 86_400_000_000_000).cast(pl.String)
        hh = ((ns // 3_600_000_000_000) % 24).cast(pl.String).str.zfill(2)
        mm = ((ns // 60_000_000_000) % 60).cast(pl.String).str.zfill(2)
        ss = ((ns // 1_000_000_000) % 60).cast(pl.String).str.zfill(2)
        subsec = (ns % 1_000_000_000).cast(pl.String).str.zfill(9)
        return pl.concat_str([
            days, pl.lit("D"),
            hh, pl.lit(":"),
            mm, pl.lit(":"),
            ss, pl.lit("."),
            subsec,
        ]).alias(col)

    def write_csv(self, res, outFile: Path) -> None:
        duration_cols = [
            c for c in res.columns
            if res.schema[c] == pl.Duration and c != "minute"
        ]
        has_minute = "minute" in res.columns and res.schema["minute"] == pl.Duration

        exprs = [pl.col(pl.Boolean).cast(pl.Int8).cast(pl.String)]
        if has_minute:
            exprs.append(self._fmt_minute("minute"))
        exprs.extend(self._fmt_duration(c) for c in duration_cols)

        res = res.with_columns(exprs)
        res.write_csv(outFile)

