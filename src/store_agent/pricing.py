"""价格引擎:纯代码确定性计算,不经过大模型。

四级价格组合(依据 P1/08 价格字段字典与调用规则):
  L1 主机:同一 SKU 的官方商城页面价
  L2 条件:预估到手价/优惠券,只展示、不自行扣减
  L3 配件:单买价;搭配购价仅在对应主机页面成立
  L4 支付:12 期免息月供 = 主机价 / 12(页面口径)
任何一级拿不到官方记录时,返回状态说明而不是估算金额。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from .knowledge import MODEL_DIRS, PriceRecord, load_prices

INSTALLMENT_MONTHS = 12
BUNDLE_HOST = "HUAWEI MateBook 14"  # 搭配购价只在该主机的商品页面观察到
_SCREENS = ("典藏版", "防窥版", "柔光版")
_STORE_TYPES = ("商城页面价", "商城活动页价")


def money(x: float | Decimal) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def fmt(x: float | Decimal) -> str:
    d = money(x)
    return f"¥{d:,.0f}" if d == d.to_integral() else f"¥{d:,.2f}"


@dataclass
class Sku:
    product: str
    memory: str
    storage: str
    screen: str
    style: str
    price: float
    ref_price: float | None
    stock: str
    purchasable: bool
    rid: str
    verified_at: str
    url: str
    condition: str

    @property
    def label(self) -> str:
        screen = "" if self.screen == "标准" else f"/{self.screen}"
        return f"{self.memory}/{self.storage}{screen}"


@dataclass
class Line:
    level: str
    name: str
    amount: float | None
    note: str = ""


@dataclass
class Quote:
    status: str  # ok / ambiguous / no_price / not_found
    product: str
    message: str = ""
    lines: list[Line] = field(default_factory=list)
    total: Decimal | None = None
    monthly: Decimal | None = None
    sku: Sku | None = None
    options: list[str] = field(default_factory=list)
    gifts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    verified_at: str = ""


def parse_style(style: str) -> tuple[str, str, str] | None:
    m = re.search(r"(\d+)\s*GB\s*/\s*(\d+)\s*(GB|TB)", style)
    if not m:
        return None
    screen = next((s for s in _SCREENS if s in style), "标准")
    return f"{m.group(1)}GB", f"{m.group(2)}{m.group(3)}", screen


def _is_store_price(r: PriceRecord) -> bool:
    return r.amount is not None and any(t in r.ptype for t in _STORE_TYPES)


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "").upper()


def skus_for(product: str) -> list[Sku]:
    """某型号的全部可报价 SKU。同一 (内存,存储,屏幕) 多条记录时取核验时间最晚的一条。"""
    canon = MODEL_DIRS[product][1]
    best: dict[tuple[str, str, str], PriceRecord] = {}
    for r in load_prices():
        if r.product != canon or not _is_store_price(r):
            continue
        key = parse_style(r.style)
        if key is None:
            continue
        old = best.get(key)
        if old is None or r.verified_at >= old.verified_at:
            best[key] = r
    out = []
    for (mem, sto, scr), r in best.items():
        out.append(
            Sku(
                product=product, memory=mem, storage=sto, screen=scr, style=r.style,
                price=r.amount, ref_price=r.ref_amount, stock=r.stock,
                purchasable=("缺货" not in r.ptype and "缺货" not in r.stock),
                rid=r.rid, verified_at=r.verified_at, url=r.url, condition=r.condition,
            )
        )
    out.sort(key=lambda s: (s.price, s.label))
    return out


def sku_labels(product: str) -> list[str]:
    return [s.label for s in skus_for(product)]


def _label_match(s: Sku, memory: str, storage: str, screen: str) -> bool:
    return (
        (not memory or _norm(memory) == _norm(s.memory))
        and (not storage or _norm(storage) == _norm(s.storage))
        and (not screen or screen == s.screen)
    )


@dataclass
class Accessory:
    name: str
    standalone: PriceRecord | None = None
    bundle: PriceRecord | None = None


def accessory_catalog() -> dict[str, Accessory]:
    cat: dict[str, Accessory] = {}
    for r in load_prices():
        if not (r.category == "电脑配件" or "M-Pen" in r.product):
            continue
        key = r.product.replace("HUAWEI ", "").strip()  # 同一配件在不同页面名称前缀不同
        a = cat.setdefault(key, Accessory(key))
        if r.amount is None:
            continue
        if "搭配购" in r.ptype:
            a.bundle = a.bundle or r
        elif _is_store_price(r):
            a.standalone = a.standalone or r
    return cat


def _month(total: Decimal) -> Decimal:
    return money(total / INSTALLMENT_MONTHS)


def _gifts(cond: str) -> list[str]:
    m = re.search(r"赠品为(.+?)(；|$)", cond)
    return [m.group(1)] if m else []


def _coupon_note(product: str) -> str:
    canon = MODEL_DIRS[product][1]
    for r in load_prices():
        if r.product == canon and "预估到手" in r.ptype and r.amount is not None:
            return f"页面曾显示「预估到手价」{fmt(r.amount)}(含优惠券等条件,以结算页为准),本报价不采用"
    for r in load_prices():
        if r.product == canon and re.search(r"\d+元优惠券", r.condition):
            m = re.search(r"(\d+)元优惠券", r.condition)
            return f"页面显示{m.group(1)}元优惠券,未自行扣减,以结算页为准"
    return ""


def _find_accessory(name: str) -> Accessory | None:
    cat = accessory_catalog()
    for key, acc in cat.items():
        if _norm(name) == _norm(key):
            return acc
    for key, acc in cat.items():
        if _norm(name) in _norm(key) or _norm(key) in _norm(name):
            return acc
    return None


def accessory_names() -> list[str]:
    return sorted(k for k, a in accessory_catalog().items() if a.standalone or a.bundle)


def quote(
    product: str,
    memory: str = "",
    storage: str = "",
    screen: str = "",
    accessories: list[str] | None = None,
    installment: bool = True,
) -> Quote:
    """生成报价。信息不足时返回 ambiguous 并列出可选项,绝不猜 SKU。"""
    accessories = accessories or []
    q = Quote(status="ok", product=product)
    if product not in MODEL_DIRS:
        q.status = "not_found"
        q.message = f"未收录型号「{product}」。"
        return q

    skus = skus_for(product)
    q.trace.append(f"L1 型号={product},候选 SKU {len(skus)} 个")
    if not skus:
        q.status = "no_price"
        q.message = (
            f"{product}在价格快照中没有当前可用的商城页面价(可能已下架或仅有官网参考起价)。"
            "不使用发布价、参考起价或相近型号价格代替,请以华为商城当前页面或店内询价为准。"
        )
        q.trace.append("无商城页面价 -> 拒绝估价")
        return q

    cands = [s for s in skus if _label_match(s, memory, storage, screen)]
    q.trace.append(f"按 内存={memory or '-'} 存储={storage or '-'} 屏幕={screen or '-'} 过滤,剩 {len(cands)} 个")
    if len(cands) != 1:
        q.status = "ambiguous"
        q.options = [f"{s.label} {fmt(s.price)}" for s in (cands or skus)]
        q.message = "配置未唯一确定,请先和顾客确认:" + (
            "以下配置都符合条件,请选一个。" if cands else "没有完全匹配的配置,可选如下。"
        )
        return q

    sku = cands[0]
    q.sku = sku
    q.verified_at = sku.verified_at
    q.sources.append(sku.url)
    host = Decimal(str(sku.price))
    q.lines.append(Line("L1 主机", f"{product} {sku.label}", sku.price, f"官方商城页面价,{sku.rid}"))
    q.trace.append(f"L1 命中 {sku.rid} 价格 {sku.price}")
    if sku.ref_price:
        q.warnings.append(f"页面同屏另有划线价 {fmt(sku.ref_price)},库中不推断其含义,不当作原价宣传")
    if not sku.purchasable:
        q.warnings.append("该配置页面显示缺货,价格不代表可下单")
    if sku.stock:
        q.warnings.append(f"库存/交付状态(核验时点):{sku.stock}")
    q.gifts = _gifts(sku.condition)

    note = _coupon_note(product)
    if note:
        q.lines.append(Line("L2 条件", "优惠券/预估到手价", None, note))
        q.trace.append("L2 仅记录条件,不扣减")

    total = host
    for name in accessories:
        acc = _find_accessory(name)
        if acc is None or not (acc.standalone or acc.bundle):
            q.warnings.append(f"配件「{name}」在价格快照中无公开金额,未计入,请店内核实")
            q.trace.append(f"L3 {name} 无价 -> 跳过")
            continue
        if acc.standalone:
            amt = acc.standalone.amount
            q.lines.append(Line("L3 配件", acc.name, amt, f"单买价,{acc.standalone.rid}"))
            q.sources.append(acc.standalone.url)
            total += Decimal(str(amt))
            q.trace.append(f"L3 {acc.name} 单买 {amt}")
            if acc.bundle and product == BUNDLE_HOST:
                q.warnings.append(
                    f"{acc.name}另有搭配购价 {fmt(acc.bundle.amount)},仅限商城主机页面搭配,是否可用以结算页为准,本报价未采用"
                )
        else:
            q.warnings.append(
                f"配件「{acc.name}」只有搭配购价 {fmt(acc.bundle.amount)},没有单买价,未计入总价;"
                "搭配价只适用于对应主机页面"
            )
            q.trace.append(f"L3 {acc.name} 仅搭配价 -> 不入总价")

    q.total = money(total)
    if installment:
        q.monthly = _month(host)
        q.lines.append(
            Line("L4 分期", f"主机 {INSTALLMENT_MONTHS} 期", float(q.monthly),
                 "按页面「至高12期0分期利息」口径,仅主机;是否具备资格以结算页为准")
        )
        q.trace.append(f"L4 月供 {q.monthly}")
    q.trace.append(f"合计 {q.total}")
    q.message = "已按官方价格快照报价。"
    return q


def render_quote(q: Quote) -> str:
    """把 Quote 渲染成给店员看的 markdown。"""
    if q.status != "ok":
        body = [f"**{q.message}**"]
        body += [f"- {o}" for o in q.options]
        return "\n".join(body)
    out = [f"### {q.product} 报价(价格核验时间 {q.verified_at[:16].replace('T', ' ')})", ""]
    out += ["| 层级 | 项目 | 金额 | 说明 |", "|---|---|---:|---|"]
    for ln in q.lines:
        amt = "-" if ln.amount is None else fmt(ln.amount) + ("/月" if ln.level.startswith("L4") else "")
        out.append(f"| {ln.level} | {ln.name} | {amt} | {ln.note} |")
    out += ["", f"**合计(主机+配件):{fmt(q.total)}**"]
    if q.gifts:
        out.append(f"页面赠品(不计价、以结算页为准):{'、'.join(q.gifts)}")
    for w in q.warnings:
        out.append(f"- ⚠ {w}")
    out.append("")
    out.append("价格为官方公开页面快照,不是承诺价;成交前请在结算页复核地区、库存、优惠与会员资格。")
    return "\n".join(out)
