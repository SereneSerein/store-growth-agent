"""资料缺失时的降级:不崩溃、打印中文警告、返回空数据、报价明确说明原因。

用子进程 + KB_ROOT 指向不存在的目录,避开 lru_cache 对同进程的影响。
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CODE = """
import sys
sys.path.insert(0, 'src')
from store_agent import knowledge as k, pricing as p
print('prices', len(k.load_prices()))
q = p.quote('HUAWEI MateBook Pro S')
print('status', q.status)
print('msg', q.message)
print('report_all_bad', all(not ok for ok, _ in k.data_report()))
"""


def test_missing_data_degrades_gracefully(tmp_path):
    r = subprocess.run(
        [sys.executable, "-c", CODE],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={"KB_ROOT": str(tmp_path / "nope"), "PYTHONIOENCODING": "utf-8", "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")},
    )
    out = r.stdout
    assert r.returncode == 0, r.stderr[-500:]
    assert "prices 0" in out
    assert "status no_price" in out
    assert "价格快照数据缺失" in out
    assert "report_all_bad True" in out
    assert "[警告]" in out  # 中文警告已打印
