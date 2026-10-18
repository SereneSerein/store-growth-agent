"""价格引擎测试:每个期望值都由 P1/08 价格快照里的原始金额人工对照,不是用代码算出来再断言。

编号 T01~T18。覆盖:单品命中、屏幕版本区分、配件叠加、分期、搭配价不入总价、缺货、
下架/无价拒绝估价、信息不全返回追问、边界(未知型号/未知配件)。
"""
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_agent.pricing import quote, skus_for  # noqa: E402

PRO_S = "HUAWEI MateBook Pro S"
M14 = "HUAWEI MateBook 14"
PRO = "HUAWEI MateBook Pro"
FOLD = "HUAWEI MateBook Fold 非凡大师"


def total(q):
    assert q.status == "ok", q.message
    return q.total


# --- 单品命中(金额来自 PRICE-0051..0057)---
def test_t01_pro_s_16_512():
    assert total(quote(PRO_S, "16GB", "512GB", "标准")) == Decimal("7999.00")


def test_t02_pro_s_24_512():
    assert total(quote(PRO_S, "24GB", "512GB", "标准")) == Decimal("8999.00")


def test_t03_pro_s_24_1tb():
    assert total(quote(PRO_S, "24GB", "1TB", "标准")) == Decimal("10499.00")


def test_t04_pro_s_privacy_vs_soft_differ():
    """同为 24GB/512GB:柔光 9999、防窥 10299,不能混。"""
    assert total(quote(PRO_S, "24GB", "512GB", "柔光版")) == Decimal("9999.00")
    assert total(quote(PRO_S, "24GB", "512GB", "防窥版")) == Decimal("10299.00")


def test_t05_pro_s_collector():
    assert total(quote(PRO_S, "32GB", "1TB", "典藏版")) == Decimal("14999.00")


def test_t06_m14_cheapest_and_amount():
    assert total(quote(M14, "16GB", "512GB", "标准")) == Decimal("5899.00")


def test_t07_fold_32_2tb():
    assert total(quote(FOLD, "32GB", "2TB", "标准")) == Decimal("29999.00")


def test_t08_pro_coupon_not_subtracted():
    """Pro 24GB/512GB 页面价 9999,页面有 500 元券,但不得自行扣减。"""
    q = quote(PRO, "24GB", "512GB", "标准")
    assert q.total == Decimal("9999.00")
    assert any("优惠券" in ln.name or "优惠券" in ln.note for ln in q.lines)


# --- 配件叠加(M-Pen 3 单买 599、内胆包 299、鼠标3 109)---
def test_t09_host_plus_one_accessory():
    q = quote(PRO_S, "24GB", "512GB", "标准", ["华为内胆包"])
    assert q.total == Decimal("9298.00")  # 8999 + 299


def test_t10_host_plus_two_accessories():
    q = quote(M14, "16GB", "512GB", "标准", ["华为内胆包", "华为无线鼠标 3"])
    assert q.total == Decimal("6307.00")  # 5899 + 299 + 109


def test_t11_bundle_price_not_used_for_m_pen():
    """M-Pen 3 搭配价 549 仅限主机页面搭配,按单买价 599 计,并提示。"""
    q = quote(M14, "16GB", "512GB", "标准", ["M-Pen 3 多功能笔"])
    assert q.total == Decimal("6498.00")  # 5899 + 599,不是 549
    assert any("搭配购价" in w for w in q.warnings)


# --- 分期:只对主机,按 12 期、四舍五入到分 ---
def test_t12_installment_host_only():
    q = quote(PRO_S, "16GB", "512GB", "标准", ["华为内胆包"])
    assert q.monthly == Decimal("666.58")  # 7999/12 = 666.583…,与页面「低至666.58元/月」一致


def test_t13_installment_matches_page_quote():
    assert quote(PRO_S, "24GB", "512GB", "柔光版").monthly == Decimal("833.25")  # 页面 833.25


# --- 拒绝估价 ---
def test_t14_delisted_model_refuses():
    q = quote("MateBook D 14")
    assert q.status == "no_price" and q.total is None


def test_t15_unknown_accessory_not_priced():
    q = quote(PRO_S, "16GB", "512GB", "标准", ["不存在的配件"])
    assert q.total == Decimal("7999.00")
    assert any("无公开金额" in w for w in q.warnings)


# --- 信息不全:追问,不猜 ---
def test_t16_series_only_asks_back():
    q = quote(PRO_S)
    assert q.status == "ambiguous" and len(q.options) == len(skus_for(PRO_S))


def test_t17_partial_info_still_ambiguous():
    """只给内存 24GB:Pro S 有多个 24GB 配置,必须追问。"""
    assert quote(PRO_S, "24GB").status == "ambiguous"


def test_t18_nonexistent_config_lists_options():
    q = quote(PRO_S, "8GB", "256GB", "标准")
    assert q.status == "ambiguous" and q.options


def test_t19_unknown_model():
    assert quote("不存在的型号").status == "not_found"


def test_t20_sku_not_cross_model():
    """Pro 与 Pro S 的 24GB/512GB 价格不同,不得串用。"""
    assert total(quote(PRO, "24GB", "512GB", "标准")) == Decimal("9999.00")
    assert total(quote(PRO_S, "24GB", "512GB", "标准")) == Decimal("8999.00")
