@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv (
  echo 首次运行,创建虚拟环境并安装依赖...
  python -m venv .venv
  .venv\Scripts\python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
)
.venv\Scripts\python app.py
