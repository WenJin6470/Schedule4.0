#!/usr/bin/env bash
# sync-to-release.sh — 将 PR 文件夹中的清单和文档同步到 release
# 用法: ./sync-to-release.sh [AppID]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PR_DIR="$SCRIPT_DIR/pr"
RELEASE_DIR="$SCRIPT_DIR/release"

sync_one() {
    local appid="$1"
    local src="$PR_DIR/$appid"
    local dst="$RELEASE_DIR/$appid"
    if [[ ! -d "$src" ]]; then
        echo "[skip] $appid — pr/ not found"
        return
    fi
    mkdir -p "$dst"
    if [[ -f "$src/standalone_manifest.json" ]]; then
        cp "$src/standalone_manifest.json" "$dst/"
        cp "$src/FuncList.json" "$dst/"
        echo "[standalone] $appid -> standalone_manifest.json + FuncList.json"
    else
        echo "[error] $appid — no manifest found"
        return 1
    fi
}

list_appids() {
    if [[ ! -d "$PR_DIR" ]]; then return; fi
    for dir in "$PR_DIR"/*/; do [[ -d "$dir" ]] && basename "$dir"; done
}

if [[ $# -ge 1 ]]; then
    sync_one "$1"
else
    appids=()
    while IFS= read -r a; do [[ -n "$a" ]] && appids+=("$a"); done < <(list_appids)
    if [[ ${#appids[@]} -eq 0 ]]; then
        echo "no pr/ directory"
        exit 0
    elif [[ ${#appids[@]} -eq 1 ]]; then
        sync_one "${appids[0]}"
    else
        for appid in "${appids[@]}"; do sync_one "$appid"; done
    fi
fi
