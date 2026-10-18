"""全量测试:所有 场景卡 x 产品 组合各跑一遍,统计成功/失败/耗时;再模拟断网和模型接口报错。

用法: python scripts/run_all.py
要求: 0 次中断(每个组合都必须返回各区非空结果)。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from store_agent import llm, pipeline  # noqa: E402
from store_agent.knowledge import product_names  # noqa: E402

SCENES = json.loads((ROOT / "config" / "scenes.json").read_text(encoding="utf-8"))["scenes"]
SECTIONS = ("insight", "moments", "video", "quote_md", "proposal", "followup")


def run_one(scene: dict, product: str):
    t0 = time.time()
    res = pipeline.run(scene["clue"], scene["channel"], product, scene["scene_dir"])
    empty = [s for s in SECTIONS if not str(getattr(res, s)).strip()] + ([] if res.titles else ["titles"])
    return res, empty, time.time() - t0


def sweep(label: str) -> int:
    bad, n, t_all = [], 0, 0.0
    for sc in SCENES:
        for p in product_names():
            n += 1
            try:
                res, empty, dt = run_one(sc, p)
            except Exception as e:  # noqa: BLE001 - 任何异常都算一次"中断"
                bad.append((sc["name"], p, f"抛出异常 {type(e).__name__}: {e}"))
                continue
            t_all += dt
            if empty or not res.ok:
                bad.append((sc["name"], p, f"空白区={empty} ok={res.ok}"))
    print(f"[{label}] 组合 {n} | 成功 {n - len(bad)} | 失败 {len(bad)} | 总耗时 {t_all:.2f}s | 平均 {t_all / n:.3f}s")
    for b in bad:
        print("   失败:", b)
    return len(bad)


def main() -> int:
    fails = 0
    os.environ["FORCE_OFFLINE"] = "1"
    fails += sweep("离线(无密钥)")

    # 模拟断网: 有密钥但地址不可达,验证重试一次后走兜底
    os.environ.pop("FORCE_OFFLINE", None)
    os.environ["LLM_API_KEY"] = "test-offline-key"
    os.environ["LLM_BASE_URL"] = "http://127.0.0.1:9"  # 本机无服务,等价于断网
    os.environ["LLM_TIMEOUT"] = "2"
    llm.TIMEOUT = 2
    sc = SCENES[0]
    t0 = time.time()
    res, empty, _ = run_one(sc, "HUAWEI MateBook Pro S")
    print(f"[断网模拟] 耗时 {time.time() - t0:.1f}s | 空白区={empty} | ok={res.ok} | 生成方式={res.modes}")
    fails += 1 if (empty or not res.ok) else 0
    print("   兜底记录:", [t for t in res.trace if "改用兜底" in t][:2])

    # 模拟模型接口报错: 本地起一个返回 500 的服务
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b'{"error":"boom"}')

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    os.environ["LLM_BASE_URL"] = f"http://127.0.0.1:{srv.server_port}"
    llm.reset_breaker()
    res, empty, _ = run_one(SCENES[3], "HUAWEI MateBook Pro S")
    print(f"[接口500模拟] 空白区={empty} | ok={res.ok} | 生成方式={res.modes}")
    fails += 1 if (empty or not res.ok) else 0
    srv.shutdown()

    print("\n结论:", "全部通过,0 次中断" if fails == 0 else f"存在 {fails} 项失败")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
