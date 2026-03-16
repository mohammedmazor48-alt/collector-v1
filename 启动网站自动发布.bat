@echo off
chcp 65001 >nul
powershell -ExecutionPolicy Bypass -File "D:\openclaw\workspaces\think-tank\collector-v1\auto_publish_site.ps1"
pause
