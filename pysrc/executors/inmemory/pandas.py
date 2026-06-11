import numpy as np
import pandas as pd

import pyarrow.dataset as ds

import logging
from datetime import timedelta, datetime
from pathlib import Path
from typing import Any, Dict, Set
import time

logger = logging.getLogger(__name__)


class QueryExecutorPandas:
    """
    Handles the setup, execution of Pandas queries
    on NYSE TAQ hive-partitioned parquet files.
    """

    def __init__(self, param: Dict[str, Any]) -> None:
        self.params: Dict[str, Any] = param
        self.eval_context: Dict[str, Any] = {
            "pd": pd,
            "np": np,
            "timedelta": timedelta,
            **param,
        }

    def load_resources(self, db_path: Path, datadate: datetime.date, writer, row_start, ios) -> None:
        logger.info("loading hive-partitioned tables at %s", db_path)
        d= datadate.strftime('%Y-%m-%d')

        io_load_start = ios.get_io_stat()
        t_load_start = time.perf_counter_ns()
        logger.info("loading root objects into memory")
        exnames = pd.read_parquet(db_path / "exnames.parquet")
        logger.info("loading master")
        master = ds.dataset(db_path / "master" / f"date={d}", format="parquet").to_table()
        master = master.set_column(master.schema.get_field_index("sym"), "sym", master.column("sym").dictionary_encode()).to_pandas()

        logger.info("loading trade")
        trade = ds.dataset(db_path / "trade" / f"date={d}", format="parquet").to_table()
        trade = trade.set_column(trade.schema.get_field_index("sym"), "sym", trade.column("sym").dictionary_encode()).to_pandas()

        logger.info("loading quote")
        quote = ds.dataset(db_path / "quote" / f"date={d}", format="parquet").to_table()
        quote = quote.set_column(quote.schema.get_field_index("sym"), "sym", quote.column("sym").dictionary_encode()).to_pandas()
        t_load_elapsed = time.perf_counter_ns() - t_load_start
        io_load_end = ios.get_io_stat()
        writer.writerow(row_start + [0, "load", "load a partition into memory", "success", t_load_elapsed, None, None,
                         None, io_load_end - io_load_start, None, None, self.getTableSize(master) + self.getTableSize(trade) + self.getTableSize(quote)])


        io_load_start = ios.get_io_stat()
        t_load_start = time.perf_counter_ns()
        logger.info("Shape of master: %s x %s", master.shape[0], master.shape[1])
        master['ex'] = pd.Categorical(master['ex'], categories=sorted(master['ex'].unique()), ordered=True)
        trade['ex'] = pd.Categorical(trade['ex'], categories=sorted(trade['ex'].unique()), ordered=True)
        quote['ex'] = pd.Categorical(quote['ex'], categories=sorted(quote['ex'].unique()), ordered=True)
        t_load_elapsed = time.perf_counter_ns() - t_load_start
        io_load_end = ios.get_io_stat()
        writer.writerow(row_start + [-1, "load", "transform", "success", t_load_elapsed, None, None,
                         None, io_load_end - io_load_start, None, None, self.getTableSize(master) + self.getTableSize(trade) + self.getTableSize(quote)])
        logger.info("Shape of trade: %s x %s", trade.shape[0], trade.shape[1])
        logger.info("Shape of quote: %s x %s", quote.shape[0], quote.shape[1])


        io_load_start = ios.get_io_stat()
        t_load_start = time.perf_counter_ns()
        trade = trade.sort_values(by="time", kind='stable')
        quote = quote.sort_values(by="time", kind='stable')
        t_load_elapsed = time.perf_counter_ns() - t_load_start
        io_load_end = ios.get_io_stat()
        writer.writerow(row_start + [-2, "load", "sort by time", "success", t_load_elapsed, None, None,
                         None, io_load_end - io_load_start, None, None, self.getTableSize(master) + self.getTableSize(trade) + self.getTableSize(quote)])

        self.eval_context["exnames"] = dict(zip(exnames["ex"], exnames["name"]))
        self.eval_context["master"] = master
        self.eval_context["trade"] = trade
        self.eval_context["quote"] = quote

    @staticmethod
    def getTableSize(df) -> int:
        return int(df.memory_usage(deep=True).sum() / 1024)

    def getTableStats(self) -> Dict[str, Any]:
        table_stats_dict = {}
        for tNames in ["master", "trade", "quote"]:
            df = self.eval_context[tNames]
            table_stats = {
                "name": tNames,
                "size (MB)": self.getTableSize(df) / 1024,
                "rowCount": df.shape[0],
                "columnCount": df.shape[1],
                "columns": [
                    {"name": col, "type": str(df[col].dtype)}
                    for col in df.columns
                ],
            }
            table_stats_dict[tNames] = table_stats
        return table_stats_dict

    def prepare_run(self) -> None:
        pass

    def execute_query(self, idx: int, tags: Set, query_str: str, parameter: str, runidx: int):
        return eval(query_str, self.eval_context)

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
