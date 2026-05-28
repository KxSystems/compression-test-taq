import os
os.environ['PYKX_4_1_ENABLED'] = 'True'  # must be set before importing pykx
import pykx as kx

import logging
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, Set

logger = logging.getLogger(__name__)


class QueryExecutorPyKX:
    """
    Handles the setup, execution of PyKX Python queries
    on NYSE TAQ kdb+ database.
    """
    def __init__(self, param: Dict[str, Any]) -> None:
        self.db: kx.DB = None
        self.params: Dict[str, Any] = param

    def load_resources(self, db_path: Path) -> None:
        logger.info("loading kdb DB %s", db_path)
        self.db = kx.DB(path=db_path, change_dir=False)

    def prepare_run(self) -> None:
        pass

    def execute_query(self, idx: int, tags: Set, query_str: str, parameter: str, runidx: int):
        eval_context = {
            "kx": kx,
            "timedelta": timedelta,
            "db": self.db,
            **self.params
        }
        return eval(query_str, eval_context)

    def write_csv(self, res, outFile: Path) -> None:
        kx.q.write.csv(outFile, res)


class QueryExecutorPyKXQ:
    """
    Handles the setup, execution of PyKX q queries
    on NYSE TAQ kdb+ database.
    """
    def __init__(self, paramdir: Path) -> None:
        self.db: kx.DB = None
        self.paramdir: Path = paramdir

    def load_resources(self, db_path: Path) -> None:
        logger.info("loading kdb DB %s", db_path)
        self.db = kx.DB(path=db_path, change_dir=False)
        kx.q.system.load("src/getQueryParameters.q")
        kx.q('getQueryParameters', kx.q.hsym(kx.SymbolAtom(self.paramdir)))

    def prepare_run(self) -> None:
        pass

    def execute_query(self, idx: int, tags: Set, query_str: str, parameter: str, runidx: int):
        return kx.q(query_str)

    def write_csv(self, res, outFile: Path) -> None:
        kx.q.write.csv(outFile, res)
