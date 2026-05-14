import os
os.environ['PYKX_4_1_ENABLED'] = 'True'  # must be set before importing pykx
import pykx as kx

import logging
from datetime import timedelta, datetime
from pathlib import Path
from typing import Any, Dict, Set
import time

logger = logging.getLogger(__name__)


class QueryExecutorPyKXInMemory:
    """
    Handles the setup, execution of PyKX Python queries
    on NYSE TAQ kdb+ database (single partition loaded into memory).
    """
    def __init__(self, param: Dict[str, Any]) -> None:
        self.master: kx.Table = None
        self.quote: kx.Table = None
        self.trade: kx.Table = None
        self.params: Dict[str, Any] = param
        kx.q['timeBucketsStep'] = kx.q('{`s#value[x]!key x}', param['timeBuckets'])

    def load_resources(self, db_path: Path, datadate: datetime.date, writer, row_start, ios) -> None:
        logger.info("loading hive-partitioned tables at %s", db_path)

        io_load_start = ios.get_io_stat()
        t_load_start = time.perf_counter_ns()
        db = kx.DB(path=db_path, change_dir=False)
        self.master = db.master.select(where=kx.Column('date') == datadate).delete(columns=kx.Column('date')).select(where=kx.Column('i') > -1)
        logger.info("Shape of master: %s x %s", self.master.shape[0], self.master.shape[1])
        self.trade = db.trade.select(where=kx.Column('date') == datadate).delete(columns=kx.Column('date')).select(where=kx.Column('i') > -1)
        logger.info("Shape of trade: %s x %s", self.trade.shape[0], self.trade.shape[1])
        self.quote = db.quote.select(where=kx.Column('date') == datadate).delete(columns=kx.Column('date')).select(where=kx.Column('i') > -1)
        logger.info("Shape of quote: %s x %s", self.quote.shape[0], self.quote.shape[1])
        t_load_elapsed = time.perf_counter_ns() - t_load_start
        io_load_end = ios.get_io_stat()
        writer.writerow(row_start + [0, "load", "load a partition into memory", "success", t_load_elapsed, None, None,
                         None, io_load_end - io_load_start, None, None])


        io_load_start = ios.get_io_stat()
        t_load_start = time.perf_counter_ns()
        self.trade = self.trade.sort_values(by='time')
        self.quote = self.quote.sort_values(by='time')
        t_load_elapsed = time.perf_counter_ns() - t_load_start
        io_load_end = ios.get_io_stat()
        writer.writerow(row_start + [-2, "load", "sort by time", "success", t_load_elapsed, None, None,
                         None, io_load_end - io_load_start, None, None])


        io_load_start = ios.get_io_stat()
        t_load_start = time.perf_counter_ns()
        self.trade = self.trade.grouped('sym')
        self.quote = self.quote.grouped('sym')
        t_load_elapsed = time.perf_counter_ns() - t_load_start
        io_load_end = ios.get_io_stat()
        writer.writerow(row_start + [-3, "load", "index", "success", t_load_elapsed, None, None,
                         None, io_load_end - io_load_start, None, None])


    def getTableStats(self) -> Dict[str, Any]:
        table_stats_dict = {}
        for tNames in ["master", "trade", "quote"]:
            df = getattr(self, tNames)
            table_stats = {
                "name": tNames,
                "rowCount": df.size.py(),
                "columnCount": df.shape[1].py(),
                "columns": [{"name": n.py(), "type": t.py().decode()} for n, t in zip(df.dtypes["columns"], df.dtypes["datatypes"])],
            }
            table_stats_dict[tNames] = table_stats
        return table_stats_dict

    def execute_query(self, idx: int, tags: Set, query_str: str, parameter: str, runidx: int):
        eval_context = {
            "kx": kx,
            "timedelta": timedelta,
            "master": self.master,
            "trade": self.trade,
            "quote": self.quote,
            **self.params
        }
        return eval(query_str, eval_context)

    def write_csv(self, res, outFile: Path) -> None:
        kx.q.write.csv(outFile, res)
