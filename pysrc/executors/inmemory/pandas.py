import numpy as np
import pandas as pd

import logging
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Set

logger = logging.getLogger(__name__)


class QueryExecutorPandas:
    """
    Handles the setup, execution of Pandas queries
    on NYSE TAQ hive-partitioned parquet files.
    """

    def __init__(self, param: Dict[str, Any]) -> None:
        self.master: Optional[pd.DataFrame] = None
        self.trade: Optional[pd.DataFrame] = None
        self.quote: Optional[pd.DataFrame] = None
        self.params: Dict[str, Any] = param

    def load_resources(self, db_path: Path) -> None:
        import pyarrow.dataset as ds
        logger.info("loading hive-partitioned tables at %s", db_path)

        master_ds = ds.dataset(db_path / "master", format="parquet", partitioning="hive")
        datadate = master_ds.head(1).column("date")[0].as_py()
        master = master_ds.to_table(filter=(ds.field("date") == datadate)).drop("date")
        master = master.set_column(master.schema.get_field_index("sym"), "sym", master.column("sym").dictionary_encode())
        self.master = master.to_pandas()
        logger.info("Shape of master: %s x %s", self.master.shape[0], self.master.shape[1])
        self.master['ex'] = pd.Categorical(self.master['ex'], categories=sorted(self.master['ex'].unique()), ordered=True)
        exnames = pd.read_parquet(db_path / "exnames.parquet")
        self.params["exnames"] = dict(zip(exnames["ex"], exnames["name"]))

        logger.info("loading trade as a pyarrow dataset")
        trade_ds = ds.dataset(db_path / "trade", format="parquet", partitioning="hive")
        trade = trade_ds.to_table(filter=(ds.field("date") == datadate)).drop("date")
        trade = trade.set_column(trade.schema.get_field_index("sym"), "sym", trade.column("sym").dictionary_encode())
        logger.info("converting to pandas")
        self.trade = trade.to_pandas().sort_values(by="time", kind='stable')
        self.trade['ex'] = pd.Categorical(self.trade['ex'], categories=sorted(self.trade['ex'].unique()), ordered=True)
        logger.info("Shape of trade: %s x %s", self.trade.shape[0], self.trade.shape[1])

        logger.info("loading quote as a pyarrow dataset")
        quote_ds = ds.dataset(db_path / "quote", format="parquet", partitioning="hive")
        quote = quote_ds.to_table(filter=(ds.field("date") == datadate)).drop("date")
        quote = quote.set_column(quote.schema.get_field_index("sym"), "sym", quote.column("sym").dictionary_encode())
        logger.info("converting to pandas")
        self.quote = quote.to_pandas().sort_values(by="time", kind='stable')
        self.quote['ex'] = pd.Categorical(self.quote['ex'], categories=sorted(self.quote['ex'].unique()), ordered=True)
        logger.info("Shape of quote: %s x %s", self.quote.shape[0], self.quote.shape[1])

    def execute_query(self, idx: int, tags: Set, query_str: str, parameter: str, runidx: int):
        eval_context = {
            "pd": pd,
            "np": np,
            "timedelta": timedelta,
            "master": self.master,
            "trade": self.trade,
            "quote": self.quote,
            **self.params
        }
        return eval(query_str, eval_context)

    def write_csv(self, res, outFile: Path) -> None:
        if isinstance(res.index, pd.MultiIndex):
            res.reset_index(inplace=True)
        for col in res.select_dtypes(include=['timedelta64']).columns:
            if col == 'minute':
                res = res.assign(**{col: res[col].apply(lambda td: "" if pd.isnull(td) else f"{td.seconds//3600:02}:{(td.seconds%3600)//60:02}")})
            else:
                res = res.assign(**{col: res[col].apply(lambda td: "" if pd.isnull(td) else f"{td.days}D{td.seconds//3600:02}:{(td.seconds%3600)//60:02}:{td.seconds%60:02}.{td.microseconds:06}{td.nanoseconds:03}")})
        for col in res.select_dtypes(include=['bool']).columns:
            res = res.assign(**{col: np.where(res[col], '1', '0')})  # Convert boolean to '1'/'0' strings for kdb+ compatibility
        res.to_csv(outFile, index=False)
