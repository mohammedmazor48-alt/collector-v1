$WshShell = New-Object -ComObject WScript.Shell
$Desktop = [Environment]::GetFolderPath('Desktop')
$Shortcut = $WshShell.CreateShortcut("$Desktop\启动微信视频监听.lnk")
Write-Host "Target:" $Shortcut.TargetPath
Write-Host "WorkDir:" $Shortcut.WorkingDirectory
