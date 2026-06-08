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
        self.params: Dict[str, Any] = param
        kx.q['timeBucketsStep'] = kx.q('{`s#value[x]!key x}', param['timeBuckets'])
        kx.q._register("./src/pivot")
        kx.pivot = kx.q('.pvt.pivot')
        kx.fills = kx.q('fills')
        self.eval_context: Dict[str, Any] = {
            "kx": kx,
            "timedelta": timedelta,
            **param,
        }

    def load_resources(self, db_path: Path, datadate: datetime.date, writer, row_start, ios) -> None:
        dpath = db_path / datadate.strftime('%Y.%m.%d')
        logger.info("loading kdb+ tables at %s", dpath)

        io_load_start = ios.get_io_stat()
        t_load_start = time.perf_counter_ns()
        kx.q(f"sym: get `:{db_path}/sym")
        kx.q(f"exnames: get `:{db_path}/exnames")
        master = kx.q.get(dpath / "master").select(where=kx.Column('i') > -1)
        logger.info("Shape of master: %s x %s", master.shape[0], master.shape[1])
        trade = kx.q.get(dpath / "trade").select(where=kx.Column('i') > -1)
        logger.info("Shape of trade: %s x %s", trade.shape[0], trade.shape[1])
        quote = kx.q.get(dpath / "quote").select(where=kx.Column('i') > -1)
        logger.info("Shape of quote: %s x %s", quote.shape[0], quote.shape[1])
        t_load_elapsed = time.perf_counter_ns() - t_load_start
        io_load_end = ios.get_io_stat()
        writer.writerow(row_start + [0, "load", "load a partition into memory", "success", t_load_elapsed, None, None,
                         None, io_load_end - io_load_start, None, None])


        io_load_start = ios.get_io_stat()
        t_load_start = time.perf_counter_ns()
        logger.info("ordering trade by time")
        trade = trade.sort_values(by='time')
        logger.info("ordering quote by time")
        quote = quote.sort_values(by='time')
        t_load_elapsed = time.perf_counter_ns() - t_load_start
        io_load_end = ios.get_io_stat()
        writer.writerow(row_start + [-2, "load", "sort by time", "success", t_load_elapsed, None, None,
                         None, io_load_end - io_load_start, None, None])


        io_load_start = ios.get_io_stat()
        t_load_start = time.perf_counter_ns()
        logger.info("adding index (grouped attribute) on sym in trade")
        trade.grouped('sym')
        logger.info("adding index (grouped attribute) on sym in quote")
        quote.grouped('sym')
        t_load_elapsed = time.perf_counter_ns() - t_load_start
        io_load_end = ios.get_io_stat()
        writer.writerow(row_start + [-3, "load", "index", "success", t_load_elapsed, None, None,
                         None, io_load_end - io_load_start, None, None])

        self.eval_context["master"] = master
        self.eval_context["trade"] = trade
        self.eval_context["quote"] = quote


    def getTableStats(self) -> Dict[str, Any]:
        table_stats_dict = {}
        for tNames in ["master", "trade", "quote"]:
            df = self.eval_context[tNames]
            table_stats = {
                "name": tNames,
                "rowCount": df.size.py(),
                "columnCount": df.shape[1].py(),
                "columns": [{"name": n.py(), "type": t.py().decode()} for n, t in zip(df.dtypes["columns"], df.dtypes["datatypes"])],
            }
            table_stats_dict[tNames] = table_stats
        return table_stats_dict

    def prepare_run(self) -> None:
        pass

    def execute_query(self, idx: int, tags: Set, query_str: str, parameter: str, runidx: int):
        return eval(query_str, self.eval_context)

    def write_csv(self, res, outFile: Path) -> None:
        kx.q.write.csv(outFile, res)
