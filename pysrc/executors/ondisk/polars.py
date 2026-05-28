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


class QueryExecutorPolars:
    """
    Handles the setup, execution of Polars queries
    on NYSE TAQ hive-partitioned parquet files.
    """

    def __init__(self, param: Dict[str, Any]) -> None:
        self.master: Optional[pl.LazyFrame] = None
        self.trade: Optional[pl.LazyFrame] = None
        self.quote: Optional[pl.LazyFrame] = None
        _build_time_bucket_exprs(param)
        self.params: Dict[str, Any] = param

    def load_resources(self, db_path: Path) -> None:
        logger.info("loading hive-partitioned tables at %s", db_path)
        self.master = pl.scan_parquet(db_path / "master/date=*/*.parquet", hive_partitioning=True)
        exnames = pl.scan_parquet(db_path / "exnames.parquet").collect()
        self.params["exnames"] = dict(zip(exnames["ex"], exnames["name"]))
        self.trade = pl.scan_parquet(db_path / "trade/date=*/*.parquet", hive_partitioning=True)
        self.quote = pl.scan_parquet(db_path / "quote/date=*/*.parquet", hive_partitioning=True)

    def prepare_run(self) -> None:
        pass

    def execute_query(self, idx: int, tags: Set, query_str: str, parameter: str, runidx: int):
        eval_context = {
            "pl": pl,
            "timedelta": timedelta,
            "master": self.master,
            "trade": self.trade,
            "quote": self.quote,
            **self.params
        }
        return eval(query_str, eval_context) if "dataframeresult" in tags else eval(query_str, eval_context).collect()

    def write_csv(self, res, outFile: Path) -> None:
        res.with_columns(pl.col(pl.Boolean).cast(pl.Int8)).fill_nan(None).write_csv(outFile, float_precision=6)
