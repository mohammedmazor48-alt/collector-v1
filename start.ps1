param(
    [ValidateSet('help','shell','doctor','doctor-live','bootstrap','bootstrap-live','summary-check','stats','list','duplicates','search','ingest-remote','ingest-baidu-video','ingest-video-page','watch-wechat')]
    [string]$Action = 'help',

    [string]$Url = '',
    [string]$Query = '',
    [string]$Tags = '',
    [string]$Title = '',
    [string]$NotifyFile = '',
    [string]$NotifyWebhook = '',
    [string]$WatchDir = 'C:\Users\darkblue\Videos\WeChat Files',
    [switch]$ExportSite,
    [switch]$PublishSite,
    [switch]$Force
)

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path $Python)) {
    Write-Host '未找到项目虚拟环境：' $Python -ForegroundColor Red
    Write-Host '请先确认项目已正确部署。' -ForegroundColor Yellow
    exit 1
}

Set-Location $ProjectRoot

function Show-Help {
    Write-Host 'collector-v1 启动脚本' -ForegroundColor Cyan
    Write-Host '项目位置：' $ProjectRoot
    Write-Host ''
    Write-Host '常用用法：' -ForegroundColor Yellow
    Write-Host '  powershell -ExecutionPolicy Bypass -File .\start.ps1 shell'
    Write-Host '  powershell -ExecutionPolicy Bypass -File .\start.ps1 doctor'
    Write-Host '  powershell -ExecutionPolicy Bypass -File .\start.ps1 doctor-live'
    Write-Host '  powershell -ExecutionPolicy Bypass -File .\start.ps1 bootstrap'
    Write-Host '  powershell -ExecutionPolicy Bypass -File .\start.ps1 bootstrap-live'
    Write-Host '  powershell -ExecutionPolicy Bypass -File .\start.ps1 summary-check'
    Write-Host '  powershell -ExecutionPolicy Bypass -File .\start.ps1 stats'
    Write-Host '  powershell -ExecutionPolicy Bypass -File .\start.ps1 list'
    Write-Host '  powershell -ExecutionPolicy Bypass -File .\start.ps1 duplicates'
    Write-Host '  powershell -ExecutionPolicy Bypass -File .\start.ps1 search -Query "毛选"'
    Write-Host '  powershell -ExecutionPolicy Bypass -File .\start.ps1 ingest-remote -Url "https://example.com/file.mp4" -Tags "远程导入,视频"'
    Write-Host '  powershell -ExecutionPolicy Bypass -File .\start.ps1 ingest-baidu-video -Url "https://mbd.baidu.com/newspage/data/videolanding?nid=..." -Tags "百度,视频,转写"'
    Write-Host '  powershell -ExecutionPolicy Bypass -File .\start.ps1 ingest-video-page -Url "https://example.com/video-landing-page" -Tags "视频页,转写" -NotifyFile ".\knowledge-vault\logs\video-status.json"'
    Write-Host ''
    Write-Host '说明：' -ForegroundColor Yellow
    Write-Host '  shell          进入项目目录并打开一个可直接使用的 PowerShell'
    Write-Host '  doctor         环境体检'
    Write-Host '  doctor-live    环境体检 + 摘要后端连通测试'
    Write-Host '  bootstrap      初始化 + 体检'
    Write-Host '  bootstrap-live 初始化 + 体检 + 摘要后端连通测试'
    Write-Host '  summary-check  检查摘要后端配置'
    Write-Host '  stats          查看资料库统计'
    Write-Host '  list           查看最近文档'
    Write-Host '  duplicates     查看重复关系'
    Write-Host '  search         全文搜索（需要 -Query）'
    Write-Host '  ingest-remote  远程下载并入库（需要 -Url）'
    Write-Host '  ingest-baidu-video 自动提取百度视频真实 mp4 后再转写入库（需要 -Url）'
    Write-Host '  ingest-video-page 通用视频页提取真实视频地址后再转写入库（需要 -Url）'
    Write-Host '  watch-wechat   监听微信视频下载目录并自动转写入库'
}

switch ($Action) {
    'help' {
        Show-Help
    }
    'shell' {
        Write-Host "进入项目目录：$ProjectRoot" -ForegroundColor Cyan
        Write-Host '提示：当前脚本不会修改你父级 shell 的激活状态。' -ForegroundColor Yellow
        Write-Host '如需手动激活：.\.venv\Scripts\activate' -ForegroundColor Yellow
        Start-Process powershell -WorkingDirectory $ProjectRoot
    }
    'doctor' {
        & $Python 'doctor.py'
    }
    'doctor-live' {
        & $Python 'doctor.py' '--live'
    }
    'bootstrap' {
        & $Python 'bootstrap.py'
    }
    'bootstrap-live' {
        & $Python 'bootstrap.py' '--live'
    }
    'summary-check' {
        & $Python 'check_summary_backend.py'
    }
    'stats' {
        & $Python 'stats.py'
    }
    'list' {
        & $Python 'list_docs.py' '--limit' '20'
    }
    'duplicates' {
        & $Python 'duplicates.py'
    }
    'search' {
        if (-not $Query) {
            Write-Host '请提供 -Query，例如：-Query "毛选"' -ForegroundColor Red
            exit 1
        }
        & $Python 'search.py' $Query
    }
    'ingest-remote' {
        if (-not $Url) {
            Write-Host '请提供 -Url，例如：-Url "https://example.com/file.mp4"' -ForegroundColor Red
            exit 1
        }
        $argsList = @('ingest_remote.py', $Url)
        if ($Tags) { $argsList += @('--tags', $Tags) }
        if ($Title) { $argsList += @('--title', $Title) }
        if ($Force) { $argsList += '--force' }
        & $Python @argsList
    }
    'ingest-baidu-video' {
        if (-not $Url) {
            Write-Host '请提供 -Url，例如：-Url "https://mbd.baidu.com/newspage/data/videolanding?nid=..."' -ForegroundColor Red
            exit 1
        }
        $argsList = @('ingest_baidu_video.py', $Url)
        if ($Tags) { $argsList += @('--tags', $Tags) }
        if ($Title) { $argsList += @('--title', $Title) }
        if ($NotifyFile) { $argsList += @('--notify-file', $NotifyFile) }
        if ($NotifyWebhook) { $argsList += @('--notify-webhook', $NotifyWebhook) }
        if ($Force) { $argsList += '--force' }
        & $Python @argsList
    }
    'ingest-video-page' {
        if (-not $Url) {
            Write-Host '请提供 -Url，例如：-Url "https://example.com/video-landing-page"' -ForegroundColor Red
            exit 1
        }
        $argsList = @('ingest_video_page.py', $Url)
        if ($Tags) { $argsList += @('--tags', $Tags) }
        if ($Title) { $argsList += @('--title', $Title) }
        if ($NotifyFile) { $argsList += @('--notify-file', $NotifyFile) }
        if ($NotifyWebhook) { $argsList += @('--notify-webhook', $NotifyWebhook) }
        if ($Force) { $argsList += '--force' }
        & $Python @argsList
    }
    'watch-wechat' {
        $argsList = @('watch_wechat_video_downloads.py', '--watch-dir', $WatchDir)
        if ($Tags) { $argsList += @('--tags', $Tags) }
        if ($ExportSite) { $argsList += '--export-site' }
        if ($PublishSite) { $argsList += '--publish-site' }
        Write-Host "监听目录：$WatchDir" -ForegroundColor Cyan
        & $Python @argsList
    }
    default {
        Show-Help
    }
}
