$WshShell = New-Object -ComObject WScript.Shell
$Desktop = [Environment]::GetFolderPath('Desktop')
$lnkPath = Join-Path $Desktop "启动微信视频监听.lnk"
$batPath = "D:\openclaw\workspaces\think-tank\collector-v1\启动微信视频监听.bat"

# 删除旧的
if (Test-Path $lnkPath) { Remove-Item $lnkPath -Force }

$Shortcut = $WshShell.CreateShortcut($lnkPath)
$Shortcut.TargetPath = $batPath
$Shortcut.WorkingDirectory = "D:\openclaw\workspaces\think-tank\collector-v1"
$Shortcut.WindowStyle = 1
$Shortcut.Save()

# 验证
$Check = $WshShell.CreateShortcut($lnkPath)
Write-Host "Target:" $Check.TargetPath
Write-Host "WorkDir:" $Check.WorkingDirectory
