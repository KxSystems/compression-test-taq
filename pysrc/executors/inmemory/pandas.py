import numpy as np
import pandas as pd

import pyarrow.dataset as ds

import logging
from datetime import timedelta, datetime
from pathlib import Path
from typing import Any, Dict, Optional, Set
import time

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

    def load_resources(self, db_path: Path, datadate: datetime.date, writer, row_start, ios) -> None:
        logger.info("loading hive-partitioned tables at %s", db_path)
        d= datadate.strftime('%Y-%m-%d')

        io_load_start = ios.get_io_stat()
        t_load_start = time.perf_counter_ns()
        logger.info("loading root objects into memory")
        exnames = pd.read_parquet(db_path / "exnames.parquet")
        logger.info("loading master")
        master_ds = ds.dataset(db_path / "master", format="parquet", partitioning="hive")
        master = master_ds.to_table(filter=(ds.field("date") == d))
        del master_ds
        master = master.drop("date").set_column(master.schema.get_field_index("sym"), "sym", master.column("sym").dictionary_encode())
        self.master = master.to_pandas()
        del master

        logger.info("loading trade")
        trade_ds = ds.dataset(db_path / "trade", format="parquet", partitioning="hive")
        trade = trade_ds.to_table(filter=(ds.field("date") == d))
        del trade_ds
        trade = trade.drop("date").set_column(trade.schema.get_field_index("sym"), "sym", trade.column("sym").dictionary_encode())
        logger.info("converting to pandas")
        self.trade = trade.to_pandas()
        del trade

        logger.info("loading quote")
        quote_ds = ds.dataset(db_path / "quote", format="parquet", partitioning="hive")
        quote = quote_ds.to_table(filter=(ds.field("date") == d))
        del quote_ds
        quote = quote.drop("date").set_column(quote.schema.get_field_index("sym"), "sym", quote.column("sym").dictionary_encode())
        logger.info("converting to pandas")
        self.quote = quote.to_pandas()
        del quote
        t_load_elapsed = time.perf_counter_ns() - t_load_start
        io_load_end = ios.get_io_stat()
        writer.writerow(row_start + [0, "load", "load a partition into memory", "success", t_load_elapsed, None, None,
                         None, io_load_end - io_load_start, None, None])


        io_load_start = ios.get_io_stat()
        t_load_start = time.perf_counter_ns()
        logger.info("Shape of master: %s x %s", self.master.shape[0], self.master.shape[1])
        self.master['ex'] = pd.Categorical(self.master['ex'], categories=sorted(self.master['ex'].unique()), ordered=True)
        self.params["exnames"] = dict(zip(exnames["ex"], exnames["name"]))
        self.trade['ex'] = pd.Categorical(self.trade['ex'], categories=sorted(self.trade['ex'].unique()), ordered=True)
        self.quote['ex'] = pd.Categorical(self.quote['ex'], categories=sorted(self.quote['ex'].unique()), ordered=True)
        t_load_elapsed = time.perf_counter_ns() - t_load_start
        io_load_end = ios.get_io_stat()
        writer.writerow(row_start + [-1, "load", "transform", "success", t_load_elapsed, None, None,
                         None, io_load_end - io_load_start, None, None])
        logger.info("Shape of trade: %s x %s", self.trade.shape[0], self.trade.shape[1])
        logger.info("Shape of quote: %s x %s", self.quote.shape[0], self.quote.shape[1])


        io_load_start = ios.get_io_stat()
        t_load_start = time.perf_counter_ns()
        self.trade = self.trade.sort_values(by="time", kind='stable')
        self.quote = self.quote.sort_values(by="time", kind='stable')
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
                "rowCount": df.shape[0],
                "columnCount": df.shape[1],
                "columns": [
                    {"name": col, "type": str(df[col].dtype)}
                    for col in df.columns
                ],
            }
            table_stats_dict[tNames] = table_stats
        return table_stats_dict


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
