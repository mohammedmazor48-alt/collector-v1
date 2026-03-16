@echo off
chcp 65001 >nul
cd /d "D:\openclaw\workspaces\think-tank\collector-v1"
python download_from_feishu_rpa.py --save-dir "D:\Downloads\wechatvideos"
pause
