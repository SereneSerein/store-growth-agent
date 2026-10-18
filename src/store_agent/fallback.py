"""兜底模板:没有大模型(无密钥/断网/报错)时,用事实包 + 需求信号确定性生成。

内容全部来自 facts.FactPack 与客户原话,不编造参数。
"""
from __future__ import annotations

import re

from .facts import FactPack
from .needs import Recommendation, Signals
from .pricing import Quote, fmt

# 需求标签 -> 优先引用的事实角度
TAG_ANGLE = {
    "便携": "便携续航接口卡", "续航": "便携续航接口卡", "投屏接口": "便携续航接口卡",
    "屏幕": "屏幕与显示卡", "隐私": "屏幕与显示卡", "反光": "屏幕与显示卡", "手写": "屏幕与显示卡",
    "视频创作": "性能与存储卡", "编程": "性能与存储卡", "办公文档": "性能与存储卡",
    "会议": "系统协同与兼容卡", "协同": "系统协同与兼容卡", "批量采购": "型号身份卡",
}

def _s(x: str) -> str:
    return x.rstrip("。；;，, ")


DIM_TITLES = [
    "核心任务与使用场景", "软件与兼容门槛", "便携、屏幕与使用环境",
    "协同、外设与接口", "预算、风险与决策阻力",
]


def _quote_ev(sig: Signals, *tags: str) -> str:
    for t in tags:
        if t in sig.evidence:
            return f"客户原话「…{sig.evidence[t]}…」"
    return ""


TAG_LABEL = {
    "便携": "便携", "续航": "续航", "屏幕": "屏幕观感", "隐私": "屏幕隐私", "反光": "强光/反光",
    "投屏接口": "投屏与接口", "视频创作": "剪辑与创作", "编程": "跑代码", "办公文档": "日常办公",
    "会议": "会议汇报", "协同": "多设备协同", "手写": "手写笔记", "批量采购": "团队采购",
}
# 客户担心 -> 在事实里找什么(正则)。匹配不到就如实说"资料里没有",不硬凑
TAG_FACT_RE = {
    "便携": r"\d\s*(kg|g)\b|轻", "续航": r"电池|Wh|续航|快充",
    "投屏接口": r"USB|DP|DisplayPort|HDMI|投屏|接口|扩展", "屏幕": r"OLED|分辨率|色域|亮度",
    "隐私": r"防窥|隐私", "反光": r"柔光|防眩|反光|眩光|亮度", "视频创作": r"内存|存储|处理器|OLED|色域",
    "编程": r"内存|存储|处理器", "办公文档": r"键盘|内存|存储|电池", "会议": r"摄像头|麦克风|投屏|降噪",
    "协同": r"协同|手机|平板|互传|超级终端", "手写": r"手写|M-Pen|笔|触控",
}
PRIORITY = ["隐私", "反光", "投屏接口", "续航", "视频创作", "编程", "便携", "屏幕", "会议", "手写", "协同", "办公文档"]
_DIM = re.compile(r"^(机身)?(宽|深|高)\s*[0-9]")  # 纯尺寸数字不是卖点


# 这些句子只是顺带带出版本名,不是在说明能力(重量/厚度/尺寸等),匹配能力类标签时排除
_NOT_ABILITY = re.compile(r"\d\s*(g|kg|mm)\b|厚|重量|\bWh\b")
_ABILITY_TAGS = {"隐私", "反光", "屏幕"}


def facts_for_tag(fp: FactPack, tag: str) -> list[tuple[str, str]]:
    rx = TAG_FACT_RE.get(tag)
    if not rx:
        return []
    pat = re.compile(rx)
    out = []
    for a, fs in fp.facts.items():
        for f in fs:
            if _DIM.match(f) or not pat.search(f):
                continue
            if tag in _ABILITY_TAGS and _NOT_ABILITY.search(f):
                continue
            out.append((a, f))
    return out


def relevant_facts(fp: FactPack, sig: Signals, n: int = 3) -> list[tuple[str, str, str]]:
    """按客户担心匹配事实,返回 [(标签, 角度, 事实)];每个担心先各取一条,再补第二条。"""
    tags = [t for t in PRIORITY if t in sig.tags]
    picked: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for _ in range(2):
        for t in tags:
            for a, f in facts_for_tag(fp, t):
                if f not in seen:
                    seen.add(f)
                    picked.append((t, a, f))
                    break
            if len(picked) >= n:
                return picked
    return picked


def limit_for(fp: FactPack, tag: str, fact: str) -> str:
    """找与该担心/事实最相关的一条表达边界;找不到返回空,不拿无关边界凑数。"""
    rx = TAG_FACT_RE.get(tag, "")
    keys = {"隐私": r"防窥|隐私|共享", "反光": r"柔光|亮度|反光|nits", "投屏接口": r"USB|DP|4K|接口|扩展|显示",
            "续航": r"电池|续航|Wh", "便携": r"重量|厚度|尺寸", "屏幕": r"屏幕|亮度|nits"}
    pat = keys.get(tag) or rx
    for lims in fp.limits.values():
        for lim in lims:
            if pat and re.search(pat, lim):
                return lim
    return ""


def missing_tags(fp: FactPack, sig: Signals) -> list[str]:
    """客户提到、但资料里找不到对应事实的担心(用于如实告知,不硬凑)。"""
    return [t for t in PRIORITY if t in sig.tags and t in TAG_FACT_RE and not facts_for_tag(fp, t)]


def pick_facts(fp: FactPack, sig: Signals, n: int = 3) -> list[tuple[str, str]]:
    got = [(a, f) for _, a, f in relevant_facts(fp, sig, max(n, 1) * 3)]
    return got or [("型号身份卡", f) for f in fp.facts.get("型号身份卡", []) if not _DIM.match(f)][: max(n, 1) * 3]


def _redline(fp: FactPack) -> str:
    for u in fp.unfit:
        if re.search(r"软件|应用|Windows|兼容|GPU", u):
            return _s(u)
    return _s(fp.unfit[0]) if fp.unfit else "以实机验证为准"


def insight_card(clue: str, channel: str, sig: Signals, fp: FactPack) -> str:
    tags = sig.tags
    L: list[str] = []
    used: set[str] = set()

    task_tags = [t for t in ("办公文档", "视频创作", "编程", "会议", "手写", "批量采购") if t in tags]
    L.append(f"**1. {DIM_TITLES[0]}**")
    L.append(f"- 主要任务:{'、'.join(TAG_LABEL[t] for t in task_tags) if task_tags else '待追问(线索中没有明确任务)'}。"
             f"依据:{_quote_ev(sig, *task_tags) or '线索中任务描述较少'}。")
    L.append(f"- 来源渠道:{channel},先回应处境再谈配置。依据:线索来自{channel}。")

    L.append(f"**2. {DIM_TITLES[1]}**")
    soft = [t for t in ("视频创作", "编程", "办公文档") if t in tags]
    if soft:
        L.append(f"- 涉及{'、'.join(TAG_LABEL[t] for t in soft)},需先确认所用软件及其对该机系统的支持,没确认前不承诺。"
                 f"依据:{_quote_ev(sig, *soft)};资料把「核心应用对系统的支持」列为销售前必须追问项。")
    else:
        L.append("- 待追问:常用软件、插件与文件格式。依据:线索未提及任何具体软件。")
    L.append(f"- 资料标注的不适合直接下结论情形:{_redline(fp)}。依据:产品资料「不适合直接下结论」。")

    L.append(f"**3. {DIM_TITLES[2]}**")
    env = [t for t in PRIORITY if t in tags and t in ("便携", "续航", "屏幕", "隐私", "反光")]
    if ("隐私" in env or "反光" in env) and "屏幕" in env:
        env.remove("屏幕")  # 隐私/反光已经是对屏幕的具体担心,不再泛泛列色域
    env = env[:3]
    if not env:
        L.append("- 待追问:是否每天携带、常用光线与桌面空间。依据:线索未提及。")
    for t in env:
        cands = [x for x in facts_for_tag(fp, t) if x[1] not in used]
        if cands:
            a, f = cands[0]
            used.add(f)
            L.append(f"- {TAG_LABEL[t]}:{_s(f)}。依据:{_quote_ev(sig, t)};产品资料「{a}」。")
        else:
            L.append(f"- {TAG_LABEL[t]}:资料中没有直接对应的事实,需现场验证,不替产品作承诺。依据:{_quote_ev(sig, t)}。")

    L.append(f"**4. {DIM_TITLES[3]}**")
    io = [t for t in PRIORITY if t in tags and t in ("投屏接口", "协同", "手写", "会议")]
    if io:
        L.append(f"- 需验证:{'、'.join(TAG_LABEL[t] for t in io)}。依据:{_quote_ev(sig, *io)}。")
        shown = 0
        for t in io:
            for a, f in facts_for_tag(fp, t):
                if f not in used and shown < 3:
                    used.add(f)
                    shown += 1
                    L.append(f"- 资料事实({TAG_LABEL[t]}):{_s(f)}。")
                    break
        lim = (fp.limits.get("便携续航接口卡") or [""])[0]
        if "投屏接口" in io and lim:
            L.append(f"- 资料中的表达边界:{_s(lim)}。必须让顾客带自己的投影/扩展坞现场试。")
    else:
        L.append("- 待追问:要接哪些外设(投影、U盘、打印机、手机、平板)。依据:线索未提及。")

    L.append(f"**5. {DIM_TITLES[4]}**")
    if sig.budget:
        kind = "上限" if sig.budget_is_cap else "约"
        L.append(f"- 预算{kind} {fmt(sig.budget)}。依据:客户原话中的预算表述。")
    elif "预算不敏感" in tags:
        L.append("- 客户表示预算不敏感,仍给三档并说明取舍,不默认推最高配。依据:客户原话「预算不太敏感」。")
    else:
        L.append("- 预算未说明,先给三档让顾客自己选,不替顾客定价格带。依据:线索无预算数字。")
    L.append("- 风险:价格、赠品、库存是动态信息,报价必须带核验时间并以结算页为准。")
    if "批量采购" in tags:
        L.append(f"- 决策阻力:批量采购通常有多人决策,先做单台试用再谈批量,不在门店承诺批量价。依据:{_quote_ev(sig, '批量采购')}。")

    L.append("")
    L.append(f"**客户真实处境**:{_situation(tags, sig.evidence, sig)}")
    L.append("**必须当面追问的 3 个问题**")
    for i, q in enumerate(_asks(tags, fp), 1):
        L.append(f"{i}. {q}")
    return "\n".join(L)


def _situation(tags: list[str], ev: dict[str, str], sig: Signals) -> str:
    if "批量采购" in tags:
        return "他不是在选一台电脑,而是在为团队的统一配置找一个不会被事后追责的方案,所以要先小范围验证、再扩大。"
    if "隐私" in tags:
        return "他真正怕的是在客户面前出现数据被看到或投屏失败的尴尬,屏幕参数反而是次要的。"
    if "反光" in tags or ("便携" in tags and "续航" in tags):
        return "他的工作场所不固定,最怕的是在外面「掉链子」:没电、没接口、屏幕看不清。"
    if "视频创作" in tags:
        return "他要的是能在外面把素材先粗剪出来的移动工作台,所以软件能否跑起来比参数更重要。"
    if "编程" in tags or "办公文档" in tags:
        return "他既要日常能背,又要关键时刻(答辩/交稿)不出问题,预算与课程/工作软件是两道硬门槛。"
    return "线索信息偏少,先通过提问确认任务、软件与使用环境,再决定推荐方向。"


def _asks(tags: list[str], fp: FactPack) -> list[str]:
    qs = []
    if any(t in tags for t in ("视频创作", "编程", "办公文档")):
        qs.append("你最常用的软件是哪几个?能否带一个真实工程/文件现场打开试一下?")
    if "投屏接口" in tags or "会议" in tags:
        qs.append("常见的投影/显示器接口是什么?自己带不带转接头或扩展坞?")
    if "便携" in tags:
        qs.append("每天是否携带?连同充电器和转接头,你能接受的总重量大概是多少?")
    if "隐私" in tags or "反光" in tags:
        qs.append("你更在意别人看不到屏幕(防窥),还是强光下看得清(柔光)?请二选一。")
    for ask in fp.must_ask:
        if len(qs) >= 3:
            break
        qs.append(ask.rstrip("。") + "?")
    return qs[:3]


# ---------------- 内容:朋友圈 / 视频切片 / 标题 ----------------
_PERSONA = {
    "批量采购": "要给团队统一配电脑的负责人", "隐私": "经常在客户面前做汇报的人",
    "反光": "常在咖啡馆、客户现场办公的人", "视频创作": "外出拍完想马上粗剪的创作者",
    "编程": "要写论文、跑代码的学生", "办公文档": "每天和文档、报表打交道的人",
}


def _persona(sig: Signals) -> str:
    if sig.persona:
        return sig.persona
    for t in sig.tags:
        if t in _PERSONA:
            return _PERSONA[t]
    return "正在选电脑的朋友"


def _scene_detail(sig: Signals) -> str:
    for t in ("反光", "隐私", "投屏接口", "便携", "续航", "视频创作", "编程", "批量采购"):
        d = sig.evidence.get(t, "")
        if d and "预算" not in d:
            return d
    return ""


def moments(sig: Signals, fp: FactPack, rec: Recommendation) -> str:
    facts = relevant_facts(fp, sig, 3)
    detail = _scene_detail(sig)
    if detail and len(detail) <= 16:
        lead = f"给{_persona(sig)}提个醒:如果你正为「{detail}」发愁,选电脑先看这几项。"
    else:
        lead = f"给{_persona(sig)}提个醒:选电脑先看这几项。"
    if facts:
        body = "\n".join(f"· 关于{TAG_LABEL[t]}:{_s(f)}" for t, _, f in facts)
        lims = [limit_for(fp, t, f) for t, _, f in facts]
        lim = next((x for x in lims if x), "")
    else:
        body = "· 具体参数请到店,我按你的使用场景逐项对照资料"
        lim = ""
    tail = (f"需要说明:{_s(lim)}。\n" if lim else "") + "把你的常用软件和使用场景发我,我按具体配置逐项帮你核对,价格以官方商城当日页面为准。"
    return f"{lead}\n{body}\n{tail}"


def video(sig: Signals, fp: FactPack, rec: Recommendation, product: str) -> str:
    detail = _scene_detail(sig) or "选电脑时最怕的那一刻"
    shots = [("1", f"镜头对准真实场景:{detail}", f"“{detail},你遇到过吗?”", "客户线索原话")]
    for i, (t, a, f) in enumerate(relevant_facts(fp, sig, 3), 2):
        shots.append((str(i), f"手持特写,让顾客亲手试:{TAG_LABEL[t]}", _s(f), f"事实包·{a}"))
    shots.append((str(len(shots) + 1), "店员递出设备:“带上你的文件,现场试”", "带上常用软件,现场验证兼容", "销售前必须追问"))
    lines = ["| 镜头 | 画面 | 旁白/字幕 | 依据 |", "|---|---|---|---|"]
    lines += [f"| {n} | {a} | {b} | {c} |" for n, a, b, c in shots]
    return "\n".join(lines)


def titles(sig: Signals, fp: FactPack, product: str) -> list[str]:
    detail = _scene_detail(sig)
    t1 = f"{detail},选电脑先看这三项" if detail and len(detail) <= 9 else "选电脑,先看这三项"
    t2 = f"{_persona(sig)}怎么选电脑"
    t3 = "到店试机前,先问清这3件事"
    return [t[:20] for t in (t1, t2, t3)]


# ---------------- 方案卡 + 演示脚本 ----------------
def proposal(sig: Signals, fp: FactPack, rec: Recommendation, q: Quote, product: str) -> str:
    L = ["### 方案卡"]
    pick = rec.balanced
    if pick is None:
        L.append("- 该型号当前没有可下单的商城页面价,无法给出配置档位,请店内询价后再推荐。")
    else:
        why = rec.reasons[0] if rec.reasons else "按客户线索中的任务与预算选取"
        L.append(f"- **推荐配置**:{product} {pick.label}({fmt(pick.price)}),理由:{why}。")
        if rec.base and rec.base is not pick:
            L.append(f"- 为什么不选保底档({rec.base.label} {fmt(rec.base.price)}):内存/存储更小,客户任务增长后余量少;若预算更紧可退到这一档。")
        if rec.advanced:
            L.append(f"- 为什么不直接上进阶档({rec.advanced.label} {fmt(rec.advanced.price)}):多出的预算要对应明确痛点才值得,先不主动推。")
    if fp.unfit:
        L.append(f"- **不适合的情况**:{_s(fp.unfit[1] if len(fp.unfit) > 1 else fp.unfit[0])}")
    L.append("- **成交前必须验证**:")
    for a in fp.must_ask[:4]:
        L.append(f"  - [ ] {a.rstrip('。')}")
    for n in rec.notes:
        L.append(f"- 注意:{n}")
    L.append("")
    L.append("### 3 分钟演示脚本")
    facts = pick_facts(fp, sig, 1)
    f1 = facts[0][1] if facts else "先介绍型号身份与版本"
    f2 = facts[1][1] if len(facts) > 1 else "再演示一个与客户任务相关的功能"
    L += [
        "| 时间 | 店员说 | 店员做(让顾客动手) | 依据 |",
        "|---|---|---|---|",
        f"| 0:00-0:30 | “先确认你最担心的是哪件事?” | 让顾客说出一个具体场景 | 洞察卡·追问 |",
        f"| 0:30-1:15 | “看这一项:{_s(f1)}” | 递上机器,让顾客自己看/摸 | 事实包 |",
        f"| 1:15-2:00 | “再看这项:{_s(f2)}” | 现场演示对应功能 | 事实包 |",
        "| 2:00-2:30 | “任何一项过不了,我们就换方案,不靠形容词成交。” | 请顾客带自己的软件/文件试 | 门店沟通卡 |",
        "| 2:30-3:00 | “这是当前配置的官方页面价,以结算页为准。” | 出示报价表,确认配置与赠品 | 报价 |",
    ]
    return "\n".join(L)


# ---------------- 成交推进 ----------------
def followup(sig: Signals, rec: Recommendation, q: Quote, product: str) -> str:
    pick = rec.balanced.label if rec.balanced else "已沟通的配置"
    detail = _scene_detail(sig)
    topic = f"「{detail}」" if detail else "你提到的使用场景"
    return f"""### 现在就做(下一步)
- **说什么**:“我先把 {product} {pick} 的配置和核验时间发你。你方便哪天带上常用软件来现场试一下{topic}?”
- **什么时候**:顾客咨询后 30 分钟内发出。
- **看什么信号**:顾客是否给出到店时间、是否提供了软件清单;给了就进入预约试机。

### 1 / 3 / 7 天跟进
| 时间 | 目的 | 可直接复制的话 | 对方回应后怎么走 |
|---|---|---|---|
| 1 天后 | 确认与验证 | “昨天说的{topic},你的软件清单方便发我吗?我提前帮你核对能不能用。” | 发了清单→核对后给结论;没回→3 天再跟 |
| 3 天后 | 解决顾虑 | “我把{product}几项取舍整理成一页:适合谁、不适合谁、要现场验证什么。你对比一下。” | 提出价格顾虑→给保底档和分期口径(以结算页为准);提出兼容→约现场试机 |
| 7 天后 | 给决策理由,不催单 | “这周官方页面的配置/赠品可能有变化,我按今天的页面重新核对了一遍报价,发你看看。需要的话我帮你预约试机。” | 仍犹豫→问卡点在哪;无回应→标记观望,下月再轻触达一次 |

### 常见异议
- **再看看**:“可以。你比较时只看三项:你的软件能不能跑、接口够不够用、总重量能不能接受。哪一项还没把握,我们现场验证。”
- **太贵了**:“我们可以退到保底档或看分期口径,先保证你最在意的那一项。具体以结算页为准。”
- **怕不兼容**:“不靠承诺,靠验证:你带上软件和外设,我们现场试,过不了就换方案。”
"""
