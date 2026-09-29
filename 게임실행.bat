@echo off
chcp 65001 >nul
title 한반도 시군구 문명
cd /d "%~dp0"

rem ---- 1. Python 찾기
set "PY="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY goto have_python
python --version >nul 2>&1
if not errorlevel 1 set "PY=python"
if defined PY goto have_python
call :find_installed
if defined PY goto have_python

rem ---- 2. 없으면 자동 설치 (Windows 10/11 winget)
echo Python이 설치되어 있지 않아 자동으로 설치합니다. 잠시 기다려 주세요...
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
call :find_installed
if defined PY goto have_python
echo.
echo [오류] Python을 자동으로 설치하지 못했습니다.
echo https://www.python.org/downloads/ 에서 직접 설치하세요.
echo 설치 첫 화면 아래의 "Add python.exe to PATH"를 꼭 체크한 뒤, 이 파일을 다시 더블클릭하세요.
pause
exit /b 1

:have_python
rem ---- 3. 처음 한 번: 필요한 부품 설치
%PY% -c "import pygame, numpy" >nul 2>&1
if not errorlevel 1 goto run_game
echo 처음 실행이라 필요한 부품 pygame, numpy 를 설치합니다. 1~2분 걸릴 수 있습니다...
%PY% -m pip install --user -r requirements.txt
%PY% -c "import pygame, numpy" >nul 2>&1
if not errorlevel 1 goto run_game
echo pygame 설치에 실패해 호환 버전 pygame-ce 로 다시 시도합니다...
%PY% -m pip install --user pygame-ce numpy
%PY% -c "import pygame, numpy" >nul 2>&1
if not errorlevel 1 goto run_game
echo.
echo [오류] 부품 설치에 실패했습니다. 이 창의 내용을 캡처해 보내 주세요.
pause
exit /b 1

:run_game
rem ---- 4. 게임 실행
echo 게임을 시작합니다...
%PY% -m korciv
if errorlevel 1 goto crashed
exit /b 0

:crashed
echo.
echo [오류] 게임이 비정상 종료되었습니다. 이 창의 내용을 캡처해 보내 주세요.
pause
exit /b 1

:find_installed
for %%V in (314 313 312 311 310) do (
  if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
  if not defined PY if exist "%ProgramFiles%\Python%%V\python.exe" set PY="%ProgramFiles%\Python%%V\python.exe"
)
exit /b 0
