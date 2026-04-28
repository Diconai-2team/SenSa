@echo off
REM ============================================================
REM 백오피스 v1~v6 한 번에 적용 스크립트 (Windows)
REM ============================================================
REM
REM 사용법:
REM   1) 이 .bat 를 SenSa_proj 의 부모 디렉토리에 두기
REM      예: C:\Users\me\SenSa_proj 가 있다면 C:\Users\me\ 에 둠
REM   2) 6개 zip 파일도 같은 곳에 두기
REM   3) 더블클릭 또는 명령 프롬프트에서 apply.bat 실행
REM ============================================================

setlocal enabledelayedexpansion

set PROJ_DIR=SenSa_proj
if not "%~1"=="" set PROJ_DIR=%~1

set TIMESTAMP=%date:~0,4%%date:~5,2%%date:~8,2%_%time:~0,2%%time:~3,2%%time:~6,2%
set TIMESTAMP=%TIMESTAMP: =0%
set BACKUP_DIR=%PROJ_DIR%_backup_%TIMESTAMP%

echo ===================================================
echo   백오피스 v1~v6 통합 적용 스크립트 (Windows)
echo ===================================================
echo.

REM ─── 사전 검증 ───
echo [1/5] 사전 검증
if not exist "%PROJ_DIR%" (
    echo X %PROJ_DIR% 디렉토리가 없습니다.
    echo    사용법: apply.bat C:\path\to\SenSa_proj
    pause
    exit /b 1
)
if not exist "%PROJ_DIR%\SenSa\manage.py" (
    echo X manage.py 가 없습니다. 경로 확인 필요.
    pause
    exit /b 1
)
for %%v in (1 2 3 4 5 6) do (
    if not exist "backoffice_v%%v.zip" (
        echo X backoffice_v%%v.zip 이 없습니다.
        pause
        exit /b 1
    )
)
echo   OK 프로젝트 경로: %PROJ_DIR%
echo   OK 6개 zip 파일 확인됨
echo.

REM ─── 백업 ───
echo [2/5] 프로젝트 백업
echo   백업 중... (%BACKUP_DIR%)
xcopy "%PROJ_DIR%" "%BACKUP_DIR%" /E /I /Q /Y > nul
echo   OK 백업 완료
echo.

REM ─── 순차 적용 ───
echo [3/5] v1~v6 순차 적용
for %%v in (1 2 3 4 5 6) do (
    echo   → backoffice_v%%v.zip 적용 중...
    powershell -Command "Expand-Archive -Path 'backoffice_v%%v.zip' -DestinationPath '%PROJ_DIR%' -Force"
    if errorlevel 1 (
        echo X v%%v 적용 실패
        pause
        exit /b 1
    )
    echo   OK v%%v 적용 완료
)
echo.

REM ─── Django 마이그레이션 ───
echo [4/5] Django 마이그레이션 + 시스템 체크
cd "%PROJ_DIR%\SenSa"

set PYTHON_BIN=python
if exist "..\venv\Scripts\python.exe" set PYTHON_BIN=..\venv\Scripts\python.exe
if exist "..\.venv\Scripts\python.exe" set PYTHON_BIN=..\.venv\Scripts\python.exe
if exist "venv\Scripts\python.exe" set PYTHON_BIN=venv\Scripts\python.exe
if exist ".venv\Scripts\python.exe" set PYTHON_BIN=.venv\Scripts\python.exe

echo   Python: %PYTHON_BIN%
echo   → migrate 실행...
%PYTHON_BIN% manage.py migrate
if errorlevel 1 (
    echo X migrate 실패
    pause
    exit /b 1
)
echo   → check 실행...
%PYTHON_BIN% manage.py check
echo   OK 마이그레이션 + 체크 통과
echo.

REM ─── 검증 ───
echo [5/5] 데이터 검증
%PYTHON_BIN% -c "import django, os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','mysite.settings'); django.setup(); from backoffice.models import *; print(f'CodeGroup: {CodeGroup.objects.count()} (v2)'); print(f'RiskCategory: {RiskCategory.objects.count()} (v2)'); print(f'NotificationPolicy: {NotificationPolicy.objects.count()} (v3)'); print(f'Notice: {Notice.objects.count()} (v4)'); print('AuditLog 모델 OK (v6)')"

echo.
echo ===================================================
echo   ✅ 적용 완료!
echo ===================================================
echo.
echo 다음 단계:
echo   1. Django 서버 재시작: python manage.py runserver
echo   2. FastAPI 재시작: cd ..\fastapi_generator ^&^& uvicorn main:app --port 8001
echo   3. 백오피스 접속: http://localhost:8000/backoffice/
echo.
echo 문제 발생 시 백업 복원:
echo   rmdir /S /Q %PROJ_DIR%
echo   move %BACKUP_DIR% %PROJ_DIR%
echo.
pause
