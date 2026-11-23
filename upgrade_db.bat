@echo off
REM Applies the database migrations (step 1: security fixes, step 2: scan_history.page for PDF, step 3: API tokens,
REM step 4: request outcome columns for the admin statistics, step 5: audit log and key rotation)
cd /d "%~dp0"
call venv\Scripts\activate.bat
echo Current database revision:
flask --app run db current
echo.
echo Upgrading...
flask --app run db upgrade
echo.
echo New database revision (should be e8c2f6a41b7d):
flask --app run db current
echo.
pause
