# publish_site_data.py 使用说明

## 功能

自动发布 collector-v1 的数据到 collector-site 并推送到 GitHub，触发 Vercel 自动部署。

## 完整流程

```
1. export_site_data.py     → 导出数据到 site-data/
2. 同步到 collector-site/data/
3. git add data
4. git commit
5. git push                 → 触发 Vercel 部署
```

## 基本用法

```bash
# 完整发布（推荐）
python publish_site_data.py

# 自定义提交消息
python publish_site_data.py --message "add 3 new videos"

# 跳过导出（数据已是最新）
python publish_site_data.py --skip-export

# 只同步和提交，不推送（测试用）
python publish_site_data.py --skip-push

# 指定 collector-site 目录
python publish_site_data.py --site-dir "D:/custom/path/collector-site"
```

## 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--site-dir` | `D:\openclaw\workspaces\think-tank\collector-site` | collector-site 项目目录 |
| `--message` | `update site data` | Git commit 消息 |
| `--skip-export` | False | 跳过执行 export_site_data.py |
| `--skip-push` | False | 只同步和 commit，不 push |

## 前置条件

### 1. collector-site 已初始化为 Git 仓库

```bash
cd D:\openclaw\workspaces\think-tank\collector-site
git init
git add .
git commit -m "initial commit"
```

### 2. 关联 GitHub 远程仓库

```bash
# 创建 GitHub 仓库后
git remote add origin https://github.com/your-username/collector-site.git
git branch -M main
git push -u origin main
```

### 3. 配置 Git 用户信息（如果未配置）

```bash
# 全局配置
git config --global user.email "you@example.com"
git config --global user.name "Your Name"

# 或仅在 collector-site 仓库配置
cd collector-site
git config user.email "you@example.com"
git config user.name "Your Name"
```

### 4. Vercel 项目已关联 GitHub 仓库

在 Vercel 控制台导入 GitHub 仓库，Vercel 会自动监听 push 事件并部署。

## 典型工作流

### 场景 1: 新增内容后发布

```bash
# 1. 采集新内容
python ingest.py "https://example.com/article" --tags AI

# 2. 发布到网站
python publish_site_data.py
```

### 场景 2: 批量导入后发布

```bash
# 1. 批量导入
python bulk_ingest.py "D:/videos"

# 2. 发布到网站
python publish_site_data.py --message "add 10 new videos"
```

### 场景 3: 测试发布流程

```bash
# 只同步和提交，不推送
python publish_site_data.py --skip-push

# 检查 collector-site 的 git 状态
cd ../collector-site
git status
git log -1
```

## 输出示例

### 成功发布

```
[*] 开始发布流程...
    源目录: D:\openclaw\workspaces\think-tank\collector-v1\site-data
    目标目录: D:\openclaw\workspaces\think-tank\collector-site\data

[1/5] 导出 site data...
    导出完成

[2/5] 同步数据到 collector-site/data...
    已删除旧数据
    数据同步完成
    同步了 8 个 JSON 文件

[3/5] git add data...
    git add 完成

[4/5] git commit...
    提交成功: update site data

[5/5] git push...
    推送成功

[+] 完成: site data 已成功发布
    Vercel 将自动部署更新
```

### 无变更

```
[*] 开始发布流程...
    源目录: D:\openclaw\workspaces\think-tank\collector-v1\site-data
    目标目录: D:\openclaw\workspaces\think-tank\collector-site\data

[1/5] 跳过导出 (--skip-export)

[2/5] 同步数据到 collector-site/data...
    已删除旧数据
    数据同步完成
    同步了 8 个 JSON 文件

[3/5] git add data...
    git add 完成

[4/5] git commit...
    没有变更需要提交

[*] 完成: 数据已是最新，无需推送
```

## 错误处理

脚本会在以下情况报错并退出：

1. `collector-site` 目录不存在
2. `collector-site/.git` 不存在（不是 Git 仓库）
3. `site-data/` 目录不存在
4. `git add/commit/push` 失败（无变更除外）

## 注意事项

1. 首次使用前确保 collector-site 已关联 GitHub 远程仓库
2. 确保本地 Git 已配置好认证（SSH 密钥或 HTTPS token）
3. 如果 push 失败，检查网络连接和 Git 认证
4. 建议先用 `--skip-push` 测试同步流程
5. Vercel 部署通常需要 1-2 分钟

## 故障排查

### 问题: git push 失败

```bash
# 检查远程仓库配置
cd collector-site
git remote -v

# 测试连接
git fetch

# 如果是认证问题，重新配置
git remote set-url origin https://github.com/your-username/collector-site.git
```

### 问题: 数据未更新

```bash
# 手动检查数据
cd collector-site/data
ls -la

# 检查 git 状态
git status
git diff
```

### 问题: Vercel 未自动部署

1. 检查 Vercel 项目设置中的 Git 集成
2. 查看 Vercel 部署日志
3. 确认 GitHub webhook 已配置
