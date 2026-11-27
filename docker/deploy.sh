#!/usr/bin/env bash
set -euo pipefail

if (( $# > 0 )); then
    printf '此脚本不接受参数，请直接执行：bash %s\n' "$0" >&2
    exit 2
fi

DEPLOY_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname -- "$DEPLOY_DIR")"

compose() {
    docker compose --project-directory "$DEPLOY_DIR" -f "$DEPLOY_DIR/compose.yaml" "$@"
}

open_webpage() {
    local address url
    address="$(compose port web 8000)"
    address="${address%%$'\n'*}"
    case "$address" in
        0.0.0.0:*|\[::\]:*) address="127.0.0.1:${address##*:}" ;;
    esac
    url="http://$address"

    if command -v wslview >/dev/null 2>&1 && wslview "$url" >/dev/null 2>&1; then
        return
    fi
    if [[ "${OSTYPE:-}" == darwin* ]] && command -v open >/dev/null 2>&1 \
        && open "$url" >/dev/null 2>&1; then
        return
    fi
    if command -v xdg-open >/dev/null 2>&1 && xdg-open "$url" >/dev/null 2>&1; then
        return
    fi
    if command -v cmd.exe >/dev/null 2>&1 \
        && MSYS_NO_PATHCONV=1 cmd.exe /c start "" "$url" >/dev/null 2>&1; then
        return
    fi
    printf '无法自动打开浏览器，请访问：%s\n' "$url" >&2
}

export_bundle() (
    local destination staging_dir bundle_dir
    destination="$PROJECT_DIR/dist/watcher-docker.tar.gz"
    mkdir -p -- "$(dirname -- "$destination")"
    staging_dir="$(mktemp -d "$(dirname -- "$destination")/.watcher-export.XXXXXX")"
    trap 'rm -rf -- "$staging_dir"' EXIT
    bundle_dir="$staging_dir/watcher-docker"
    mkdir -- "$bundle_dir"
    docker image save --output "$bundle_dir/watcher-image.tar" "$image"
    cp -- "$DEPLOY_DIR/compose.yaml" "$DEPLOY_DIR/deploy.sh" \
        "$DEPLOY_DIR/README.md" "$bundle_dir/"
    # Preserve custom image names/ports when the bundle is exported.
    compose config > "$bundle_dir/compose.yaml"
    tar -czf "$staging_dir/bundle.tar.gz" -C "$staging_dir" watcher-docker
    mv -- "$staging_dir/bundle.tar.gz" "$destination"
)

if ! command -v docker >/dev/null 2>&1; then
    printf '%s\n' '请先安装并启动 Docker。' >&2
    exit 1
fi
docker compose version >/dev/null
docker version --format '{{.Server.Version}}' >/dev/null

image="$(compose config --images)"
source_checkout=false
if [[ -f "$PROJECT_DIR/pyproject.toml" && -f "$DEPLOY_DIR/Dockerfile" ]]; then
    source_checkout=true
    docker build -f "$DEPLOY_DIR/Dockerfile" -t "$image" "$PROJECT_DIR"
elif [[ -f "$DEPLOY_DIR/watcher-image.tar" ]]; then
    docker image load --input "$DEPLOY_DIR/watcher-image.tar"
elif ! docker image inspect "$image" >/dev/null 2>&1; then
    printf '%s\n' '未找到镜像，请在完整源码仓库或解压后的完整部署包中运行。' >&2
    exit 1
fi

if ! compose up -d --wait --wait-timeout 120; then
    compose logs --tail 80 >&2
    exit 1
fi

if [[ "$source_checkout" == true ]]; then
    export_bundle
fi

open_webpage
