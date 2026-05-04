import polars as pl

import logging
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Set

logger = logging.getLogger(__name__)


def _build_time_bucket_exprs(param: Dict[str, Any]) -> None:
    """Adds time_bucket_expr and time_bucket_idx_expr to param in-place."""
    time_bucket_expr = pl.lit(None)
    for bucket, bound in param['timeBuckets'].items():
        time_bucket_expr = pl.when(pl.col("time") >= bound).then(
            pl.lit(bucket)).otherwise(time_bucket_expr)
    param['time_bucket_expr'] = time_bucket_expr

    time_bucket_idx_expr = pl.lit(None)
    for index, bound in enumerate(param['timeBuckets'].values()):
        time_bucket_idx_expr = pl.when(pl.col("time") >= bound).then(
            pl.lit(index)).otherwise(time_bucket_idx_expr)
    param['time_bucket_idx_expr'] = time_bucket_idx_expr


class QueryExecutorPolarsInMemory:
    """
    Handles the setup, execution of Polars in-memory queries
    (single partition loaded into memory).
    """

    def __init__(self, param: Dict[str, Any]) -> None:
        self.datadate: Optional[Any] = None
        self.master: Optional[pl.DataFrame] = None
        self.trade: Optional[pl.DataFrame] = None
        self.quote: Optional[pl.DataFrame] = None
        _build_time_bucket_exprs(param)
        self.params: Dict[str, Any] = param

    def load_resources(self, db_path: Path) -> None:
        logger.info("loading first partition of hive-partitioned tables at %s into memory", db_path)
        master = pl.scan_parquet(db_path / "master/date=*/*.parquet", hive_partitioning=True)
        self.datadate = master.select(pl.first("date")).collect().item()
        self.master = master.filter(pl.col("date") == self.datadate).drop("date").with_columns(pl.col("sym").cast(pl.Categorical)).collect()
        logger.info("Shape of master: %s x %s", self.master.shape[0], self.master.shape[1])

        exnames = pl.scan_parquet(db_path / "exnames.parquet").collect()
        self.params["exnames"] = dict(zip(exnames["ex"], exnames["name"]))

        logger.info("loading trade")
        self.trade = pl.scan_parquet(db_path / "trade/date=*/*.parquet",
            hive_partitioning=True).filter(pl.col("date") == self.datadate).drop("date").with_columns(pl.col("sym").cast(pl.Categorical)).sort("time").collect()
        logger.info("Shape of trade: %s x %s", self.trade.shape[0], self.trade.shape[1])
        logger.info("loading quote")
        self.quote = pl.scan_parquet(db_path / "quote/date=*/*.parquet",
            hive_partitioning=True).filter(pl.col("date") == self.datadate).drop("date").with_columns(pl.col("sym").cast(pl.Categorical)).sort("time").collect()
        logger.info("Shape of quote: %s x %s", self.quote.shape[0], self.quote.shape[1])

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

    def write_csv(self, res, outFile: Path) -> None:
        res.write_csv(outFile)
