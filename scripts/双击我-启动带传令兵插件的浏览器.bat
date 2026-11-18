@echo off
chcp 65001 >nul
set "EXT_DIR=%~dp0..\browser-extension"
for %%I in ("%EXT_DIR%") do set "EXT_DIR=%%~fI"
powershell -NoProfile -Command "Set-Clipboard -Value '%EXT_DIR%'"
echo ============================================================
echo [AI Farm] 已将传令兵插件路径复制到剪贴板：
echo   %EXT_DIR%
echo 正在为你启动带传令兵扩展的浏览器...
echo （若浏览器提示“加载已解压的扩展程序”，直接按 Ctrl+V 回车即可！）
echo ============================================================
set "PROFILE_DIR=%USERPROFILE%\.ai-farm\browser-profile"
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --user-data-dir="%PROFILE_DIR%" --load-extension="%EXT_DIR%" "http://127.0.0.1:8765/"
) else (
    start "" "msedge.exe" --user-data-dir="%PROFILE_DIR%" --load-extension="%EXT_DIR%" "http://127.0.0.1:8765/"
)
