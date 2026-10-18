@echo off
cd /d "%~dp0"
set NO_PROXY=127.0.0.1,localhost
set no_proxy=127.0.0.1,localhost
set PYTHONIOENCODING=utf-8
if not exist .venv\Scripts\python.exe (
  echo First run: creating venv and installing packages, please wait...
  python -m venv .venv
  .venv\Scripts\python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
)
echo Starting... open http://127.0.0.1:7860 in your browser
.venv\Scripts\python app.py
echo.
echo Program exited. If there is an error above, take a screenshot.
pause
