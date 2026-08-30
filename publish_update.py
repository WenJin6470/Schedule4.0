"""
╔══════════════════════════════════════════════════════════════════════════╗
║        📅 电子课表系统 —— publish_update.py（一键构建 + 发布更新）         ║
╚══════════════════════════════════════════════════════════════════════════╝

📌 本脚本做什么（一条命令完成发布全流程）
═══════════════════════════════════════════════════════════════════════════
  1. Nuitka 打包（--standalone + PySide6 插件，产物在 build/main.dist）
  2. 组装 exe/ 完整运行环境（模拟用户电脑：main.exe + _internal + images
     + Config + log）
  3. 生成更新包（仅含程序文件 main.exe + _internal/）：
       - 全量包  update-<版本>-full.zip
       - 差分包  update-<版本>-delta.zip（与上一版本对比，只打包变化的文件）
       （超过 Gitee raw 直链限制的大文件自动切成 .partNNN 分片存储）
  4. 生成版本清单 latest.json（版本号 / 下载地址 / SHA-256 / 文件清单）
  5. 写入本地更新仓库 update_repo/ 并提交；--push 时推送到
     https://gitee.com/zhao-chenyu-8633/Schedule4.0-Update.git

📌 用法
═══════════════════════════════════════════════════════════════════════════
  .\\venv\\Scripts\\python.exe publish_update.py --version 4.1.0 --notes "修复xxx" --push
  参数：
    --version    必填，本次发布版本号（如 4.1.0）
    --notes      可选，更新说明（写入 latest.json 的 notes）
    --push       可选，推送到 Gitee 更新仓库（需已配置 git 凭据）
    --skip-build 可选，跳过 Nuitka 构建（复用 build/main.dist 已有产物）

📌 依赖
═══════════════════════════════════════════════════════════════════════════
  - 本机已安装 Nuitka（venv 内）与 C 编译器（MSVC / MinGW64）
  - 发布机器需能访问 Gitee（推送时）
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# 控制台可能为 GBK 编码，统一输出 UTF-8，避免 emoji 打印崩溃
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ================================================================
#  路径常量
# ================================================================
CODE_DIR: Path = Path(__file__).resolve().parent
PROJECT_ROOT: Path = CODE_DIR.parent
VENV_PY: Path = Path(sys.executable)  # 本脚本需用 venv 的 python 运行
DIST_DIR: Path = CODE_DIR / 'build' / 'main.dist'
EXE_DIR: Path = PROJECT_ROOT / 'exe'          # 模拟用户运行环境
UPDATE_REPO: Path = CODE_DIR / 'update_repo'  # 本地更新仓库
ICON: Path = CODE_DIR / 'images' / 'Icons' / 'DAILY_SCHEDULE.ico'

# Nuitka 的 DLL 依赖扫描（depends.exe）在含中文的路径下会解析失败，
# 因此构建必须在纯 ASCII 路径下进行。BUILD_ROOT 即构建工作目录
# （首次使用需在其中准备 venv：把 Code/venv 复制过去即可）。
BUILD_ROOT: Path = Path(os.environ.get('SCHEDULE_BUILD_ROOT', r'D:\Schedule4Build'))

UPDATE_REPO_URL: str = 'https://gitee.com/zhao-chenyu-8633/Schedule4.0-Update.git'
UPDATE_BRANCH: str = 'main'

# 更新包只包含程序文件（不包含 Config / images / log）
# Nuitka 4.x standalone 为扁平布局：程序文件 = dist 根下除数据目录外的全部条目
# （main.exe + 各 DLL/.pyd + PySide6/ + shiboken6/）
PAYLOAD_EXCLUDES: List[str] = ['Config', 'images']

# Gitee raw 直链对超大单文件返回 403，超过阈值的更新包按字节切成 .partNNN 分片
# 存入仓库，客户端逐片下载后合并（合并结果哈希不变）。分片大小留足余量。
CHUNK_THRESHOLD: int = 10 * 1024 * 1024  # 超过 10MB 即分片
CHUNK_SIZE: int = 8 * 1024 * 1024        # 每个分片 8MB


def list_program_parts(dist: Path) -> List[str]:
    """返回 dist 中属于"程序文件"的顶层条目名（排除数据目录）。"""
    parts: List[str] = []
    for child in sorted(dist.iterdir()):
        if child.name not in PAYLOAD_EXCLUDES and child.name != 'log':
            parts.append(child.name)
    return parts

MIRROR_HINTS: str = (
    "更新包已生成，推送到 Gitee 后用户即可通过以下地址获取：\n"
    "  https://gitee.com/zhao-chenyu-8633/Schedule4.0-Update/raw/main/"
)


# ================================================================
#  工具函数
# ================================================================
def run(cmd: List[str], cwd: Path) -> None:
    """运行子进程，失败即退出。"""
    print(f"\n>>> {' '.join(str(c) for c in cmd)}\n")
    result = subprocess.run(cmd, cwd=str(cwd))
    if result.returncode != 0:
        print(f"!! 命令失败（exit={result.returncode}）：{' '.join(str(c) for c in cmd)}")
        sys.exit(result.returncode)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def parse_version(v: str) -> Tuple[int, ...]:
    parts: List[int] = []
    for seg in str(v).strip().split('.'):
        digits: str = ''.join(ch for ch in seg if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts)


def build_file_manifest(dist: Path) -> List[Dict]:
    """扫描全部程序文件，生成 [{path, sha256, size}]（相对路径用 / 分隔）。"""
    files: List[Dict] = []
    for part in list_program_parts(dist):
        src: Path = dist / part
        if not src.exists():
            print(f"!! 产物缺失：{src}")
            sys.exit(1)
        if src.is_dir():
            for p in sorted(src.rglob('*')):
                if p.is_file():
                    rel: str = p.relative_to(dist).as_posix()
                    files.append({
                        'path': rel,
                        'sha256': sha256_file(p),
                        'size': p.stat().st_size,
                    })
        else:
            rel = src.relative_to(dist).as_posix()
            files.append({'path': rel, 'sha256': sha256_file(src), 'size': src.stat().st_size})
    files.sort(key=lambda f: f['path'])
    return files


def zip_payload(dist: Path, out_zip: Path, selected: List[str]) -> None:
    """把 dist 下的 selected（相对路径，/ 分隔）打包成 zip。"""
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    if out_zip.exists():
        out_zip.unlink()
    with zipfile.ZipFile(out_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
        for rel in selected:
            src: Path = dist / rel
            if src.is_dir():
                for p in sorted(src.rglob('*')):
                    if p.is_file():
                        zf.write(p, p.relative_to(dist).as_posix())
            elif src.is_file():
                zf.write(src, rel)
    print(f"已生成更新包：{out_zip}（{out_zip.stat().st_size / 1024 / 1024:.1f} MB）")


def split_file(path: Path, chunk_size: int) -> List[Path]:
    """把大文件按字节切成 .partNNN 分片，返回分片路径列表（已写入磁盘）。"""
    parts: List[Path] = []
    idx: int = 1
    with open(path, 'rb') as f:
        while True:
            chunk: bytes = f.read(chunk_size)
            if not chunk:
                break
            part: Path = path.with_name(f"{path.name}.part{idx:03d}")
            part.write_bytes(chunk)
            parts.append(part)
            idx += 1
    return parts


def make_payload_entry(zip_path: Path, url_prefix: str, sha: str) -> Dict:
    """
    构造清单中的 full/delta 条目。
    ------------------------------
    小文件（≤ CHUNK_THRESHOLD）→ {'url', 'sha256', 'size'}；
    大文件 → 切成 parts 并删除单体文件，返回
    {'parts': [{url, sha256, size}...], 'sha256', 'size'}（sha256 为合并后哈希）。
    """
    entry: Dict = {'sha256': sha, 'size': zip_path.stat().st_size}
    if zip_path.stat().st_size > CHUNK_THRESHOLD:
        parts = split_file(zip_path, CHUNK_SIZE)
        zip_path.unlink()  # Gitee raw 无法直链下载单体大文件，仅保留分片
        entry['parts'] = [
            {'url': f"{url_prefix}{p.name}", 'sha256': sha256_file(p),
             'size': p.stat().st_size}
            for p in parts
        ]
        print(f"  {zip_path.name} 超过 {CHUNK_THRESHOLD // 1024 // 1024}MB，"
              f"已分片为 {len(parts)} 个分片（适配 Gitee raw 直链限制）")
    else:
        entry['url'] = f"{url_prefix}{zip_path.name}"
    return entry


# ================================================================
#  1. Nuitka 构建
# ================================================================
def build_nuitka(version: str) -> None:
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)

    # ---- 同步源码到 ASCII 构建目录 ----
    if not (BUILD_ROOT / 'venv' / 'Scripts' / 'python.exe').exists():
        print(f"!! 构建目录未就绪：{BUILD_ROOT}")
        print("   Nuitka 的 depends.exe 无法处理含中文的路径，必须在 ASCII 路径构建。")
        print("   请执行一次初始化（复制 venv 与源码）：")
        print(f"     robocopy {CODE_DIR / 'venv'} {BUILD_ROOT / 'venv'} /E")
        print(f"     copy *.py {BUILD_ROOT}\\")
        sys.exit(1)
    build_py: Path = BUILD_ROOT / 'venv' / 'Scripts' / 'python.exe'
    for f in CODE_DIR.glob('*.py'):
        shutil.copy2(f, BUILD_ROOT / f.name)
    # 强制使用开发环境中的 Config / images 备份（每次构建都整体覆盖，
    # 避免构建目录残留旧配置文件导致打包产物配置过期）。
    for data_dir in ('Config', 'images'):
        target: Path = BUILD_ROOT / data_dir
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(CODE_DIR / data_dir, target)
        print(f"已同步开发环境 {data_dir}/ → 构建目录（{data_dir}/）")

    jobs: int = max(1, min(8, os.cpu_count() or 4))
    cmd: List[str] = [
        str(build_py), '-m', 'nuitka',
        '--standalone',
        '--enable-plugin=pyside6',
        '--include-package=knotlink',
        f'--include-data-dir=images=images',
        f'--include-data-dir=Config=Config',
        f'--windows-icon-from-ico={ICON}',
        '--windows-console-mode=disable',
        '--company-name=Schedule',
        '--product-name=电子课表',
        f'--file-version={version}',
        '--output-dir=build',
        '--jobs=' + str(jobs),
        '--assume-yes-for-downloads',
        # 不清理 .build 缓存：保持增量构建能力（二次构建仅重编改动模块）
        'main.py',
    ]
    print("=" * 60)
    print("第 1 步：Nuitka 构建（首次约 20~40 分钟，请耐心等待）")
    print(f"        构建目录：{BUILD_ROOT}")
    print("=" * 60)
    run(cmd, BUILD_ROOT)

    # ---- 把产物复制回 Code/build/main.dist ----
    dist_src: Path = BUILD_ROOT / 'build' / 'main.dist'
    if not dist_src.exists():
        print(f"!! 构建产物不存在：{dist_src}")
        sys.exit(1)
    shutil.copytree(dist_src, DIST_DIR)
    print(f"构建完成：{DIST_DIR}")


# ================================================================
#  2. 组装 exe/ 完整运行环境
# ================================================================
def assemble_exe_env() -> None:
    print("=" * 60)
    print("第 2 步：组装 exe/ 完整运行环境（模拟用户电脑）")
    print("=" * 60)
    if EXE_DIR.exists():
        for child in EXE_DIR.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    else:
        EXE_DIR.mkdir(parents=True)

    # Nuitka 4.x standalone 为扁平布局：完整拷贝 dist 全部内容（程序文件+数据目录）
    for child in DIST_DIR.iterdir():
        dst: Path = EXE_DIR / child.name
        if child.is_dir():
            shutil.copytree(child, dst)
        else:
            shutil.copy2(child, dst)
    (EXE_DIR / 'log').mkdir(exist_ok=True)
    print(f"exe/ 运行环境已组装：{EXE_DIR}")


# ================================================================
#  3. 生成更新包 + 清单
# ================================================================
def find_previous_version(current: str) -> Optional[Tuple[str, Dict]]:
    """在 update_repo/updates/*/manifest.json 中找比当前版本旧的最高版本。"""
    updates_dir: Path = UPDATE_REPO / 'updates'
    if not updates_dir.is_dir():
        return None
    candidates: List[Tuple[Tuple[int, ...], str, Dict]] = []
    cur: Tuple[int, ...] = parse_version(current)
    for ver_dir in updates_dir.iterdir():
        if not ver_dir.is_dir():
            continue
        manifest_path: Path = ver_dir / 'manifest.json'
        if not manifest_path.exists():
            continue
        ver: str = ver_dir.name
        vtuple: Tuple[int, ...] = parse_version(ver)
        if vtuple < cur:
            try:
                data = json.loads(manifest_path.read_text(encoding='utf-8'))
                candidates.append((vtuple, ver, data))
            except Exception:  # noqa: BLE001
                continue
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0])
    best: Tuple[int, ...] = candidates[-1][0]
    # 取同版本号最新的一份
    latest_of_best: Optional[Tuple[str, Dict]] = None
    for vtuple, ver, data in candidates:
        if vtuple == best:
            latest_of_best = (ver, data)
    return latest_of_best


def generate_payloads(version: str, notes: str) -> None:
    print("=" * 60)
    print("第 3 步：生成更新包与版本清单")
    print("=" * 60)
    files: List[Dict] = build_file_manifest(DIST_DIR)

    ver_dir: Path = UPDATE_REPO / 'updates' / version
    full_zip: Path = ver_dir / f'update-{version}-full.zip'
    delta_zip: Path = ver_dir / f'update-{version}-delta.zip'

    # ---- 全量包 ----
    zip_payload(DIST_DIR, full_zip, list_program_parts(DIST_DIR))
    full_sha: str = sha256_file(full_zip)
    full_entry: Dict = make_payload_entry(full_zip, f"updates/{version}/", full_sha)

    # ---- 差分包（与上一版本对比）----
    delta_info: Dict = {}
    prev = find_previous_version(version)
    if prev is not None:
        prev_ver, prev_data = prev
        prev_files: Dict[str, str] = {
            f.get('path', ''): f.get('sha256', '') for f in (prev_data.get('files') or [])
        }
        changed: List[str] = [
            f['path'] for f in files
            if prev_files.get(f['path']) != f['sha256']
        ]
        if changed:
            # 差分包必须始终包含 main.exe（客户端暂存阶段强校验其存在）
            if 'main.exe' not in changed:
                changed.insert(0, 'main.exe')
            zip_payload(DIST_DIR, delta_zip, changed)
            delta_entry: Dict = make_payload_entry(
                delta_zip, f"updates/{version}/", sha256_file(delta_zip))
            delta_info = {'from': prev_ver}
            delta_info.update(delta_entry)
            print(f"差分包相对 {prev_ver}：{len(changed)} 个文件变化")
        else:
            print(f"相对上一版本 {prev_ver} 无文件变化，跳过差分包")
    else:
        print("无上一版本，跳过差分包（首次发布仅全量包）")

    # ---- latest.json + 版本 manifest.json ----
    latest: Dict = {
        'version': version,
        'notes': notes,
        'full': full_entry,
        'delta': delta_info or None,
        'files': files,
    }
    ver_dir.mkdir(parents=True, exist_ok=True)
    (ver_dir / 'manifest.json').write_text(
        json.dumps(latest, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    (UPDATE_REPO / 'latest.json').write_text(
        json.dumps(latest, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    print(f"已写入清单：{UPDATE_REPO / 'latest.json'}")
    print(f"文件总数：{len(files)}，全量包 SHA-256：{full_sha[:16]}…")


# ================================================================
#  4. 提交并推送更新仓库
# ================================================================
def git_ensure() -> None:
    """确保 update_repo 是一个 git 仓库且 remote 指向更新仓库。"""
    if not (UPDATE_REPO / '.git').exists():
        run(['git', 'init', '-b', UPDATE_BRANCH], UPDATE_REPO)
    remotes: str = subprocess.run(
        ['git', 'remote'], capture_output=True, text=True, cwd=str(UPDATE_REPO)
    ).stdout.strip()
    if 'origin' not in remotes.splitlines():
        run(['git', 'remote', 'add', 'origin', UPDATE_REPO_URL], UPDATE_REPO)


def git_commit_push(push: bool) -> None:
    print("=" * 60)
    print("第 4 步：提交更新仓库")
    print("=" * 60)
    git_ensure()
    run(['git', 'add', '-A'], UPDATE_REPO)
    status: str = subprocess.run(
        ['git', 'status', '--porcelain'], capture_output=True, text=True,
        cwd=str(UPDATE_REPO),
    ).stdout.strip()
    if status:
        run(['git', 'commit', '-m', 'release update'], UPDATE_REPO)
    else:
        print("无变更需要提交")
    if push:
        print("尝试推送到 Gitee...")
        result = subprocess.run(
            ['git', 'push', '-u', 'origin', UPDATE_BRANCH],
            cwd=str(UPDATE_REPO),
        )
        if result.returncode == 0:
            print("推送成功！用户端将可通过自动更新获取新版本。")
        else:
            print("!! 推送失败（可能是未配置 git 凭据或仓库尚未创建）。")
            print("   请手动执行：")
            print(f"     cd {UPDATE_REPO}")
            print(f"     git push -u origin {UPDATE_BRANCH}")
            print("   推送前请确认 Gitee 上已存在仓库 Schedule4.0-Update（可先在网页创建空仓库）。")
    else:
        print("已提交到本地更新仓库（未推送）。如需推送，请执行：")
        print(f"  cd {UPDATE_REPO}")
        print(f"  git push -u origin {UPDATE_BRANCH}")


# ================================================================
#  主流程
# ================================================================
def main() -> None:
    parser = argparse.ArgumentParser(description='Schedule4.0 一键构建 + 发布更新')
    parser.add_argument('--version', required=True, help='本次发布版本号，如 4.1.0')
    parser.add_argument('--notes', default='新版本发布，建议更新。', help='更新说明')
    parser.add_argument('--push', action='store_true', help='推送到 Gitee 更新仓库')
    parser.add_argument('--skip-build', action='store_true', help='跳过 Nuitka 构建')
    args = parser.parse_args()

    if not args.skip_build:
        build_nuitka(args.version)
    else:
        if not DIST_DIR.exists():
            print(f"!! --skip-build 但产物不存在：{DIST_DIR}")
            sys.exit(1)
        print(f"跳过构建，复用产物：{DIST_DIR}")

    assemble_exe_env()
    generate_payloads(args.version, args.notes)
    git_commit_push(args.push)

    print()
    print("=" * 60)
    print("发布流程完成 ✅")
    print("=" * 60)
    print(MIRROR_HINTS)


if __name__ == '__main__':
    main()
