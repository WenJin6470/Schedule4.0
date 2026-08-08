#!/usr/bin/env bash
# version.sh — 管理节点的版本号（patch/minor/major）
# 用法: ./version.sh {show|patch|minor|major|set} [AppID] [version]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

bump() {
    local ver="$1" part="$2"
    IFS='.' read -r major minor patch <<< "$ver"
    case "$part" in
        major) echo "$((major + 1)).0.0" ;;
        minor) echo "$major.$((minor + 1)).0" ;;
        patch) echo "$major.$minor.$((patch + 1))" ;;
    esac
}

update_manifest() {
    local file="$1" newver="$2" tmp="$file.tmp"
    sed -E "s/\"(manifestVersion|version)\": \"v?[0-9]+\.[0-9]+\.[0-9]+\"/\"\\1\": \"$newver\"/" "$file" > "$tmp"
    mv "$tmp" "$file"
}

update_appid() {
    local appid="$1" newver="$2" updated=0
    for base in "$SCRIPT_DIR/pr/$appid" "$SCRIPT_DIR/release/$appid"; do
        for f in "$base"/FuncList.json "$base"/*_manifest.json; do
            if [[ -f "$f" ]]; then
                local oldver
                oldver="$(grep -oP '(?<="(manifestVersion|version)":\s")v?[0-9]+\.[0-9]+\.[0-9]+' "$f" | head -1 | sed 's/^v//')"
                if [[ -n "$oldver" ]]; then
                    update_manifest "$f" "$newver"
                    echo "[update] $f: $oldver -> $newver"
                    updated=1
                fi
            fi
        done
    done
    if [[ $updated -eq 0 ]]; then
        echo "[error] no manifest found for $appid"
        exit 1
    fi
}

do_show() {
    local appid="$1"
    for f in "$SCRIPT_DIR/pr/$appid"/FuncList.json "$SCRIPT_DIR/pr/$appid"/*_manifest.json; do
        if [[ -f "$f" ]]; then
            echo "$(basename "$f"): $(grep -oP '(?<="(manifestVersion|version)":\s")[^"]+' "$f" | head -1)"
        fi
    done
}

list_appids() {
    for dir in "$SCRIPT_DIR"/pr/*/; do [[ -d "$dir" ]] && basename "$dir"; done
}

CMD="${1:-show}"

if [[ $# -ge 2 ]]; then
    APPID="$2"
else
    appids=()
    while IFS= read -r a; do [[ -n "$a" ]] && appids+=("$a"); done < <(list_appids)
    if [[ ${#appids[@]} -eq 0 ]]; then
        echo "no AppID found"
        exit 1
    elif [[ ${#appids[@]} -eq 1 ]]; then
        APPID="${appids[0]}"
        echo "[auto] AppID: $APPID"
    else
        echo "multiple AppIDs, specify: $0 $CMD <AppID>"
        for a in "${appids[@]}"; do echo "  - $a"; done
        exit 1
    fi
fi

case "$CMD" in
    show) do_show "$APPID" ;;
    patch|minor|major)
        oldver="$(grep -oP '(?<="(manifestVersion|version)":\s")v?[0-9]+\.[0-9]+\.[0-9]+' "$SCRIPT_DIR/pr/$APPID"/FuncList.json | head -1 | sed 's/^v//')"
        newver="$(bump "$oldver" "$CMD")"
        update_appid "$APPID" "$newver"
        ;;
    set)
        newver="${3:-}"
        if [[ -z "$newver" ]]; then
            echo "usage: $0 set <AppID> <version>"
            exit 1
        fi
        update_appid "$APPID" "$newver"
        ;;
    *) echo "unknown: $CMD (use show|patch|minor|major|set)" ; exit 1 ;;
esac
