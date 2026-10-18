"""需求信号抽取与配置推荐:纯规则,保证无大模型时也有依据、可复现。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .pricing import Sku, fmt, skus_for

# 标签 -> 触发关键词
TAG_KEYWORDS: dict[str, tuple[str, ...]] = {
    "便携": ("背", "携带", "带回家", "出差", "轻", "通勤", "宿舍", "咖啡馆", "到处"),
    "续航": ("电池", "续航", "电量", "不够电"),
    "屏幕": ("屏幕", "色彩", "调色", "画面", "显示"),
    "隐私": ("隐私", "偷看", "旁边人", "防窥", "不要看到"),
    "反光": ("反光", "强光", "咖啡馆", "户外", "窗边"),
    "投屏接口": ("投屏", "投影", "接口", "外接", "扩展坞", "转接"),
    "视频创作": ("剪辑", "vlog", "Vlog", "商单", "短视频", "剪点"),
    "办公文档": ("论文", "PPT", "ppt", "报价单", "文档", "表格", "记账", "报表", "写稿", "撰稿"),
    "编程": ("Python", "python", "编程", "代码"),
    "会议": ("会议", "视频会议", "汇报", "演示"),
    "协同": ("手机", "平板", "协同", "传文件"),
    "批量采购": ("批量", "十个", "统一配", "团队", "公司"),
    "预算敏感": ("预算有限", "便宜", "性价比", "学生"),
    "手写": ("手写", "笔记", "画", "批注"),
}

_CN = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _cn_to_int(s: str) -> int | None:
    if not s:
        return None
    if s.isdigit():
        return int(s)
    total, cur = 0, 0
    for ch in s:
        if ch in _CN:
            cur = _CN[ch]
        elif ch == "十":
            total += (cur or 1) * 10
            cur = 0
        else:
            return None
    return total + cur


def parse_budget(text: str) -> tuple[int | None, bool]:
    """返回 (预算元, 是否为'上限')。无法识别返回 (None, False)。"""
    m = re.search(r"预算[^0-9一二三四五六七八九十两万千]*([0-9.]+|[一二三四五六七八九十两]+)\s*(万|千|k|K)?", text)
    if not m:
        m = re.search(r"([0-9.]+|[一二三四五六七八九十两]+)\s*(万|千)(?:元|块)?(?:以内|左右|上下|以下)?", text)
    if not m:
        return None, False
    raw, unit = m.group(1), m.group(2)
    try:
        num = float(raw) if re.fullmatch(r"[0-9.]+", raw) else float(_cn_to_int(raw) or 0)
    except ValueError:
        return None, False
    if num <= 0:
        return None, False
    mult = {"万": 10000, "千": 1000, "k": 1000, "K": 1000}.get(unit or "", 1)
    val = int(num * mult)
    if val < 1000:  # "预算8" 之类无单位的小数字,不可信
        return None, False
    tail = text[m.end() : m.end() + 6]
    return val, ("以内" in tail or "以下" in tail)


@dataclass
class Signals:
    tags: list[str] = field(default_factory=list)
    budget: int | None = None
    budget_is_cap: bool = False
    evidence: dict[str, str] = field(default_factory=dict)  # 标签 -> 客户原话片段


def _snippet(text: str, kw: str) -> str:
    i = text.find(kw)
    if i < 0:
        return kw
    a = max(0, i - 8)
    b = min(len(text), i + len(kw) + 10)
    return text[a:b].strip("，。,. ")


def extract(clue: str) -> Signals:
    sig = Signals()
    for tag, kws in TAG_KEYWORDS.items():
        for kw in kws:
            if kw in clue:
                sig.tags.append(tag)
                sig.evidence[tag] = _snippet(clue, kw)
                break
    sig.budget, sig.budget_is_cap = parse_budget(clue)
    return sig


@dataclass
class Recommendation:
    base: Sku | None  # 保底
    balanced: Sku | None  # 均衡(主推)
    advanced: Sku | None  # 进阶
    reasons: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _label_with_price(s: Sku) -> str:
    return f"{s.label}({fmt(s.price)})"


def recommend(product: str, sig: Signals) -> Recommendation:
    """三档推荐:先过硬门槛(隐私/反光),再按预算和任务选主推。"""
    rec = Recommendation(None, None, None)
    pool = [s for s in skus_for(product) if s.purchasable]
    if not pool:
        rec.notes.append("该型号没有可下单的商城页面价,无法给出配置档位,请改为店内询价")
        return rec

    need_screen = None
    if "隐私" in sig.tags and any(s.screen in ("防窥版", "典藏版") for s in pool):
        need_screen = ("防窥版", "典藏版")
        rec.reasons.append("客户提到隐私,硬门槛是防窥屏版本(需现场实机验证侧视效果)")
    elif "反光" in sig.tags and any(s.screen == "柔光版" for s in pool):
        need_screen = ("柔光版",)
        rec.reasons.append("客户常在强光/咖啡馆使用,优先核对柔光屏版本")
    if need_screen:
        pool_hard = [s for s in pool if s.screen in need_screen]
    else:
        # 客户没有提出屏幕特殊需求时,不主动推柔光/防窥/典藏等加价版本
        std = [s for s in pool if s.screen == "标准"]
        pool_hard = std or pool

    pool_hard.sort(key=lambda s: s.price)
    cap = None
    if sig.budget:
        cap = sig.budget if sig.budget_is_cap else int(sig.budget * 1.1)
    within = [s for s in pool_hard if cap is None or s.price <= cap]
    if sig.budget and not within:
        rec.notes.append(
            f"预算 {fmt(sig.budget)} 低于满足硬门槛的最低配置 {fmt(pool_hard[0].price)},"
            "建议先确认预算弹性或放弃该硬门槛"
        )
        within = pool_hard[:1]

    heavy = any(t in sig.tags for t in ("视频创作", "编程", "批量采购")) and "预算敏感" not in sig.tags
    if heavy:
        # 重任务:主推预算内较大内存/存储的一档(取预算内价格上半区)
        rec.balanced = within[min(len(within) - 1, len(within) // 2 + (1 if len(within) > 2 else 0))]
        rec.reasons.append("有视频/编程类任务,倾向预算内更大内存与存储(具体表现需用客户自己的工程文件实测)")
    else:
        rec.balanced = within[len(within) // 2] if len(within) > 2 else within[0]
        if "预算敏感" in sig.tags:
            rec.balanced = within[0]
            rec.reasons.append("预算敏感,主推满足硬门槛的最低配置")
    rec.base = within[0]
    higher = [s for s in pool_hard if s.price > rec.balanced.price]
    rec.advanced = higher[0] if higher else None
    if rec.advanced and cap and rec.advanced.price > cap:
        rec.notes.append("进阶档超出预算,仅在顾客愿意为明确痛点增加预算时再提")
    if rec.base is rec.balanced:
        rec.notes.append("保底与主推为同一档:预算内可选配置有限")
    return rec
