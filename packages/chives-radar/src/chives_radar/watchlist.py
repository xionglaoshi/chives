"""Persistence for watchlist symbols added at runtime.

The YAML configuration is never modified: runtime additions live in a separate
JSON file next to the engine state.  Reads tolerate a missing or corrupt file;
writes replace the file atomically.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

logger = logging.getLogger("chives_radar.watchlist")

RUNTIME_FILE_NAME = "watchlist.runtime.json"
RUNTIME_TMP_SUFFIX = ".tmp"


@dataclass(frozen=True)
class RuntimeWatchlistState:
    codes: tuple[str, ...] = ()
    names: Mapping[str, str] = field(default_factory=dict)


class RuntimeWatchlist:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> RuntimeWatchlistState:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.info("运行时自选股文件 %s 不存在，按空处理", self.path)
            return RuntimeWatchlistState()
        except OSError as exc:
            logger.warning("无法读取运行时自选股文件 %s: %s，按空处理", self.path, exc)
            return RuntimeWatchlistState()
        try:
            raw: Any = json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning("运行时自选股文件 %s 已损坏（%s），按空处理", self.path, exc)
            return RuntimeWatchlistState()
        if isinstance(raw, list):
            codes_raw, names_raw = raw, {}
        elif isinstance(raw, dict):
            codes_raw, names_raw = raw.get("codes"), raw.get("names", {})
        else:
            logger.warning("运行时自选股文件 %s 结构错误，按空处理", self.path)
            return RuntimeWatchlistState()
        if not isinstance(codes_raw, list):
            logger.warning("运行时自选股文件 %s 缺少 codes 数组，按空处理", self.path)
            return RuntimeWatchlistState()
        if not isinstance(names_raw, dict):
            names_raw = {}
        codes = tuple(item for item in codes_raw if isinstance(item, str))
        names = {
            key: value
            for key, value in names_raw.items()
            if isinstance(key, str) and isinstance(value, str) and value
        }
        return RuntimeWatchlistState(codes=codes, names=names)

    def save(self, codes: list[str]) -> None:
        data = json.dumps(list(codes), ensure_ascii=False, allow_nan=False, indent=2)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{self.path.name}{RUNTIME_TMP_SUFFIX}")
        try:
            with tmp.open("w", encoding="utf-8") as handle:
                handle.write(data)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise
