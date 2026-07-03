# 小红书工作台安装流程

这份说明用于把当前项目压缩包复制到另一台 Windows 电脑后，从零安装并启动本地 Web 工作台。

## 1. 目标电脑需要准备

- Windows 10/11
- Python 3.10 或更高版本
- Google Chrome 浏览器
- 能正常访问小红书网页版的网络环境
- PowerShell

安装 Python 时建议勾选 `Add Python to PATH`。

安装后在 PowerShell 中检查：

```powershell
python --version
pip --version
```

如果能看到版本号，说明 Python 和 pip 可用。

## 2. 解压项目

把压缩包解压到一个固定目录，例如：

```text
C:\XiaohongshuSkills
```

后续命令都在这个目录里执行：

```powershell
cd C:\XiaohongshuSkills
```

## 3. 创建虚拟环境并安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

如果 PowerShell 不允许激活虚拟环境，先执行：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

当前项目依赖很少，主要是：

```text
requests
websockets
```

## 4. 准备配置文件

默认可以先不手动创建账号配置，直接走扫码登录。

如果需要多账号或指定 Chrome Profile，可以复制示例：

```powershell
Copy-Item config\accounts.json.example config\accounts.json
```

然后编辑 `config\accounts.json`，把 `profile_dir` 改成目标电脑上的本地路径。不要把真实 Cookie、账号令牌或个人 Chrome Profile 打包给别人。

半自动评论筛选配置可选：

```powershell
Copy-Item config\semi_auto_comment.example.json config\semi_auto_comment.json
```

如果不复制，脚本会使用默认逻辑或示例模板。

## 5. 首次登录小红书

推荐先启动有窗口 Chrome，方便扫码：

```powershell
python scripts\chrome_launcher.py
```

然后执行登录：

```powershell
python scripts\cdp_publish.py login
```

在弹出的 Chrome 窗口中扫码登录小红书。

登录后检查状态：

```powershell
python scripts\cdp_publish.py check-login
```

如果需要检查主页登录态，也可以打开工作台后用页面里的登录检查按钮。

## 6. 启动本地工作台

```powershell
python scripts\workbench.py
```

浏览器打开：

```text
http://127.0.0.1:8766/
```

也可以指定端口：

```powershell
python scripts\workbench.py --host 127.0.0.1 --port 8766
```

如果希望脚本自动打开浏览器：

```powershell
python scripts\workbench.py --open
```

## 7. 工作台常用流程

1. 在工作台中输入关键词和候选数量，生成 `review_queue.csv`。
2. 在网页里查看候选、修改建议评论、批准或跳过。
3. 点击发布已批准，底层会调用 `semi_auto_comment.py --publish-approved`。
4. 通过页面输出区或 `run_status.log` 查看运行状态。

同一时间只建议跑一个任务，避免重复发布或覆盖队列。

## 8. 命令行备用流程

生成待审队列：

```powershell
python semi_auto_comment.py --make-queue --keyword "找货源" --limit 10
```

终端审查队列：

```powershell
python semi_auto_comment.py --review-queue
```

发布已批准内容：

```powershell
python semi_auto_comment.py --publish-approved
```

## 9. 常见问题

### 端口被占用

换一个端口启动：

```powershell
python scripts\workbench.py --port 8770
```

访问：

```text
http://127.0.0.1:8770/
```

### 登录失效

重新扫码：

```powershell
python scripts\cdp_publish.py login
```

### 依赖安装失败

确认目标电脑能访问 Python 包源，然后重新执行：

```powershell
pip install -r requirements.txt
```

### Chrome 没有启动或状态异常

重启专用 Chrome：

```powershell
python scripts\chrome_launcher.py --restart
```

关闭专用 Chrome：

```powershell
python scripts\chrome_launcher.py --kill
```

## 10. 风险提醒

小红书自动化操作可能触发平台风控、限流、封号或禁用账号。建议使用测试号、小频率运行，并在发布前人工审核内容。
