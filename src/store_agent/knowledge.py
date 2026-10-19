"""知识库加载:产品事实、卖点与限制、价格快照、场景卡。

资料放在项目根目录的 data_raw/ 下(随仓库发布),也可用环境变量 KB_ROOT 指向别处。
所有结构化信息都由本模块从原始 markdown / csv 解析,业务代码不直接读文件。
文件缺失或损坏时不抛异常:打印中文警告并返回空数据,界面仍可打开。
"""
from __future__ import annotations

import csv
import os
import re
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

# 项目根目录:基于本文件位置(src/store_agent/knowledge.py -> 上两级),不依赖运行时的当前工作目录
ROOT = Path(__file__).resolve().parents[2]
PRICE_CSV = "P1-产品参数库/08-官方公开价格快照/官方价格快照.csv"

_warned: set[str] = set()


def _warn(msg: str) -> None:
    """同一条警告只打印一次,避免刷屏。"""
    if msg not in _warned:
        _warned.add(msg)
        print(f"[警告] {msg}", flush=True)


def kb_root() -> Path:
    env = os.environ.get("KB_ROOT")
    if env:
        return Path(env)
    base = ROOT / "data_raw"
    subs = sorted(p for p in base.glob("*") if p.is_dir()) if base.is_dir() else []
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
    p = kb_root() / PRICE_CSV
    if not p.is_file():
        _warn(f"价格快照文件缺失:{p},报价功能不可用,使用空数据")
        return []
    try:
        with open(p, encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
    except Exception as e:  # noqa: BLE001 - 文件损坏/编码错误同样降级
        _warn(f"价格快照读取失败({type(e).__name__}: {e}),使用空数据")
        return []
    out = []
    for r in rows:
        try:
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
        except (KeyError, TypeError) as e:
            _warn(f"价格快照存在缺少字段的行,已跳过(缺少 {e})")
    return out


@lru_cache(maxsize=None)
def load_product(name: str) -> ProductKB:
    sub, _ = MODEL_DIRS[name]
    d = kb_root() / "P1-产品参数库" / sub
    kb = ProductKB(name=name)
    f = d / "产品事实.md"
    s = d / "卖点与限制.md"
    if f.is_file():
        kb.facts_md = f.read_text(encoding="utf-8")
    else:
        _warn(f"产品事实缺失:{name},相关内容将缺少依据")
    if s.is_file():
        kb.selling_md = s.read_text(encoding="utf-8")
        kb.sections = _split_sections(kb.selling_md)
    else:
        _warn(f"卖点与限制缺失:{name},相关内容将缺少依据")
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
        if f.is_file():
            res[fn] = f.read_text(encoding="utf-8")
        else:
            res[fn] = ""
            _warn(f"场景资料缺失:{name}/{fn}.md,该场景将缺少背景资料")
    return res


def scene_names() -> list[str]:
    return list(SCENE_DIRS)


def data_report() -> list[tuple[bool, str]]:
    """启动自检:每类数据文件是否存在及数量。返回 [(是否正常, 说明)]。"""
    root = kb_root()
    rep: list[tuple[bool, str]] = []
    if not root.is_dir():
        rep.append((False, f"资料目录不存在:{root}"))  # 继续往下逐项报告,每类文件都显示缺失
    csv_ok = (root / PRICE_CSV).is_file()
    n = len(load_prices()) if csv_ok else 0
    rep.append((csv_ok and n > 0, f"官方价格快照.csv — {n} 条" if csv_ok else "官方价格快照.csv — 文件缺失,使用空数据"))
    for fn in ("产品事实.md", "卖点与限制.md"):
        have = sum(1 for sub, _ in MODEL_DIRS.values() if (root / "P1-产品参数库" / sub / fn).is_file())
        rep.append((have == len(MODEL_DIRS), f"{fn} — {have}/{len(MODEL_DIRS)} 个型号" + ("" if have else ",文件缺失,使用空数据")))
    have = sum(1 for d in SCENE_DIRS.values() if (root / d / "客户画像.md").is_file())
    rep.append((have == len(SCENE_DIRS), f"场景卡资料(客户画像.md) — {have}/{len(SCENE_DIRS)} 个场景" + ("" if have else ",文件缺失,使用空数据")))
    return rep


def print_data_report() -> bool:
    """在控制台打印自检结果,返回是否全部正常。"""
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:  # 控制台编码(如 GBK)不支持 emoji 时,改用文字符号
        "✅❌".encode(enc)
        mark_ok, mark_bad = "✅", "❌"
    except (UnicodeEncodeError, LookupError):
        mark_ok, mark_bad = "[正常]", "[缺失]"
    print(f"资料目录:{kb_root()}", flush=True)
    rep = data_report()
    for ok, msg in rep:
        print(f"{mark_ok if ok else mark_bad} {msg}", flush=True)
    return all(ok for ok, _ in rep)
