# Docker 部署与分发

[English quick start](#english-quick-start)

本文介绍 Docker 启动、配置和镜像分发，也随分发包提供。先安装并启动 Docker，确认支持 Linux 容器和 Compose v2；无需另装 Python。Windows 使用 Linux 容器模式。

## 从源码启动

在项目根目录通过 PowerShell 或 Bash 执行：

```sh
docker compose -f docker/compose.yaml -f docker/compose.build.yaml up -d --build --wait --wait-timeout 120
```

启动后，在部署机器的浏览器中打开 `http://127.0.0.1:18080`。首次构建需要联网下载基础镜像和 Python 依赖；修改源码后，重新执行此命令更新服务。

如需同时导出镜像分发包，在 Bash 环境中执行：

```bash
bash docker/deploy.sh
```

脚本会构建并启动服务，生成 `dist/watcher-docker.tar.gz`，并尝试打开浏览器。

## 使用分发包

接收机器安装 Docker 后，解压 `watcher-docker.tar.gz`，进入包内 `watcher-docker/` 目录执行：

```sh
docker image load --input watcher-image.tar
docker compose up -d --wait --wait-timeout 120
```

也可在该目录的 Bash 环境中执行 `bash deploy.sh`，完成镜像导入和服务启动。

在部署机器的浏览器中打开 `http://127.0.0.1:18080`，在“模型设置”中填写 API 根地址、模型名称和 API Key，点击“保存配置”，连接测试通过后生效。根地址不包含 `/chat/completions`。检测 Agent Skill 时，先选择该检测对象，再上传根目录直接包含 `SKILL.md` 的单个包目录。

分发包不包含已有检测记录、上传源码或模型设置。使用时需配置自己的模型服务；检测过程仍会调用模型 API。

## 镜像平台与版本

镜像使用构建机器的默认平台。分发前，确认接收机器支持该 Linux 镜像及其 CPU 架构。

在含有 `compose.yaml` 的目录执行下面的命令，取得当前镜像名称：

```sh
docker compose config --images
```

然后检查输出的镜像名称；默认名称的示例如下：

```sh
docker image inspect --format '{{.Os}}/{{.Architecture}}' watcher:0.0.1-web
```

如果镜像名称经过自定义，请替换命令中的名称。源码更新后重新执行构建或分发脚本；发给别人的已有压缩包不会自动更新。

## 配置与数据

需要调整配置时，直接修改 `compose.yaml` 中对应环境变量表达式的默认值，再重新部署。例如，将 `${WATCHER_PORT:-18080}` 中的 `18080` 改为需要的端口。源码版配置位于 `docker/compose.yaml`。

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `WATCHER_IMAGE` | `watcher:0.0.1-web` | 镜像名称 |
| `WATCHER_PORT` | `18080` | 宿主机发布端口 |
| `WATCHER_BIND` | `127.0.0.1` | 宿主机绑定地址 |
| `WATCHER_MAX_CONCURRENT_SCANS` | `1` | 同时执行的检测任务数，其余任务排队 |

分发包的镜像名、端口和并发数已写入包内 `compose.yaml`。需要调整时，直接修改该文件的 `image`、`ports` 或 `environment`，再重新部署。修改后重新部署即可生效。

任务记录、源码副本和报告保存在数据卷中，容器内目录为 `/data`。停止、重启和重新部署会保留已经保存的数据。

默认在部署机器本机访问。容器需要连接部署机器上的模型服务时，将模型地址中的 `localhost` 改为 `host.docker.internal`，并确认模型服务允许来自容器的连接。

## 查看状态与管理服务

先进入含有 `compose.yaml` 的目录：源码部署使用 `docker/`，分发包部署使用解压后的 `watcher-docker/`。然后执行：

```sh
docker compose ps
docker compose logs -f --tail 100
docker compose stop
docker compose start
docker compose down
```

`stop` / `start` 用于停止和启动服务。`down` 移除容器和网络，但保留检测数据；`down -v` 会同时删除这些数据。服务重启后，未完成的任务需要重新提交。

启动失败时，运行 `docker compose logs --tail 100` 查看日志。服务启动后，在浏览器中打开首页即可开始使用。

## English quick start

Install and start Docker with Linux container support and Compose v2. Python is included in the image.

**From source**, run this command in the project root:

```sh
docker compose -f docker/compose.yaml -f docker/compose.build.yaml up -d --build --wait --wait-timeout 120
```

To also export a distribution bundle, run `bash docker/deploy.sh` in a Bash environment. It builds and starts the service and creates `dist/watcher-docker.tar.gz`.

**From a distribution bundle**, extract the archive, enter `watcher-docker/`, and run:

```sh
docker image load --input watcher-image.tar
docker compose up -d --wait --wait-timeout 120
```

Alternatively, run `bash deploy.sh` from that directory in a Bash environment.

Open `http://127.0.0.1:18080` in a browser on the machine running the service. Enter your API root, model name, and API key in model settings, then click **Save configuration**. The settings take effect after the connection test succeeds. Scans require a working model service. The bundle does not include existing scan data or model settings.

The image uses the build machine's default platform. From the directory containing `compose.yaml`, run `docker compose config --images`, then inspect the returned image name with `docker image inspect --format '{{.Os}}/{{.Architecture}}' IMAGE_NAME`. The receiving machine must support that Linux image and CPU architecture.

For source deployments, edit the defaults in `docker/compose.yaml`, such as `18080` in `${WATCHER_PORT:-18080}`, and redeploy. In exported bundles, settings are written into `compose.yaml`; edit that file's `image`, `ports`, or `environment` directly and redeploy.

From the directory containing `compose.yaml`, use `docker compose ps`, `docker compose logs -f --tail 100`, `docker compose stop`, `docker compose start`, or `docker compose down`. Saved data remains in the volume mounted at `/data`; `down -v` deletes it. Unfinished scans must be resubmitted after a restart. If startup fails, run `docker compose logs --tail 100` to view the logs.

The default address is accessible only from the machine running the service. For a model service on that machine, use `host.docker.internal` instead of `localhost` and confirm that the model service accepts connections from the container.
