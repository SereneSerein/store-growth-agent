"""主流水线:洞察卡 → 内容 → 价格方案 → 演示脚本 → 跟进计划。

设计原则:
- 价格由 pricing.py 纯代码计算,大模型只写文字;
- 每一步:先试大模型(失败自动重试一次),仍失败则用兜底模板;
- 任何异常都被捕获并记录到 trace,整条链路绝不抛出。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from . import compliance, fallback, llm
from .facts import FactPack, build as build_facts
from .knowledge import load_scene
from .needs import Recommendation, Signals, extract, recommend
from .pricing import Quote, fmt, quote, render_quote

PROMPTS = Path(__file__).resolve().parents[2] / "prompts"


@dataclass
class Result:
    insight: str = ""
    moments: str = ""
    video: str = ""
    titles: list[str] = field(default_factory=list)
    quote_md: str = ""
    proposal: str = ""
    followup: str = ""
    trace: list[str] = field(default_factory=list)
    modes: dict[str, str] = field(default_factory=dict)  # 步骤 -> llm / fallback
    compliance_notes: list[str] = field(default_factory=list)
    seconds: dict[str, float] = field(default_factory=dict)
    ok: bool = True


def _prompt(name: str, **kw: str) -> str:
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8").format(**kw)


def _system() -> str:
    return (PROMPTS / "_system.md").read_text(encoding="utf-8")


def _quote_brief(q: Quote) -> str:
    if q.status != "ok":
        return q.message
    return "；".join(f"{ln.name} {fmt(ln.amount)}" for ln in q.lines if ln.amount is not None and ln.level != "L4 分期") + f"；合计 {fmt(q.total)}（以结算页为准）"


def _proposal_brief(rec: Recommendation, q: Quote) -> str:
    pick = rec.balanced.label if rec.balanced else "待确认"
    return f"主推配置:{pick};{_quote_brief(q)}"


def _run_step(res: Result, name: str, llm_fn, fb_fn):
    """执行一步:大模型(含重试) -> 兜底。返回文本,永不抛出。"""
    t0 = time.time()
    text = None
    if llm.available():
        try:
            text = llm_fn()
            res.modes[name] = "llm"
        except Exception as e:  # noqa: BLE001
            res.trace.append(f"[{name}] 大模型失败,改用兜底模板: {type(e).__name__}: {e}")
    if text is None:
        try:
            text = fb_fn()
        except Exception as e:  # noqa: BLE001 - 兜底也失败时返回提示,链路继续
            res.trace.append(f"[{name}] 兜底模板异常: {type(e).__name__}: {e}")
            text = f"（{name}暂时无法生成,请人工补充）"
            res.ok = False
        res.modes[name] = "fallback"
    res.seconds[name] = round(time.time() - t0, 2)
    cleaned, hits = compliance.sanitize(text)
    if hits:
        res.compliance_notes += [f"[{name}] 命中「{h.word}」:{h.reason} → 已改写" for h in hits]
    return cleaned


def run(
    clue: str,
    channel: str,
    product: str,
    scene: str | None = None,
    memory: str = "",
    storage: str = "",
    screen: str = "",
    accessories: list[str] | None = None,
) -> Result:
    res = Result()
    try:
        _run(res, clue, channel, product, scene, memory, storage, screen, accessories or [])
    except Exception as e:  # noqa: BLE001 - 最后一道防线
        res.trace.append(f"流水线异常已捕获: {type(e).__name__}: {e}")
        res.ok = False
    return res


def _split_content(text: str) -> tuple[str, str, list[str]]:
    """把大模型的 ===朋友圈=== / ===视频切片=== / ===标题=== 三段拆开。"""
    parts: dict[str, str] = {}
    cur = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("===") and s.endswith("==="):
            cur = s.strip("= ")
            parts[cur] = ""
        elif cur:
            parts[cur] += line + "\n"
    if not all(k in parts and parts[k].strip() for k in ("朋友圈", "视频切片", "标题")):
        raise ValueError("模型输出缺少必需分段")
    titles = [t.strip(" -·0123456789.、") for t in parts["标题"].strip().splitlines() if t.strip()]
    return parts["朋友圈"].strip(), parts["视频切片"].strip(), titles[:3]


def _run(res, clue, channel, product, scene, memory, storage, screen, accessories):
    t_all = time.time()
    # 1 信号与事实 ------------------------------------------------
    sig: Signals = extract(clue)
    fp: FactPack = build_facts(product)
    scene_profile = ""
    if scene:
        try:
            scene_profile = load_scene(scene)["客户画像"][:1200]
        except Exception as e:  # noqa: BLE001
            res.trace.append(f"场景画像读取失败,忽略: {e}")
    rec = recommend(product, sig)
    res.trace.append(f"信号={sig.tags} 预算={sig.budget} 主推={(rec.balanced.label if rec.balanced else None)}")

    # 价格:先用客户指定配置,没指定则用主推配置;全程纯代码 ----------
    use = (memory, storage, screen)
    if not any(use) and rec.balanced is not None:
        use = (rec.balanced.memory, rec.balanced.storage, "" if rec.balanced.screen == "标准" else rec.balanced.screen)
        if rec.balanced.screen == "标准":
            # 标准屏 SKU:需限定为无屏幕后缀的那一条,quote() 的 screen 过滤用显式值
            use = (rec.balanced.memory, rec.balanced.storage, "标准")
    try:
        q = quote(product, use[0], use[1], use[2], accessories)
    except Exception as e:  # noqa: BLE001
        q = Quote(status="no_price", product=product, message=f"价格计算失败:{e},请店内人工核价")
        res.trace.append(f"价格引擎异常: {e}")
    res.trace += [f"[价格] {t}" for t in q.trace]
    res.quote_md = render_quote(q)

    facts_txt = fp.as_text(4)
    sys_prompt = _system()

    # 2 洞察卡 ----------------------------------------------------
    res.insight = _run_step(
        res, "洞察卡",
        lambda: llm.chat(sys_prompt, _prompt("insight", clue=clue, channel=channel,
                                             scene_profile=scene_profile or "（无）", product_facts=facts_txt)),
        lambda: fallback.insight_card(clue, channel, sig, fp),
    )

    # 3 内容 ------------------------------------------------------
    def content_llm():
        out = llm.chat(sys_prompt, _prompt("content", clue=clue, insight=res.insight,
                                           product_facts=facts_txt, quote_brief=_quote_brief(q)), temperature=0.7)
        return out

    t0 = time.time()
    raw_mode = "fallback"
    try:
        if llm.available():
            m, v, t = _split_content(content_llm())
            raw_mode = "llm"
        else:
            raise llm.LLMUnavailable("离线")
    except Exception as e:  # noqa: BLE001
        if llm.available():
            res.trace.append(f"[内容] 大模型失败,改用兜底模板: {type(e).__name__}: {e}")
        try:
            m, v, t = fallback.moments(sig, fp, rec), fallback.video(sig, fp, rec, product), fallback.titles(sig, fp, product)
        except Exception as e2:  # noqa: BLE001
            res.trace.append(f"[内容] 兜底异常: {e2}")
            m, v, t, res.ok = "（朋友圈文案暂时无法生成,请人工补充）", "（暂缺）", ["（暂缺）"], False
    res.modes["内容"] = raw_mode
    res.seconds["内容"] = round(time.time() - t0, 2)
    res.moments, hits_m = compliance.sanitize(m)
    res.video, hits_v = compliance.sanitize(v)
    res.titles = []
    for title in t:
        c, h = compliance.sanitize(title)
        res.titles.append(c[:20] if len(c) > 20 else c)
        hits_m += h
    res.compliance_notes += [f"[内容] 命中「{h.word}」:{h.reason} → 已改写" for h in hits_m + hits_v]

    # 4 方案 + 演示脚本 ------------------------------------------
    res.proposal = _run_step(
        res, "方案与演示脚本",
        lambda: llm.chat(sys_prompt, _prompt("proposal", clue=clue, insight=res.insight,
                                             product_facts=facts_txt, quote_md=res.quote_md)),
        lambda: fallback.proposal(sig, fp, rec, q, product),
    )

    # 5 跟进 ------------------------------------------------------
    res.followup = _run_step(
        res, "跟进计划",
        lambda: llm.chat(sys_prompt, _prompt("followup", clue=clue, insight=res.insight,
                                             proposal_brief=_proposal_brief(rec, q))),
        lambda: fallback.followup(sig, rec, q, product),
    )
    res.seconds["总计"] = round(time.time() - t_all, 2)
