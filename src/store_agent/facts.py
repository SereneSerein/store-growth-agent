"""事实包:从「卖点与限制.md」抽取可引用事实与表达边界。

模型与兜底模板都只能用这里的内容,保证"信息全部来自产品资料"。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .knowledge import load_product

ANGLES = ("型号身份卡", "屏幕与显示卡", "性能与存储卡", "便携续航接口卡", "系统协同与兼容卡", "适用人群与限制卡")


@dataclass
class FactPack:
    product: str
    positioning: str = ""
    facts: dict[str, list[str]] = field(default_factory=dict)  # 角度 -> 事实
    limits: dict[str, list[str]] = field(default_factory=dict)  # 角度 -> 表达边界
    unfit: list[str] = field(default_factory=list)
    must_ask: list[str] = field(default_factory=list)
    fit: list[str] = field(default_factory=list)
    source: str = ""

    def as_text(self, max_per_angle: int = 5) -> str:
        out = [f"型号:{self.product}", f"一句话定位:{self.positioning}"]
        for a in ANGLES:
            if self.facts.get(a):
                out.append(f"[{a}·事实]")
                out += [f"- {x}" for x in self.facts[a][:max_per_angle]]
            if self.limits.get(a):
                out.append(f"[{a}·表达边界]")
                out += [f"- {x}" for x in self.limits[a][:3]]
        if self.unfit:
            out.append("[不适合直接下结论]")
            out += [f"- {x}" for x in self.unfit[:6]]
        if self.must_ask:
            out.append("[销售前必须追问]")
            out += [f"- {x}" for x in self.must_ask[:6]]
        return "\n".join(out)

    def all_facts(self) -> list[str]:
        return [f for a in ANGLES for f in self.facts.get(a, [])]


def _bullets(block: str) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"^\s*-\s+(.+)$", block, flags=re.M)]


def _between(block: str, start: str, end: str | None) -> str:
    i = block.find(start)
    if i < 0:
        return ""
    i += len(start)
    j = block.find(end, i) if end else -1
    return block[i : j if j > 0 else None]


def build(product: str) -> FactPack:
    kb = load_product(product)
    fp = FactPack(product=product, source=f"P1-产品参数库/…/{product}/卖点与限制.md")
    sec = kb.sections
    for k, v in sec.items():
        if k == "一句话定位":
            fp.positioning = v.split("\n\n")[0].strip()
    for key, body in sec.items():
        name = re.sub(r"^\d+\.\s*", "", key)
        if name in ANGLES:
            fp.facts[name] = _bullets(_between(body, "**支撑事实**", "**表达边界**"))
            fp.limits[name] = _bullets(_between(body, "**表达边界**", None))
    fp.fit = _bullets(sec.get("适合进入候选清单的任务", ""))
    fp.unfit = _bullets(sec.get("不适合直接下结论的任务", ""))
    fp.must_ask = _bullets(sec.get("发布或销售前必须追问", ""))
    return fp
