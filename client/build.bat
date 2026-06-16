@echo off
setlocal
cd /d "%~dp0"
python -m venv .venv-build 2>nul
call .venv-build\Scripts\activate.bat
pip install -r requirements.txt
pyinstaller build.spec --noconfirm
if exist dist\DayZMapClient.exe (
  echo Built: %cd%\dist\DayZMapClient.exe
) else (
  exit /b 1
)
