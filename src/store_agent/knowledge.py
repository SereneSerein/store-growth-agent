"""知识库加载:产品事实、卖点与限制、价格快照、场景卡。

资料包不入库(见 .gitignore),路径通过环境变量 KB_ROOT 或默认的 data_raw/ 指定。
所有结构化信息都由本模块从原始 markdown / csv 解析,业务代码不直接读文件。
"""
from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def kb_root() -> Path:
    env = os.environ.get("KB_ROOT")
    if env:
        return Path(env)
    base = ROOT / "data_raw"
    subs = [p for p in base.glob("*") if p.is_dir()]
    return subs[0] if subs else base


# 价格快照里的规范产品名 -> 资料目录(相对 P1)
MODEL_DIRS: dict[str, tuple[str, str]] = {
    # 展示名: (P1 子目录, 价格 CSV 中的规范产品名关键字)
    "HUAWEI MateBook Pro S": ("01-鸿蒙电脑/HUAWEI MateBook Pro S", "HUAWEI MateBook Pro S"),
    "HUAWEI MateBook Pro": ("01-鸿蒙电脑/HUAWEI MateBook Pro", "HUAWEI MateBook Pro（鸿蒙版）"),
    "HUAWEI MateBook 14": ("01-鸿蒙电脑/HUAWEI MateBook 14", "HUAWEI MateBook 14（鸿蒙版）"),
    "HUAWEI MateBook Fold 非凡大师": (
        "01-鸿蒙电脑/HUAWEI MateBook Fold 非凡大师",
        "HUAWEI MateBook Fold 非凡大师",
    ),
    "MateBook 14 酷睿 Ultra": ("02-MateBook-Windows/MateBook 14 酷睿 Ultra", "HUAWEI MateBook 14 酷睿 Ultra"),
    "MateBook D 14": ("02-MateBook-Windows/MateBook D 14", "HUAWEI MateBook D 14 2024"),
    "MateBook D 16": ("02-MateBook-Windows/MateBook D 16", "HUAWEI MateBook D 16 2024"),
    "MateBook D 16 SE 版": (
        "02-MateBook-Windows/MateBook D 16 SE 版",
        "HUAWEI MateBook D 16 SE 版 2024",
    ),
    "MateBook GT 系列": ("02-MateBook-Windows/MateBook GT 系列", "HUAWEI MateBook GT 14"),
    "MateBook X系列": (
        "02-MateBook-Windows/MateBook X系列",
        "HUAWEI MateBook X Pro 酷睿 Ultra 微绒典藏版",
    ),
}


@dataclass
class PriceRecord:
    rid: str
    product: str
    style: str  # 精确款式
    ptype: str  # 价格类型
    amount: float | None
    ref_amount: float | None
    condition: str
    stock: str
    verified_at: str
    url: str
    category: str


@dataclass
class ProductKB:
    name: str
    facts_md: str = ""
    selling_md: str = ""
    sections: dict[str, str] = field(default_factory=dict)  # 卖点文件按 ## / ### 切分
    image_dir: Path | None = None


def _num(s: str) -> float | None:
    s = (s or "").strip().replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _split_sections(md: str) -> dict[str, str]:
    out: dict[str, list[str]] = {}
    cur = "_head"
    out[cur] = []
    for line in md.splitlines():
        m = re.match(r"^#{2,3}\s+(.*)$", line)
        if m:
            cur = m.group(1).strip()
            out.setdefault(cur, [])
        else:
            out[cur].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


@lru_cache(maxsize=1)
def load_prices() -> list[PriceRecord]:
    p = kb_root() / "P1-产品参数库/08-官方公开价格快照/官方价格快照.csv"
    rows = list(csv.DictReader(open(p, encoding="utf-8-sig")))
    out = []
    for r in rows:
        out.append(
            PriceRecord(
                rid=r["记录ID"],
                product=r["规范产品名称"],
                style=r["精确款式"],
                ptype=r["价格类型"],
                amount=_num(r["页面金额（元）"]),
                ref_amount=_num(r["参考或划线金额（元）"]),
                condition=r["条件摘要"],
                stock=r["库存状态"],
                verified_at=r["核验时间"],
                url=r["官方URL"],
                category=r["分类"],
            )
        )
    return out


@lru_cache(maxsize=None)
def load_product(name: str) -> ProductKB:
    sub, _ = MODEL_DIRS[name]
    d = kb_root() / "P1-产品参数库" / sub
    kb = ProductKB(name=name)
    f = d / "产品事实.md"
    s = d / "卖点与限制.md"
    if f.exists():
        kb.facts_md = f.read_text(encoding="utf-8")
    if s.exists():
        kb.selling_md = s.read_text(encoding="utf-8")
        kb.sections = _split_sections(kb.selling_md)
    kb.image_dir = d / "images" if (d / "images").exists() else None
    return kb


def product_names() -> list[str]:
    return list(MODEL_DIRS)


# ---- 场景卡 ----
SCENE_DIRS = {
    "零售门店顾客": "P8-客户场景库/12-行业场景/21-零售门店",
    "高校学生": "P8-客户场景库/12-行业场景/08-高校学生",
    "自由职业者": "P8-客户场景库/12-行业场景/29-自由职业",
    "企业高管": "P8-客户场景库/12-行业场景/28-企业高管",
    "销售团队": "P8-客户场景库/12-行业场景/25-销售团队",
    "视频制作": "P8-客户场景库/12-行业场景/14-视频制作",
}


@lru_cache(maxsize=None)
def load_scene(name: str) -> dict[str, str]:
    d = kb_root() / SCENE_DIRS[name]
    res = {}
    for fn in ("客户画像", "问题清单", "方案输出模板", "验收清单"):
        f = d / f"{fn}.md"
        res[fn] = f.read_text(encoding="utf-8") if f.exists() else ""
    return res


def scene_names() -> list[str]:
    return list(SCENE_DIRS)
