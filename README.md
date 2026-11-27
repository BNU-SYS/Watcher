# Watcher

中文 | [English](README.en.md)

Watcher 是一个面向 Java、PHP、C/C++、Python 源码及 Agent Skill 的智能缺陷检测框架，支持多类 CWE 缺陷检测与 Agent Skill 安全审查。支持检测源码文件、项目目录和代码仓库，展示候选缺陷、保存检测报告，并提供用户反馈入口。

项目提供 **Docker 部署**和 **Python 本地部署**两种方式。推荐使用 Docker 统一运行环境；Python 本地部署适合开发和调试。

## 功能与支持范围

- **源码检测**：上传文件或目录、粘贴代码，或读取公开 GitHub 仓库，可指定仓库分支、标签和子目录。
- **检测范围控制**：选择语言、缺陷类型，设置文件数量、模型调用次数、文件大小和超时等预算。
- **结果查看**：展示任务进度、候选缺陷、源码证据、覆盖范围和执行错误，支持筛选与 JSON 报告下载。
- **反馈与记录**：对源码报告提交误报、漏报、位置或 CWE 分类反馈，保存检测记录、反馈结果与 Token 用量。
- **Agent Skill 审查**：检查提示词注入、恶意代码、权限过大、密钥泄露、供应链和校验问题。

当前支持范围由 `skills/*/manifest.json` 声明，具体支持类型见下表中的能力声明，规则位于对应 Skill 目录：

| 检测对象 | 当前类型数 | 说明 |
| --- | --- | --- |
| Java | 17 类 CWE | [skills/java/manifest.json](skills/java/manifest.json) |
| C/C++ | 8 类 CWE | [skills/c/manifest.json](skills/c/manifest.json) |
| PHP | 12 类 CWE | [skills/php/manifest.json](skills/php/manifest.json) |
| Python | 10 类 CWE | [skills/python/manifest.json](skills/python/manifest.json) |
| Agent Skill | 6 类安全问题 | [skills/agent_skill/manifest.json](skills/agent_skill/manifest.json) |

上表列出了四种编程语言和 Agent Skill 支持的检测类型，具体规则见对应的 Skill 目录。

源码检测报告支持用户反馈；Agent Skill 检测报告暂不支持此功能。

## 选择部署方式

| 对比项 | Docker 部署（推荐） | Python 本地部署 |
| --- | --- | --- |
| 适用场景 | 统一环境、交付和部署 | 开发调试、自定义环境 |
| 软件要求 | 支持 Linux 容器的 Docker，包含 Compose v2 | Python 3.11+、pip |
| 宿主机是否需要 Python | 不需要 | 需要 |
| 默认访问地址 | http://127.0.0.1:18080 | http://127.0.0.1:8000 |
| 默认数据位置 | Docker 命名数据卷，容器内为 `/data` | 项目内 `web/data/` |

两种部署方式均需配置可用的模型服务、模型名称和 API Key。默认在部署机器上通过浏览器访问；使用 Docker 部署时，该机器需安装 Docker，无需另装 Python。

**下文命令均在项目根目录执行。**

## 方式一：Docker 部署

### 构建并启动

安装并启动 Docker，确认支持 Docker Compose v2；Windows 使用 Linux 容器模式。首次构建需要联网下载基础镜像与 Python 依赖。

在 PowerShell 或 Bash 中执行：

```sh
docker compose -f docker/compose.yaml -f docker/compose.build.yaml up -d --build --wait --wait-timeout 120
```

启动后，在部署机器的浏览器中打开 `http://127.0.0.1:18080`。修改源码后，重新执行此命令以构建并部署更新。

### 查看和管理服务

```sh
docker compose -f docker/compose.yaml ps
docker compose -f docker/compose.yaml logs -f --tail 100
docker compose -f docker/compose.yaml stop
docker compose -f docker/compose.yaml start
docker compose -f docker/compose.yaml down
```

`stop` / `start` 用于停止和启动服务；`down` 移除容器和网络，但保留检测数据。执行 `down -v` 会同时删除数据卷中的检测记录、源码副本和报告。

## 方式二：Python 本地部署

安装 **Python 3.11 或更高版本**及 pip。以下命令创建独立虚拟环境并直接调用环境内的解释器，无需激活环境。

### Windows / PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e . -r web/requirements.txt
$env:WATCHER_FRAMEWORK_DIR = (Get-Location).Path
.\.venv\Scripts\python.exe web/backend/run.py
```

### Linux / macOS / Bash

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e . -r web/requirements.txt
export WATCHER_FRAMEWORK_DIR="$PWD"
.venv/bin/python web/backend/run.py
```

启动后，在部署机器的浏览器中打开 `http://127.0.0.1:8000`。在终端按 `Ctrl+C` 停止服务。后续启动时，在项目根目录设置 `WATCHER_FRAMEWORK_DIR`，再执行对应的启动命令即可。

### 可选运行配置

默认配置即可启动服务。需要调整时，可在启动服务的终端设置以下环境变量。框架路径、数据目录和并发数也可写入 `web/.env`；若终端和文件中设置了同名变量，以终端中的值为准。

| 变量 | 本地使用说明 |
| --- | --- |
| `WATCHER_FRAMEWORK_DIR` | 框架根目录，按上面的命令设置为当前项目路径 |
| `WATCHER_DATA_DIR` | 检测数据保存目录，默认 `web/data/`；自定义时使用绝对路径 |
| `WATCHER_MAX_CONCURRENT_SCANS` | 同时执行的任务数，默认 `1`，其余任务排队等待 |
| `WATCHER_HOST` / `WATCHER_PORT` | 本地启动监听地址和端口，默认 `127.0.0.1` / `8000` |
| `WATCHER_RELOAD` | 设为 `true` 后，修改代码会自动重启服务 |

## 开始检测

1. 打开网页，进入“模型设置”，填写模型 API 根地址、模型名称和 API Key，点击“保存配置”。连接测试通过后，配置保存并生效。根地址形如 `https://api.openai.com/v1`，不要附加 `/chat/completions`。
2. 进入“新建检测”，先选择对应语言，再上传源码文件或目录、粘贴代码，或输入公开 GitHub 仓库地址。选择缺陷类型、确认模型后提交。
3. 查看任务进度与报告，结合源码证据、覆盖范围和错误判断结果；按需下载 JSON 或对源码报告提交反馈。
4. 检测 Agent Skill 时，先选择该检测对象，再上传根目录直接包含 `SKILL.md` 的单个包目录。

文件数量、模型调用次数、单文件字符数及超时可在新建检测页的“高级参数”中调整。

## 数据保存与运行说明

- **检测数据**：任务记录、源码副本和报告分别保存在数据目录的 `scans/`、`workspaces/`、`reports/` 中。停止或重启服务会保留已经保存的数据。
- **模型服务**：用于模型分析的源码会发送到所配置的模型服务。模型设置保存在当前浏览器中，请妥善保管 API Key。
- **宿主机模型**：Docker 中访问宿主机上的模型 API 时，使用 `host.docker.internal` 代替 `localhost`，并确保服务监听容器可访问的地址。
- **任务调度**：默认同时执行一个检测任务，其余任务排队等待。服务重启后，未完成的任务会标为失败，需要重新提交。

## 命令行检测

安装后，可通过命令行检测文件、目录或 HTTPS Git 仓库。先设置模型服务配置：

```powershell
$env:ICODE_BASE_URL = "https://api.openai.com/v1"
$env:ICODE_MODEL = "模型名称"
$env:ICODE_API_KEY = "XXXXXXXXXXXXXXXXXX"
python -m detector "待检测目录" --language python
```

将占位符替换为实际配置，并使用已安装本项目的 Python 解释器。Bash 使用 `export 变量名="值"` 设置环境变量。完整参数见 `python -m detector --help`；Agent Skill 检测使用 `--language agent_skill`。

## 项目结构

```text
.
├── docker/          # 镜像构建、服务启动及分发
├── web/             # 网页后端与界面
├── src/detector/    # 检测框架与命令行入口
├── skills/          # 五类检测对象的运行规则
├── pyproject.toml   # Python 安装及运行规则打包
├── LICENSE
└── THIRD_PARTY_NOTICES.md
```

Docker 配置和镜像分发见 [Docker 部署说明](docker/README.md)。
