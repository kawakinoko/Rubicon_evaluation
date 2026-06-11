@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
set "PAYLOAD_ZIP=%SCRIPT_DIR%rubicon-evaluation-payload.zip"
set "TARGET_PARENT=%~1"
if "%TARGET_PARENT%"=="" set "TARGET_PARENT=%CD%\bundle-output"
set "BRANCH_NAME=%~2"
if "%BRANCH_NAME%"=="" set "BRANCH_NAME=import/rubicon-bundle"
set "REMOTE_URL=%~3"
set "REPO_DIR=%TARGET_PARENT%\Rubicon_evaluation"

if not exist "%PAYLOAD_ZIP%" (
    echo Payload zip not found: %PAYLOAD_ZIP%
    exit /b 1
)

where git >nul 2>nul
if errorlevel 1 (
    echo git is required but not installed.
    exit /b 1
)

if not exist "%TARGET_PARENT%" mkdir "%TARGET_PARENT%"

powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%PAYLOAD_ZIP%' -DestinationPath '%TARGET_PARENT%' -Force"
if errorlevel 1 exit /b 1

if not exist "%REPO_DIR%" (
    echo Expected repo directory was not created: %REPO_DIR%
    exit /b 1
)

pushd "%REPO_DIR%"

if not exist ".git" (
    git init -b main >nul
)

git checkout -B "%BRANCH_NAME%" >nul
if errorlevel 1 (
    popd
    exit /b 1
)

git config user.name >nul 2>nul
if errorlevel 1 git config user.name "Rubicon Bundle"
git config user.email >nul 2>nul
if errorlevel 1 git config user.email "bundle@local.invalid"

if not "%REMOTE_URL%"=="" (
    git remote get-url origin >nul 2>nul
    if errorlevel 1 (
        git remote add origin "%REMOTE_URL%"
    ) else (
        git remote set-url origin "%REMOTE_URL%"
    )
)

git add .
git status --short | findstr . >nul
if not errorlevel 1 (
    git commit -m "Import Rubicon evaluation bundle" >nul
)

popd

echo Bundle restored to %REPO_DIR%
echo Active branch: %BRANCH_NAME%
if not "%REMOTE_URL%"=="" echo Remote origin: %REMOTE_URL%
echo Next: cd /d "%REPO_DIR%" ^&^& git push -u origin "%BRANCH_NAME%"