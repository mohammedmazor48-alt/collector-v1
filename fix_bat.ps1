$bat = "D:\openclaw\workspaces\think-tank\collector-v1\启动微信视频监听.bat"
$lines = @(
    "@echo off",
    "cd /d `"D:\openclaw\workspaces\think-tank\collector-v1`"",
    "python watch_wechat_video_downloads.py --watch-dir `"D:\Users\wechat\xwechat_files\wxid_e5xqonbbw6z322_b4f3\msg\video`"",
    "pause"
)
[System.IO.File]::WriteAllLines($bat, $lines, [System.Text.Encoding]::GetEncoding(936))
Write-Host "OK"
