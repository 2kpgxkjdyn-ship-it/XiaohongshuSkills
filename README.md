# XiaohongshuSkills Workbench

这是一个面向本地使用的小红书自动化工作台，基于 Chrome DevTools Protocol（CDP）控制浏览器，支持登录检查、图文/视频发布、内容检索、笔记详情读取、半自动评论队列、网页审核和本地 Web 控制台。

本项目基于开源小红书自动化工具整理扩展，保留 MIT License 与来源致谢。当前仓库重点补充了本地工作台、半自动评论队列、安装部署流程和公开发布前的安全忽略规则。

## 风险提示

使用任何小红书自动化工具都可能触发平台风控、限流、封号或账号限制。请仅用于学习研究或自有测试流程，优先使用测试账号、小频率运行，并在发布、评论、点赞、收藏等动作前进行人工审核。使用者需自行承担账号、内容和合规风险。

## 功能概览

- 本地 Web 工作台：通过浏览器页面生成待审队列、审核评论、发布已批准内容、查看运行状态。
- CDP 浏览器控制：启动、重启、关闭专用 Chrome，并检查小红书登录状态。
- 内容发布：支持图文、视频、本地文件、远程 URL、无头模式和预览模式。
- 内容检索：支持首页 feed、关键词搜索、笔记详情、评论数据、用户主页和通知接口读取。
- 互动动作：支持评论、回复、点赞/取消点赞、收藏/取消收藏。
- 半自动评论：搜索候选笔记，按配置筛选，生成 CSV 队列，由人工审核后再发布。
- 多账号隔离：通过不同 Chrome Profile 管理账号登录态。
- 安全忽略：默认忽略账号配置、日志、队列、缓存、虚拟环境和本地表格。

## 环境要求

- Windows 10/11
- Python 3.10+
- Google Chrome
- PowerShell
- 能访问小红书网页版和 GitHub/Python 包源的网络环境

## 快速安装

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

如果 PowerShell 阻止激活虚拟环境：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

完整迁移安装说明见 [INSTALL_WORKBENCH.md](INSTALL_WORKBENCH.md)。

## 首次登录

推荐先启动有窗口 Chrome：

```powershell
python scripts\chrome_launcher.py
```

扫码登录：

```powershell
python scripts\cdp_publish.py login
```

检查登录状态：

```powershell
python scripts\cdp_publish.py check-login
```

## 启动工作台

```powershell
python scripts\workbench.py
```

打开：

```text
http://127.0.0.1:8766/
```

常用参数：

```powershell
python scripts\workbench.py --host 127.0.0.1 --port 8766
python scripts\workbench.py --open
```

工作台会复用：

```text
semi_auto_comment.py
comment_templates.txt
review_queue.csv
comment_log.csv
run_status.log
```

其中 `review_queue.csv`、`comment_log.csv`、`run_status.log` 是运行数据，默认不会提交到 Git。

## 工作台流程

1. 输入关键词和候选数量，生成待审队列。
2. 在网页里查看候选、修改建议评论、批准、跳过或批量批准。
3. 点击“发布已批准”，底层调用 `semi_auto_comment.py --publish-approved`。
4. 在页面输出区或 `run_status.log` 查看进度和结果。

同一时间建议只运行一个后台任务，避免重复发布或覆盖队列。

## 半自动评论命令

生成待审队列，不发布：

```powershell
python semi_auto_comment.py --make-queue --keyword "示例关键词" --limit 10
```

终端审核队列：

```powershell
python semi_auto_comment.py --review-queue
```

发布已批准内容：

```powershell
python semi_auto_comment.py --publish-approved
```

直接逐条人工确认：

```powershell
python semi_auto_comment.py --keyword "示例关键词" --limit 10
```

交互按键：

```text
p 发布
r 换一句
e 编辑
s 跳过
q 退出
```

## 发布内容

图文发布：

```powershell
python scripts\publish_pipeline.py --headless `
  --title "文章标题" `
  --content "文章正文" `
  --image-urls "https://example.com/image.jpg"
```

有窗口预览，不自动点击发布：

```powershell
python scripts\publish_pipeline.py --preview `
  --title "文章标题" `
  --content "文章正文" `
  --image-urls "https://example.com/image.jpg"
```

本地图片：

```powershell
python scripts\publish_pipeline.py --headless `
  --title "文章标题" `
  --content "文章正文" `
  --images "C:\path\to\image.jpg"
```

视频：

```powershell
python scripts\publish_pipeline.py --headless `
  --title "视频标题" `
  --content "视频正文" `
  --video "C:\path\to\video.mp4"
```

## 内容检索与互动

首页推荐：

```powershell
python scripts\cdp_publish.py list-feeds
```

搜索笔记：

```powershell
python scripts\cdp_publish.py search-feeds --keyword "关键词"
```

获取详情：

```powershell
python scripts\cdp_publish.py get-feed-detail `
  --feed-id FEED_ID `
  --xsec-token XSEC_TOKEN
```

评论：

```powershell
python scripts\cdp_publish.py post-comment-to-feed `
  --feed-id FEED_ID `
  --xsec-token XSEC_TOKEN `
  --content "评论内容"
```

点赞/收藏：

```powershell
python scripts\cdp_publish.py note-upvote --feed-id FEED_ID --xsec-token XSEC_TOKEN
python scripts\cdp_publish.py note-bookmark --feed-id FEED_ID --xsec-token XSEC_TOKEN
```

## 多账号

列出账号：

```powershell
python scripts\cdp_publish.py list-accounts
```

添加账号：

```powershell
python scripts\cdp_publish.py add-account work --alias "工作号"
```

指定账号登录：

```powershell
python scripts\cdp_publish.py --account work login
```

指定账号发布：

```powershell
python scripts\publish_pipeline.py --account work --headless `
  --title "标题" `
  --content "正文" `
  --image-urls "https://example.com/image.jpg"
```

## 配置文件

账号配置示例：

```text
config/accounts.json.example
```

如需自定义账号：

```powershell
Copy-Item config\accounts.json.example config\accounts.json
```

半自动评论配置示例：

```text
config/semi_auto_comment.example.json
```

如需自定义筛选规则：

```powershell
Copy-Item config\semi_auto_comment.example.json config\semi_auto_comment.json
```

以下文件包含本地隐私或运行数据，不应上传：

```text
config/accounts.json
config/semi_auto_comment.json
comment_log*.csv
review_queue*.csv
run_status.log
tmp/
outputs/
.venv/
*.xlsx
```

## 目录结构

```text
scripts/
  workbench.py           本地 Web 工作台
  cdp_publish.py         CDP 自动化与互动命令
  publish_pipeline.py    图文/视频发布入口
  chrome_launcher.py     Chrome 生命周期管理
  account_manager.py     多账号 Profile 管理
  run_lock.py            后台任务锁
config/
  *.example.json         示例配置
images/publish_temp/     临时素材占位
docs/                    集成说明
```

## 常见问题

### Chrome 状态异常

```powershell
python scripts\chrome_launcher.py --restart
```

### 登录失效

```powershell
python scripts\cdp_publish.py login
```

### 端口被占用

```powershell
python scripts\workbench.py --port 8770
```

然后打开：

```text
http://127.0.0.1:8770/
```

## 许可证与来源

本项目使用 MIT License。

本仓库基于开源小红书自动化项目整理扩展，感谢原项目作者和社区贡献。保留来源说明是为了尊重原始工作和许可证要求；当前仓库的公开说明、模板和部署文档已做中性化处理。
