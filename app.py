"""门店增长智能体 - Gradio 界面入口。运行: python app.py (或双击 start.bat)"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import os

# 本机地址不走系统代理,否则 Gradio 启动自检会被代理拦成 502 而闪退
for _k in ("NO_PROXY", "no_proxy"):
    os.environ[_k] = ",".join(filter(None, [os.environ.get(_k, ""), "127.0.0.1", "localhost", "::1"]))

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

import gradio as gr  # noqa: E402

from store_agent import llm, pipeline  # noqa: E402
from store_agent.knowledge import product_names  # noqa: E402
from store_agent.pricing import accessory_names, sku_labels  # noqa: E402

SCENES = json.loads((ROOT / "config" / "scenes.json").read_text(encoding="utf-8"))["scenes"]
SCENE_BY_NAME = {s["name"]: s for s in SCENES}
AUTO = "自动推荐(按线索选配置)"
SCRIPT_HEAD = re.compile(r"^#{1,4}\s*(?:3\s*分钟)?演示脚本.*$", re.M)


def on_scene(name: str):
    s = SCENE_BY_NAME[name]
    return s["clue"], s["channel"], s["default_product"]


def on_product(product: str):
    labels = sku_labels(product)
    return gr.update(choices=[AUTO] + labels, value=AUTO)


def _split_proposal(text: str) -> tuple[str, str]:
    m = SCRIPT_HEAD.search(text)
    if not m:
        return text, "（演示脚本已包含在「方案卡」中）"
    return text[: m.start()].strip(), text[m.start():].strip()


def _parse_label(label: str) -> tuple[str, str, str]:
    """'24GB/512GB/柔光版' -> ('24GB','512GB','柔光版');无屏幕后缀视为标准屏。"""
    parts = label.split("/")
    screen = parts[2] if len(parts) > 2 else "标准"
    return parts[0], parts[1], screen


def generate(scene_name, clue, channel, product, sku_label, accessories):
    """点一次按钮,跑完整条链路,分区返回结果。任何异常都不会让界面报错。"""
    mem = sto = scr = ""
    if sku_label and sku_label != AUTO:
        mem, sto, scr = _parse_label(sku_label)
    res = pipeline.run(
        clue=clue, channel=channel, product=product,
        scene=SCENE_BY_NAME.get(scene_name, {}).get("scene_dir"),
        memory=mem, storage=sto, screen=scr, accessories=accessories or [],
    )
    content = "### 朋友圈文案\n" + res.moments + "\n\n### 视频切片分镜\n" + res.video
    content += "\n\n### 标题备选\n" + "\n".join(f"{i}. {t}" for i, t in enumerate(res.titles, 1))
    proposal, script = _split_proposal(res.proposal)
    mode = "、".join(f"{k}:{'大模型' if v == 'llm' else '兜底模板'}" for k, v in res.modes.items())
    log = [f"链路状态:{'全部完成' if res.ok else '有步骤降级,请人工补充'}", f"生成方式:{mode}",
           f"耗时(秒):{res.seconds}"]
    log += res.compliance_notes + res.trace
    return res.insight, content, res.quote_md + "\n\n" + proposal, script, res.followup, "\n".join(log)


def build_ui() -> gr.Blocks:
    first = SCENES[0]
    with gr.Blocks(title="门店增长智能体") as demo:
        gr.Markdown(
            "# 门店增长智能体\n读懂客户 → 写出内容 → 给出方案 → 推到成交。"
            f"当前模式:{'大模型 + 兜底模板' if llm.available() else '离线(兜底模板)'}"
        )
        with gr.Row():
            with gr.Column(scale=1):
                scene = gr.Dropdown([s["name"] for s in SCENES], value=first["name"], label="场景卡")
                clue = gr.Textbox(first["clue"], label="客户线索(可直接改)", lines=5)
                channel = gr.Textbox(first["channel"], label="渠道")
                product = gr.Dropdown(product_names(), value=first["default_product"], label="产品")
                sku = gr.Dropdown([AUTO] + sku_labels(first["default_product"]), value=AUTO, label="配置(可选)")
                acc = gr.CheckboxGroup(accessory_names(), label="配件(按单买价计入)")
                btn = gr.Button("一键生成", variant="primary")
            with gr.Column(scale=2):
                with gr.Tabs():
                    with gr.Tab("① 洞察卡"):
                        o1 = gr.Markdown()
                    with gr.Tab("② 内容"):
                        o2 = gr.Markdown()
                    with gr.Tab("③ 报价与方案"):
                        o3 = gr.Markdown()
                    with gr.Tab("④ 3分钟演示脚本"):
                        o4 = gr.Markdown()
                    with gr.Tab("⑤ 1/3/7天跟进"):
                        o5 = gr.Markdown()
                    with gr.Tab("运行日志"):
                        o6 = gr.Textbox(lines=14, show_label=False)
        scene.change(on_scene, scene, [clue, channel, product])
        product.change(on_product, product, sku)
        btn.click(generate, [scene, clue, channel, product, sku, acc], [o1, o2, o3, o4, o5, o6])
    return demo


if __name__ == "__main__":
    build_ui().launch(server_name="127.0.0.1", server_port=7860, theme=gr.themes.Soft())
