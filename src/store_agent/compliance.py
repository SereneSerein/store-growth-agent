"""合规扫描:禁用/高风险表述检测与自动改写。

词表来源:P6/08-合规/售后与促销表述红线、P1/08 价格字段字典与 Agent 价格问答测试集。
配置在 config/banned_words.json,可直接改。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[2] / "config" / "banned_words.json"


@dataclass
class Hit:
    word: str
    reason: str
    replacement: str


def _load() -> list[dict]:
    return json.loads(CONFIG.read_text(encoding="utf-8"))["rules"]


def scan(text: str) -> list[Hit]:
    hits = []
    for r in _load():
        if re.search(r["pattern"], text):
            hits.append(Hit(r["pattern"], r["reason"], r["replacement"]))
    return hits


def sanitize(text: str) -> tuple[str, list[Hit]]:
    """命中即改写为带条件的安全表述,返回(新文本, 命中列表)。"""
    hits = scan(text)
    for r in _load():
        text = re.sub(r["pattern"], r["replacement"], text)
    return text, hits
