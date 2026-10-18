@echo off
chcp 65001 >nul
cd /d "%~dp0"
set NO_PROXY=127.0.0.1,localhost
set no_proxy=127.0.0.1,localhost
if not exist .venv (
  echo 首次运行,创建虚拟环境并安装依赖...
  python -m venv .venv
  .venv\Scripts\python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
)
echo 启动中,稍后请在浏览器打开 http://127.0.0.1:7860
.venv\Scripts\python app.py
echo.
echo 程序已退出。如有报错请截图。
pause
