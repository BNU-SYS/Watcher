# Watcher

[中文](README.md) | English

Watcher reviews Java, PHP, C/C++, and Python source code and Agent Skill packages. It accepts source files, project directories, and Git repositories, displays candidate findings, saves reports, and provides a feedback interface.

The project supports **Docker deployment** and **local Python deployment**. Docker is recommended for a consistent environment; local Python deployment is suited to development and debugging.

## Features and supported checks

- **Source input**: upload files or a directory, paste code, or use a public GitHub repository with an optional branch, tag, and subdirectory.
- **Scan limits**: choose a language and defect types; configure file count, model calls, file size, and time budgets.
- **Results**: view progress, candidate defects, source evidence, coverage, and errors; filter findings and download JSON reports.
- **Feedback and history**: submit false-positive, false-negative, location, or CWE classification feedback for source reports; retain scans, feedback results, and token usage.
- **Agent Skill review**: check prompt injection, malicious code, excessive permissions, secret exposure, supply chain risks, and validation issues.

Current capabilities are declared in `skills/*/manifest.json`. The linked manifests list supported categories; runtime rules are stored in each Skill directory.

| Target | Current categories | Details |
| --- | --- | --- |
| Java | 17 CWEs | [skills/java/manifest.json](skills/java/manifest.json) |
| C/C++ | 8 CWEs | [skills/c/manifest.json](skills/c/manifest.json) |
| PHP | 12 CWEs | [skills/php/manifest.json](skills/php/manifest.json) |
| Python | 10 CWEs | [skills/python/manifest.json](skills/python/manifest.json) |
| Agent Skill | 6 security categories | [skills/agent_skill/manifest.json](skills/agent_skill/manifest.json) |

The table lists the supported checks for four programming languages and Agent Skill packages. See each Skill directory for its rules.

User feedback is available for source reports. Agent Skill reports do not currently support feedback.

## Choose a deployment option

| Item | Docker (recommended) | Local Python |
| --- | --- | --- |
| Intended use | Consistent environments, distribution, and deployment | Development, debugging, and custom environments |
| Requirements | Docker with Linux container support and Compose v2 | Python 3.11+ and pip |
| Python on the host | Not required | Required |
| Default URL | http://127.0.0.1:18080 | http://127.0.0.1:8000 |
| Default data location | Docker named volume mounted at `/data` | Project directory `web/data/` |

Both options require a working model service, model name, and API key. By default, open the application in a browser on the machine running it. Docker deployment requires Docker on that machine, with no separate Python installation.

**Run all commands below from the project root.**

## Option 1: Docker deployment

### Build and start

Install and start Docker with Compose v2. On Windows, use Linux containers. The first build needs network access to download the base image and Python dependencies.

Run in PowerShell or Bash:

```sh
docker compose -f docker/compose.yaml -f docker/compose.build.yaml up -d --build --wait --wait-timeout 120
```

Open `http://127.0.0.1:18080` in a browser on the machine running the service. After changing the source, run the same command to rebuild and deploy.

### Manage the service

```sh
docker compose -f docker/compose.yaml ps
docker compose -f docker/compose.yaml logs -f --tail 100
docker compose -f docker/compose.yaml stop
docker compose -f docker/compose.yaml start
docker compose -f docker/compose.yaml down
```

`stop` and `start` stop and start the service. `down` removes containers and the network while keeping scan data. Adding `-v` also deletes the data volume, including scan records, source snapshots, and reports.

## Option 2: Local Python deployment

Install **Python 3.11 or later** with pip. These commands use a dedicated virtual environment directly, without requiring shell activation.

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

Open `http://127.0.0.1:8000` in a browser on the machine running the service. Press `Ctrl+C` in the terminal to stop it. For later launches, set `WATCHER_FRAMEWORK_DIR` in the project root and run the appropriate startup command.

### Optional configuration

The defaults are sufficient to start the service. To change them, set the following environment variables in the terminal used to launch it. The framework path, data directory, and concurrency limit can also be set in `web/.env`. Terminal environment variables take precedence over values in that file.

| Variable | Local deployment |
| --- | --- |
| `WATCHER_FRAMEWORK_DIR` | Framework root; set it to this project directory as shown above |
| `WATCHER_DATA_DIR` | Scan data directory; defaults to `web/data/`. Use an absolute path for a custom location |
| `WATCHER_MAX_CONCURRENT_SCANS` | Concurrent tasks; defaults to `1` (further tasks queue up) |
| `WATCHER_HOST` / `WATCHER_PORT` | Local bind address and port; defaults to `127.0.0.1` / `8000` |
| `WATCHER_RELOAD` | Set to `true` during local development to restart the service after code changes |

## Start a scan

1. Open model settings, enter the API root, model name, and API key, then click **Save configuration**. The connection is tested automatically, and the settings are saved only after the test succeeds. Use a root such as `https://api.openai.com/v1` without appending `/chat/completions`.
2. Create a scan by first selecting the source language, then uploading files or a directory, pasting code, or providing a public GitHub repository URL. Choose the defect types, confirm the model settings, and submit.
3. Review progress and the report together with source evidence, coverage, and errors. Download JSON or submit feedback for source reports as needed.
4. For Agent Skill checks, first select that target, then upload one package directory with `SKILL.md` directly at its root.

Use **Advanced parameters** on the new scan page to adjust file count, model calls, file size in characters, and timeouts.

## Data storage and runtime behavior

- **Stored data**: task records, source snapshots, and reports are saved under `scans/`, `workspaces/`, and `reports/` in the data directory. Saved data remains after a stop or restart.
- **Model service**: source selected for analysis is sent to the configured model service. Model settings are saved in the current browser; keep API keys private.
- **Models on the Docker host**: use `host.docker.internal` instead of `localhost`, and ensure the model service listens on an address reachable from the container.
- **Scheduling**: one scan runs at a time by default; other scans wait in a queue. After a service restart, unfinished scans are marked as failed and must be resubmitted.

## Command-line scans

After installation, scan a source file, directory, or HTTPS Git repository. Set the model configuration first:

```powershell
$env:ICODE_BASE_URL = "https://api.openai.com/v1"
$env:ICODE_MODEL = "MODEL_NAME"
$env:ICODE_API_KEY = "XXXXXXXXXXXXXXXXXX"
python -m detector "SOURCE_DIRECTORY" --language python
```

Replace the placeholders and use the Python interpreter where this project is installed. In Bash, set variables with `export NAME="VALUE"`. Run `python -m detector --help` for all options. Use `--language agent_skill` for Agent Skill packages.

## Project layout

```text
.
├── docker/          # Image build, service startup, and distribution
├── web/             # Web backend and frontend
├── src/detector/    # Detection framework and CLI
├── skills/          # Runtime rules for five detection targets
├── pyproject.toml   # Python installation and runtime rule packaging
├── LICENSE
└── THIRD_PARTY_NOTICES.md
```

See the [Docker guide](docker/README.md#english-quick-start) for Docker configuration and distribution.
