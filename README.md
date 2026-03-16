# Collector V1

本地内容采集系统 V1，支持网页、图片、PDF、音频、视频统一入库为 Markdown + JSON + SQLite。

## 项目路径

建议部署路径：`D:\openclaw\workspaces\think-tank\collector-v1`

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 初始化

```bash
python bootstrap.py
```

### 3. 如果使用 Kimi 摘要后端，先配置环境变量（PowerShell）

```powershell
$env:OPENAI_API_KEY="你的Kimi API Key"
$env:OPENAI_BASE_URL="https://api.moonshot.cn/v1"
$env:OPENAI_MODEL="moonshot-v1-8k"
```

然后测试：

```bash
python doctor.py --live
```

### 4. 导入内容

```bash
python ingest.py "https://example.com/article" --tags AI,产品
python ingest.py "D:/docs/report.pdf" --tags PDF,文档
python ingest.py "D:/media/meeting.m4a" --tags 会议,转写
```

### 5. 搜索

```bash
python search.py "AI"
```

## 存储位置

- 原始文件：`knowledge-vault/raw/`
- Markdown：`knowledge-vault/notes/`
- 元数据：`knowledge-vault/meta/`
- 资源：`knowledge-vault/assets/`
- 日志：`knowledge-vault/logs/`
- SQLite：`knowledge-vault/index.sqlite`

## 常用命令

```bash
python bootstrap.py
python doctor.py
python doctor.py --live
python check_summary_backend.py
python ingest.py "https://example.com"
python ingest_remote.py "https://example.com/file.mp4" --tags 远程导入,视频
python ingest_baidu_video.py "https://mbd.baidu.com/newspage/data/videolanding?nid=..." --tags 百度,视频,转写
python bulk_ingest.py "D:/archive"
python search.py "关键词"
python list_docs.py --limit 20
python duplicates.py
python stats.py
python export_site_data.py
python publish_site_data.py
```

## 导出静态网站数据

`export_site_data.py` 用于将本地采集的内容导出为静态网站可直接读取的 JSON 格式，供 GitHub + Vercel 查询站使用。

## 发布到查询站

`publish_site_data.py` 用于自动发布数据到 `collector-site` 并推送到 GitHub，触发 Vercel 自动部署。

### 用途

自动完成以下流程：
1. 运行 `export_site_data.py` 导出最新数据
2. 同步 `site-data/` 到 `collector-site/data/`
3. 在 `collector-site` 执行 `git add`、`git commit`、`git push`
4. Vercel 检测到 GitHub 更新后自动部署

### 基本用法

```bash
# 完整发布流程（导出 -> 同步 -> 推送）
python publish_site_data.py

# 自定义 commit 消息
python publish_site_data.py --message "add new video transcripts"

# 跳过导出（数据已是最新）
python publish_site_data.py --skip-export

# 只同步和提交，不推送
python publish_site_data.py --skip-push

# 指定 collector-site 目录
python publish_site_data.py --site-dir "D:/path/to/collector-site"
```

### 前置条件

1. `collector-site` 目录存在
2. `collector-site` 已初始化为 Git 仓库
3. `collector-site` 已关联 GitHub 远程仓库
4. 本地 Git 已配置好认证（SSH 或 HTTPS）

### 发布链路

```
collector-v1 (本地)
  ↓ export_site_data.py
site-data/ (导出)
  ↓ publish_site_data.py
collector-site/data/ (同步)
  ↓ git push
GitHub (远程仓库)
  ↓ webhook
Vercel (自动部署)
  ↓
查询站更新 ✓
```

### 用途

- 从 `knowledge-vault/meta/**/*.json` 读取元数据
- 读取对应的 Markdown 文件内容
- 导出为轻量级的 `index.json` 和完整的 `docs/<id>.json`
- 生成统计信息 `stats.json`

### 输出目录结构

```text
site-data/
  ├─ index.json          # 轻量级索引（列表页用）
  ├─ stats.json          # 统计信息
  └─ docs/
      ├─ <id1>.json      # 完整详情（包含 markdown）
      ├─ <id2>.json
      └─ ...
```

### 使用方法

```bash
# 基本用法：导出所有 processed/partial 状态的记录
python export_site_data.py

# 指定输出目录
python export_site_data.py --out-dir my-export

# 限制导出数量（最新 N 条）
python export_site_data.py --limit 10

# 包含 blocked/failed 状态的记录
python export_site_data.py --include-blocked
```

### 导出规则

- 默认只导出 `status` 为 `processed` 或 `partial` 的记录
- 默认不导出 `blocked` / `failed` 状态（可用 `--include-blocked` 包含）
- `index.json` 按时间倒序排列（最新的在前）
- 如果 Markdown 文件不存在，会跳过但继续导出其他字段，并标记 `markdown_missing: true`
- `index.json` 只包含轻量字段，不含全文内容
- `docs/<id>.json` 包含完整内容（包括 markdown 和 content_text）

## 云端任务队列（Vercel + Supabase + 本地 worker）

已在本地项目中预置一版 V1 文件，位置：

```text
cloud/
  ├─ supabase_schema.sql
  ├─ .env.example
  └─ poll_tasks.py
```

用途：
- `supabase_schema.sql`：初始化 `tasks` / `task_logs` 表
- `.env.example`：本地 worker 所需环境变量示例
- `poll_tasks.py`：本地 worker，轮询 Supabase 的 `pending` 任务并调用现有 `ingest.py` / `ingest_remote.py`

### 本地 worker 用法示例

```bash
cd cloud
copy .env.example .env
# 填好 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 后
python poll_tasks.py
python poll_tasks.py --loop
```

## 远程下载模式（适合外部投递大文件）

当你人在外面、Discord 传不了大文件时，可以先把文件上传到一个可下载链接，再在本地项目运行：

```bash
python ingest_remote.py "https://example.com/file.mp4" --tags 远程导入,视频
```

它会：
1. 先检查远程 URL 是网页还是文件
2. 如果是网页：直接路由到 `ingest.py URL`
3. 如果是文件：先下载到 `knowledge-vault/raw/remote_downloads/`
4. 自动推断文件类型和扩展名
5. 再复用现有 `ingest.py` 完成入库

### 例子

```bash
python ingest_remote.py "https://example.com/file.mp4" --tags 远程导入,视频
python ingest_remote.py "https://example.com/report.pdf" --tags 远程导入,PDF
python ingest_remote.py "https://example.com/article" --tags 远程导入,网页
python ingest_remote.py "https://example.com/download?id=123" --filename meeting.mp4 --tags 会议,远程导入
python ingest_remote.py "https://example.com/file.mp4" --inspect-only
```

## 视频落地页自动转写（通用版）

适合这种链接：

```bash
python ingest_video_page.py "https://example.com/video-landing-page" --tags 视频页,转写
python ingest_baidu_video.py "https://mbd.baidu.com/newspage/data/videolanding?nid=..." --tags 百度,视频,转写
powershell -ExecutionPolicy Bypass -File .\start.ps1 ingest-video-page -Url "https://example.com/video-landing-page" -NotifyFile ".\knowledge-vault\logs\video-status.json"
```

它会：
1. 对普通站点：先尝试用 HTTP 从页面源码里提取真实 `.mp4` / `.m3u8`
2. 对白名单大站（如百度、腾讯、微信）：**跳过 HTTP 直提**，直接用 Playwright 启动本机 Chrome 抓真实视频地址
3. 成功后自动调用 `ingest_remote.py`
4. 最终继续走现有视频转写与 Markdown 入库链路

遇到风控时：
- 脚本会识别常见验证/风控页面
- 默认会在本机浏览器里**暂停等待**你手动完成验证
- 验证完成后，脚本会继续尝试提取真实视频地址
- 如果等待超时，会明确提示你重新运行或直接提供真实视频链接
- 还可以通过 `--notify-file` / `--notify-webhook`（或 `config.yaml` 默认值）输出事件状态，方便接入 Supabase / Vercel
- 当前标准事件包括：`start`、`browser_first`、`http_extract_error`、`browser_fallback`、`blocked_pause`、`resume_success`、`blocked_timeout`、`resolved`、`ingest_failed`、`done`、`failed`
- `ingest_remote.py` 也已接入进度事件：`remote_start`、`remote_inspected`、`downloading`、`downloaded`、`download_retry`、`download_failed`、`local_ingest_start`、`local_ingest_failed`、`local_ingest_done`
- `ingest.py / audio.py / video.py` 也已细化阶段事件：如 `processing_started`、`extracting_audio`、`normalizing_audio`、`transcribing`、`writing_markdown`、`ingest_done`

说明：
- `ingest_baidu_video.py` 现在只是 `ingest_video_page.py` 的百度快捷别名
- 白名单大站可在 `config.yaml -> video_page.browser_first_hosts` 里配置
- 风控关键词可在 `config.yaml -> video_page.block_hints` 里配置
- 等待时长可在 `config.yaml -> video_page.browser_wait_seconds` / `video_page.block_wait_seconds` 里配置
- 通知输出可在 `config.yaml -> video_page.notify_file` / `video_page.notify_webhook` 里配置
- 站点自动更新可在 `config.yaml -> video_page.auto_export_site` / `video_page.auto_publish_site` 里配置（已支持在视频页转写成功后自动执行 `export_site_data.py` 和 `publish_site_data.py`）
- 默认白名单包含：`baidu.com`、`qq.com`、`v.qq.com`、`video.qq.com`、`weixin.qq.com`、`mp.weixin.qq.com`
- 依赖：`playwright`，并确保本机 Chrome 可用
- 对 `.mp4` 最友好；若抓到 `.m3u8`，会继续交给现有远程入库链路处理

### V1.1 新增能力

- 自动判断网页 / 文件并分流
- 下载重试（默认 3 次）
- 更清晰的 URL 检查与日志输出
- 支持 `--inspect-only` 仅检测，不实际下载/入库

## 微信视频号下载自动监听

`watch_wechat_video_downloads.py` 用于持续监听一个本地视频下载目录（例如微信视频号下载器的落地目录），当出现新视频文件时自动转写入库，可选导出或发布网站。

### 适用场景

```
微信视频下载器 → 落地 mp4
  ↓ watcher 监听到新文件
  ↓ 等待下载完成（文件大小稳定）
  ↓ python ingest.py 转写入库
  ↓ （可选）export_site_data.py 导出
  ↓ （可选）publish_site_data.py 发布网站
```

### 最小启动命令

```bash
python watch_wechat_video_downloads.py --watch-dir "D:\Downloads\WeChatVideos"
```

### 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--watch-dir` | 必填 | 监听目录（微信视频下载落地目录） |
| `--poll-seconds` | `5` | 轮询间隔（秒） |
| `--stable-check-seconds` | `2` | 文件稳定检查间隔（秒） |
| `--stable-rounds` | `3` | 连续多少轮大小不变视为下载完成 |
| `--tags` | `微信视频号,视频,转写` | ingest 时附加的标签 |
| `--export-site` | 否 | ingest 成功后自动导出站点数据 |
| `--publish-site` | 否 | ingest 成功后自动发布网站（隐含导出） |
| `--state-file` | `knowledge-vault/logs/watch-wechat-video-state.json` | 已处理文件状态记录 |
| `--once` | 否 | 只扫描一次后退出（用于测试） |

### 示例命令

```bash
# 基本监听（常驻）
python watch_wechat_video_downloads.py --watch-dir "D:\Downloads\WeChatVideos"

# 自动导出+发布
python watch_wechat_video_downloads.py --watch-dir "D:\Downloads\WeChatVideos" --publish-site

# 自定义标签
python watch_wechat_video_downloads.py --watch-dir "D:\Downloads\WeChatVideos" --tags "微信,财经,转写"

# 单次扫描测试
python watch_wechat_video_downloads.py --watch-dir "D:\Downloads\WeChatVideos" --once
```

### 支持监控的文件类型

`.mp4` / `.mov` / `.mkv` / `.webm`

### 状态文件

处理记录保存在 `knowledge-vault/logs/watch-wechat-video-state.json`，重启后不会重复处理同一文件。

### 下载器配置建议

请将你的微信视频号下载工具的输出目录设置为一个固定路径（如 `D:\Downloads\WeChatVideos`），然后将该路径传给 `--watch-dir`。

## 微信公众号链接

V1 会识别微信文章链接。当前优先级已调整为：

1. **Playwright 真实浏览器优先**（非 headless，可人工完成验证）
2. `Jina Reader` 作为 fallback
3. 最后才落回原始 HTML / blocked 记录

如果命中验证码/风控页，脚本会优先在真实浏览器里保留人工介入空间；如果仍未拿到正文，再记录为 blocked：

- `status = blocked`
- `block_reason = wechat_captcha`

并保存原始 HTML，不会假装抓取成功。
