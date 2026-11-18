# 连接工作室成员

在办公室切到实时模式，由总裁席写下目标。派单后 Carbon 自动出方案，Astra 选择执行成员，团队自动接力。结果汇总后由总裁验收。团队忙时任务自动排队。网页调用模型会使用本机 CLI 账户的额度。

| 工位 | 实际入口 | 启用条件 |
| --- | --- | --- |
| Gemini 4 Carbon / Argon / Hydrogen | Antigravity CLI，分别绑定 `gemini-4-carbon-medium`、`gemini-4-argon-medium`、`gemini-4-hydrogen-medium` | `agy models` 中包含相应型号，CLI 支持单次会话 `--settings` |
| GPT Astra | Codex CLI，绑定 `gpt-6.2-astra` | `codex login status` 已登录，`codex debug models` 中有这个型号 |
| 本机 Codex | Codex CLI，绑定 `gpt-6.2-sol`，负责修改和测试办公室代码 | 已登录的 CLI 账户可使用该模型，且本机能运行 Codex 沙盒 |
| Codex Dot | 个人 Dot 主会话与其连接的 Windows 电脑 | 点「连接我的 Dot」并发送入驻指令。电脑在线且允许 Dot 访问时可通过专用收件箱交付 |
| 同事协作席 | 同事电脑上的命令行 Agent 或兼容 Chat Completions 的 API | 创建插槽，把专属令牌和连接包交给对方，连接器上线后可由 Astra 分工 |

可以在本机终端核对实际可用的型号。Antigravity CLI 安装在项目目录时用 `.\.office-tools\agy.exe models`。第一次使用时，直接运行这个 `agy.exe` 完成 Google 登录。Codex 通过 `codex login` 登录。安装在自定义位置时，可用环境变量 `OFFICE_CODEX_BIN` 和 `OFFICE_AGY_BIN` 分别指定可执行文件的完整路径，再重启办公室。应用只查询 CLI 登录状态和型号清单，模型访问权与额度由服务商在执行时确认。[Antigravity 登录](https://antigravity.google/docs/cli/install/) · [Antigravity 型号选择](https://antigravity.google/docs/models) · [Dot 的使用方式](https://developers.openai.com/training/walkthroughs/personalize-your-dot)

## 从终端直接工作并上报状态

Dot 的收件箱命令是 `python office.py dot inbox`。有工单时会给出本步的任务和回执，用 `python office.py dot reply <taskId> <receipt> --file <答复文件>` 提交。绑定后进入 [Dot 的电脑管理](https://learn.chatgpt.com/docs/dots/computers-and-apps#connect-your-computers) 可检查设备在线状态。协作插槽使用独立的凭据和端口，接法见[同事接入指南](connectors/接入指南.md)。

用以下命令可以保留原终端输出、权限确认和 CLI 的退出码。示例在工作室目录运行，从其他项目运行时，将脚本路径换成你克隆的 `office.py` 路径。`--` 后填写对应 CLI 参数，工位会自动选择其指定模型。下面两行都将发起一次真实推理。

```powershell
python .\office.py run astra review -- exec "请简短说明当前 Git 仓库的用途"
python .\office.py run carbon planning -- -p "为团队周会安排三个议题"
```

程序启动后，工位显示「终端中」，进程存活时每十分钟续报一次。退出码为零显示「已完成」，其他退出码或中断显示「出错」。终端包装器只上报状态和类别；从网页提交的工作流才会自动将正文交给下一位。每个工位显示最近一次上报，同一成员并行运行多个命令会覆盖显示。交互式 CLI 的状态覆盖整个会话。

## 在 Dot、旧版 Gemini CLI 或既有工作流里手动上报

在真实事件发生时执行对应一行。用网页版、现有终端、脚本和 API 客户端都可以上报。涉及工作流时，还需在总裁席提交该步骤的实际结果。

```powershell
python office.py report carbon thinking planning
python office.py report astra needs_input review
python office.py report argon browsing research --with hydrogen
python office.py report dot done code
```

| 参数 | 可选值 |
| --- | --- |
| 成员 | `carbon`、`astra`、`codex`、`dot`、`argon`、`hydrogen` |
| 状态 | `idle` 空闲、`coding` 编码、`terminal` 终端、`browsing` 浏览、`thinking` 思考、`needs_input` 需要你、`error` 出错、`done` 完成 |
| 任务类别 | `general` 通用、`code` 编程、`research` 调研、`review` 审阅、`writing` 写作、`planning` 规划、`media` 媒体 |

## 网页任务的数据与权限

Carbon、Astra 和文本执行成员使用任务简报和上游结果生成文字。它们在临时目录运行，并关闭命令执行、项目文件访问等工具。CLI 会连接相应模型服务，模型服务可能按账号设置保存会话。[Antigravity 单次任务](https://antigravity.google/docs/cli/headless/) · [Antigravity 权限](https://antigravity.google/docs/cli/permissions)

本机 Codex 开发工位使用工作室的源码副本。工作室检查候选代码、运行测试，再将成果交给总裁验收。候选版可在独立本机地址预览，使用示例工位状态。正式任务记录、令牌和机器上的账号配置不随源码副本交给模型。总裁可以打回修改，或验收并发布后回退。前端改动发布后，任务详情可打开更新后的办公室，动态壁纸也会重新载入画面。Python 服务或原生 EXE 需要重启或构建才能加载相应改动。

公开工位状态只包含成员、状态、类别和可选的协作者。本机上报地址默认是 `http://127.0.0.1:8765`，密钥默认读取 `.office-data/report-token`。如将只读展示部署到 VPS，终端可指定 HTTPS 地址 `OFFICE_URL` 和对应的办公室写入密钥 `OFFICE_REPORT_TOKEN`。网页派单使用运行服务的机器上的 CLI 与登录；VPS 要调用你电脑上的 CLI 时还需要独立的本地执行通道。
