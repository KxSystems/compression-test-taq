import os
os.environ['PYKX_4_1_ENABLED'] = 'True'  # must be set before importing pykx
import pykx as kx

import logging
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, Set

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

    def load_resources(self, db_path: Path) -> None:
        logger.info("loading first partition's tables of the kdb+ database at %s into memory", db_path)
        db = kx.DB(path=db_path, change_dir=False)
        self.master = db.master.select(where=kx.Column('date') == kx.Column('date').min()).delete(columns=kx.Column('date')).select(where=kx.Column('i') > -1)
        self.quote = db.quote.select(where=kx.Column('date') == kx.Column('date').min()).delete(columns=kx.Column('date')).select(where=kx.Column('i') > -1)
        self.quote = self.quote.sort_values(by='time').grouped('sym')
        self.trade = db.trade.select(where=kx.Column('date') == kx.Column('date').min()).delete(columns=kx.Column('date')).select(where=kx.Column('i') > -1)
        self.trade = self.trade.sort_values(by='time').grouped('sym')

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
