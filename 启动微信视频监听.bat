@echo off
chcp 65001 >nul
cd /d "D:\openclaw\workspaces\think-tank\collector-v1"
python watch_wechat_video_downloads.py --watch-dir "D:\Downloads\wechatvideos"
pause
