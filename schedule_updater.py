"""
╔══════════════════════════════════════════════════════════════════════════╗
║        📅 电子课表系统 —— schedule_updater.py（自动更新模块）             ║
╚══════════════════════════════════════════════════════════════════════════╝

📌 本文件的作用
═══════════════════════════════════════════════════════════════════════════
实现完整的"自动更新"能力：

  1. 从 Gitee 更新仓库拉取版本清单 latest.json（多镜像源自动切换）
  2. 与当前版本比较，决定是否需要更新、走全量包还是差分包
  3. 下载更新包（带进度回调）+ SHA-256 完整性校验
  4. 解压暂存 → 交给隐藏的 PowerShell 更新器脚本（apply_update.ps1）
     在程序退出后替换程序文件（main.exe 及各 DLL/.pyd），随后自动重启

更新仓库布局（zhao-chenyu-8633/Schedule4.0-Update）：
  latest.json                    ← 版本清单（始终指向最新版）
  updates/<版本号>/
    update-<版本号>-full.zip     ← 全量更新包（全部程序文件）
    update-<版本号>-full.zip.partNNN ← 全量包分片（Gitee raw 大文件直链限制时自动分片）
    update-<版本号>-delta.zip    ← 差分更新包（仅变化的文件，可选）
    manifest.json                ← 该版本的完整文件清单（含 SHA-256）

设计要点：
  - 更新包只包含程序文件（main.exe + 各 DLL/.pyd + PySide6 包目录），
    绝不包含 Config/（用户数据）、log/、images/（背景图）。
  - 差分包优先：当清单声明 delta.from == 当前版本时下载差分包，
    否则回退全量包。
  - 多镜像源：Gitee raw 直链（国内节点，可达性好），失败自动降级，
    适配国内网络。
  - 所有网络请求设置 UA 与超时，失败静默降级，绝不影响课表主功能。
"""

import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QThread, Signal

from app_paths import app_root, is_frozen

logger: logging.Logger = logging.getLogger(__name__)

# ================================================================
#  ★ 更新仓库配置 ★
# ================================================================
UPDATE_REPO_OWNER: str = "zhao-chenyu-8633"
UPDATE_REPO_NAME: str = "Schedule4.0-Update"
UPDATE_REPO_BRANCH: str = "main"
MANIFEST_NAME: str = "latest.json"

# 多镜像源（按顺序尝试，第一个成功的即采用）
# Gitee raw 直链为国内节点，可达性好；更新仓库必须为 Public 才能匿名访问。
# 后续如需增强容灾，可在此追加其它镜像（如 Cloudflare R2 自定义域名直链）。
BASE_URLS: List[str] = [
    f"https://gitee.com/{UPDATE_REPO_OWNER}/{UPDATE_REPO_NAME}/raw/{UPDATE_REPO_BRANCH}/",
]

HTTP_TIMEOUT: int = 30
MANIFEST_TIMEOUT: int = 15  # 清单很小，超时更短，加快镜像切换
USER_AGENT: str = "Schedule4.0-Updater/1.0"


# ================================================================
#  版本号工具
# ================================================================
def parse_version(version: str) -> Tuple[int, ...]:
    """把 '4.1.0' / '4.0.0.0' 解析为整数元组，用于逐段比较。"""
    parts: List[int] = []
    for seg in str(version).strip().split('.'):
        digits: str = ''.join(ch for ch in seg if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    # 补零对齐，保证 4.1.0 == 4.1.0.0
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts)


def is_newer(latest: str, current: str) -> bool:
    """latest 是否比 current 新。"""
    return parse_version(latest) > parse_version(current)


# ================================================================
#  数据模型
# ================================================================
@dataclass
class UpdateInfo:
    """解析后的更新清单信息。"""
    version: str = ''
    notes: str = ''
    full_url: str = ''
    full_sha256: str = ''
    full_size: int = 0
    full_parts: List[Dict[str, Any]] = field(default_factory=list)  # [{url, sha256, size}]
    delta_from: Optional[str] = None
    delta_url: Optional[str] = None
    delta_sha256: Optional[str] = None
    delta_size: int = 0
    delta_parts: List[Dict[str, Any]] = field(default_factory=list)  # [{url, sha256, size}]
    files: List[Dict[str, Any]] = field(default_factory=list)  # [{path, sha256, size}]

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'UpdateInfo':
        full: Dict[str, Any] = data.get('full') or {}
        delta: Dict[str, Any] = data.get('delta') or {}
        return UpdateInfo(
            version=str(data.get('version', '')),
            notes=str(data.get('notes', '')),
            full_url=str(full.get('url', '')),
            full_sha256=str(full.get('sha256', '')),
            full_size=int(full.get('size', 0) or 0),
            full_parts=list(full.get('parts') or []),
            delta_from=str(delta.get('from')) if delta.get('from') else None,
            delta_url=str(delta.get('url', '')),
            delta_sha256=str(delta.get('sha256', '')),
            delta_size=int(delta.get('size', 0) or 0),
            delta_parts=list(delta.get('parts') or []),
            files=list(data.get('files') or []),
        )


# ================================================================
#  网络 / 文件工具
# ================================================================
def _http_get(url: str, timeout: int) -> bytes:
    """GET 请求，带 UA 与超时；失败抛异常。"""
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.read()


def fetch_json(url: str) -> Optional[Dict[str, Any]]:
    """拉取并解析 JSON（清单专用：短超时），失败返回 None。"""
    try:
        raw: bytes = _http_get(url, MANIFEST_TIMEOUT)
        data = json.loads(raw.decode('utf-8-sig'))
        return data if isinstance(data, dict) else None
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"拉取 JSON 失败：{url} → {exc}")
        return None


def _abs_url(base: str, url: str) -> str:
    """把清单里的相对路径补全为绝对 URL（下载阶段需要完整地址）。"""
    if url.startswith('http://') or url.startswith('https://'):
        return url
    return base + url.lstrip('/')


def fetch_manifest() -> Tuple[Optional[UpdateInfo], Optional[str]]:
    """
    按镜像顺序拉取最新清单。
    ------------------------
    返回 (UpdateInfo|None, error|None)。
    清单内的相对 URL 会基于成功拉取的镜像源补全为绝对地址。
    """
    last_error: str = ''
    for base in BASE_URLS:
        url: str = base + MANIFEST_NAME
        data = fetch_json(url)
        if data is not None:
            logger.info(f"更新清单拉取成功：{url}")
            info: UpdateInfo = UpdateInfo.from_dict(data)
            if info.full_url:
                info.full_url = _abs_url(base, info.full_url)
            if info.delta_url:
                info.delta_url = _abs_url(base, info.delta_url)
            for part in info.full_parts:
                part['url'] = _abs_url(base, str(part.get('url', '')))
            for part in info.delta_parts:
                part['url'] = _abs_url(base, str(part.get('url', '')))
            return info, None
        last_error = f"所有镜像源均不可达（最后尝试：{url}）"
    return None, last_error


def sha256_file(path: str) -> str:
    """计算文件 SHA-256（分块读取，兼容大文件）。"""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def download_file(url: str, dest: str,
                  progress_cb: Optional[Callable[[int, int], None]] = None) -> bool:
    """
    下载文件到 dest，支持进度回调 (已下载字节, 总字节)。
    成功返回 True；失败返回 False（不抛异常）。
    """
    try:
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:  # noqa: S310
            total: int = int(resp.headers.get('Content-Length') or 0)
            done: int = 0
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, 'wb') as f:
                while True:
                    chunk = resp.read(1024 * 256)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if progress_cb is not None:
                        progress_cb(done, total)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error(f"下载失败：{url} → {exc}")
        try:
            if os.path.exists(dest):
                os.remove(dest)
        except OSError:
            pass
        return False


def download_payload(payload: Dict[str, Any], dest: str,
                     progress_cb: Optional[Callable[[int, int], None]] = None) -> bool:
    """
    下载更新包到 dest。
    ------------------
    payload 可为 {'url', 'sha256', 'size'}（单体文件）
    或 {'parts': [{url, sha256, size}...], 'sha256', 'size'}（分片下载后合并，
    合并结果即完整 zip，仍按 sha256 校验）。成功返回 True。
    """
    parts: List[Dict[str, Any]] = list(payload.get('parts') or [])
    if parts:
        total: int = sum(int(p.get('size') or 0) for p in parts)
        done: int = 0
        part_files: List[str] = []
        try:
            for i, part in enumerate(parts):
                part_path: str = f"{dest}.part{i + 1}"
                part_files.append(part_path)
                base_done: int = done

                def part_cb(d: int, t: int, _base: int = base_done) -> None:
                    if progress_cb is not None:
                        progress_cb(_base + d, total)

                if not download_file(str(part.get('url', '')), part_path, part_cb):
                    return False
                done += int(part.get('size') or 0)
            # 按序合并分片为完整 zip
            with open(dest, 'wb') as out:
                for pf in part_files:
                    with open(pf, 'rb') as f:
                        shutil.copyfileobj(f, out, 1024 * 1024)
            return True
        except OSError as exc:
            logger.error(f"合并分片失败：{exc}")
            return False
        finally:
            for pf in part_files:
                try:
                    if os.path.exists(pf):
                        os.remove(pf)
                except OSError:
                    pass
    url: str = str(payload.get('url') or '')
    if not url:
        logger.error("更新包清单缺少 url 与 parts")
        return False
    return download_file(url, dest, progress_cb)


# ================================================================
#  更新包选择 / 暂存 / 应用
# ================================================================
def pick_payload(info: UpdateInfo, current_version: str) -> Tuple[Dict[str, Any], bool]:
    """
    根据当前版本选择下载目标。
    --------------------------
    返回 (payload, is_delta)。payload 形如：
      {'url': ..., 'sha256': ..., 'size': ...} 或
      {'parts': [{url, sha256, size}...], 'sha256': ..., 'size': ...}
    清单声明 delta.from == 当前版本 → 用差分包；否则用全量包。
    """
    if (info.delta_from is not None and info.delta_url
            and parse_version(info.delta_from) == parse_version(current_version)):
        return {'url': info.delta_url, 'sha256': info.delta_sha256,
                'size': info.delta_size, 'parts': info.delta_parts}, True
    return {'url': info.full_url, 'sha256': info.full_sha256,
            'size': info.full_size, 'parts': info.full_parts}, False


def _verify_staged_files(stage_dir: str, files: List[Dict[str, Any]]) -> Tuple[bool, str]:
    """按清单校验暂存区内的文件（只校验存在文件，差分包只含部分文件）。"""
    for item in files:
        rel: str = str(item.get('path', ''))
        if not rel:
            continue
        local: str = os.path.join(stage_dir, rel.replace('/', os.sep))
        if not os.path.isfile(local):
            continue  # 差分包中不含该文件，跳过
        actual: str = sha256_file(local)
        expected: str = str(item.get('sha256', ''))
        if expected and actual.lower() != expected.lower():
            return False, f"文件校验失败：{rel}"
    return True, ''


def stage_update(zip_path: str, info: UpdateInfo,
                 app_dir: str, is_delta: bool = False) -> Tuple[bool, str]:
    """
    解压更新包到 _update/ 暂存区，并生成隐藏的 PowerShell 应用脚本。
    ----------------------------------------------------------------
    成功返回 (True, '')；失败返回 (False, 原因)。
    注意：本函数只做"暂存"，真正的替换由 apply_update.ps1 在程序退出后执行。
    is_delta=True 表示差分包（应用时合并覆盖，不整体删除）。
    """
    updater_dir: str = os.path.join(app_dir, '_update')
    stage_dir: str = os.path.join(updater_dir, 'staging')
    try:
        # 清理旧的暂存区
        if os.path.exists(updater_dir):
            shutil.rmtree(updater_dir, ignore_errors=True)
        os.makedirs(stage_dir, exist_ok=True)

        # 解压
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(stage_dir)

        # 完整性校验（按清单）
        ok, err = _verify_staged_files(stage_dir, info.files)
        if not ok:
            return False, err

        # 关键文件必须存在（Nuitka 4.x 扁平布局：程序文件均在包根，main.exe 为入口）
        new_exe: str = os.path.join(stage_dir, 'main.exe')
        if not os.path.isfile(new_exe):
            return False, f"更新包缺少 main.exe：{new_exe}"

        # 写入更新类型标记（full=整体替换，delta=合并）
        with open(os.path.join(updater_dir, 'type.txt'), 'w', encoding='utf-8') as f:
            f.write('delta' if is_delta else 'full')

        # 写入目标版本号（供更新器脚本更新 Config/schedule_config.ini 的 version 键，
        # 避免更新后配置文件版本号仍是旧值导致反复触发更新下载）
        with open(os.path.join(updater_dir, 'version.txt'), 'w', encoding='utf-8') as f:
            f.write(str(info.version).strip())

        # 生成 PowerShell 应用脚本
        ps_script: str = os.path.join(updater_dir, 'apply_update.ps1')
        with open(ps_script, 'w', encoding='utf-8-sig', newline='\r\n') as f:
            f.write(_APPLY_SCRIPT)
        logger.info(f"更新暂存完成：{updater_dir}（{'差分' if is_delta else '全量'}）")
        return True, ''
    except Exception as exc:  # noqa: BLE001
        logger.error(f"更新暂存失败：{exc}")
        return False, f"更新暂存失败：{exc}"


_APPLY_SCRIPT: str = r"""# -*- coding: utf-8 -*-
# Schedule4.0 更新器 —— 由 schedule_updater.py 自动生成，程序退出后执行
param([Parameter(Mandatory = $true)][int]$AppPid)

$ErrorActionPreference = 'Stop'
$appDir = Split-Path -Parent $PSScriptRoot
$stage  = Join-Path $appDir '_update\staging'
$logDir = Join-Path $appDir 'log'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir 'updater.log'

function Write-Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    try { Add-Content -Path $log -Value $line -Encoding UTF8 } catch {}
}

Write-Log '更新器启动，等待主程序退出...'
Start-Sleep -Milliseconds 800

# 等待主程序完全退出（最多 5 分钟）
$deadline = (Get-Date).AddMinutes(5)
while ((Get-Process -Id $AppPid -ErrorAction SilentlyContinue) -and ((Get-Date) -lt $deadline)) {
    Start-Sleep -Milliseconds 300
}

try {
    # ---- 1. 替换 main.exe（旧 exe 先改名备份）----
    $exe = Join-Path $appDir 'main.exe'
    $exeOld = Join-Path $appDir 'main.exe.old'
    if (Test-Path $exeOld) { Remove-Item -Force $exeOld }
    if (Test-Path $exe)    { Move-Item -Force $exe $exeOld }
    Copy-Item -Force (Join-Path $stage 'main.exe') $exe
    Write-Log 'main.exe 已替换'

    # ---- 2. 更新其他程序文件（Nuitka 扁平布局：程序文件与 Config/images/log 并列）----
    $typeFile = Join-Path $PSScriptRoot 'type.txt'
    $updateType = 'full'
    if (Test-Path $typeFile) { $updateType = (Get-Content $typeFile -Raw).Trim() }
    if ($updateType -eq 'full') {
        # 全量：旧程序文件移入备份区，再整体拷贝新文件（可回滚）
        $backup = Join-Path $appDir '_update\old_program'
        New-Item -ItemType Directory -Force -Path $backup | Out-Null
        Get-ChildItem $appDir -Force | Where-Object {
            $_.Name -notin @('Config','images','log','_update','main.exe','main.exe.old')
        } | ForEach-Object {
            Move-Item -Force $_.FullName (Join-Path $backup $_.Name)
        }
        Copy-Item -Recurse -Force (Join-Path $stage '*') $appDir
        Write-Log '程序文件已整体替换（full）'
    } else {
        # 差分：变化文件合并覆盖到现有程序文件上
        Copy-Item -Recurse -Force (Join-Path $stage '*') $appDir
        Write-Log '程序文件已合并更新（delta）'
    }

    # ---- 2.5 同步 Config/schedule_config.ini 的 version 键为最新版本 ----
    # 更新包不包含 Config/（用户数据），若不更新版本号会导致客户端
    # 每次启动都认为有新版本，反复下载更新。
    $verFile = Join-Path $PSScriptRoot 'version.txt'
    $iniPath = Join-Path $appDir 'Config\schedule_config.ini'
    if (Test-Path $verFile) {
        $newVer = (Get-Content $verFile -Raw).Trim()
        if (Test-Path $iniPath) {
            $lines = Get-Content $iniPath -Encoding UTF8
            $updated = $false
            $out = @()
            foreach ($line in $lines) {
                $stripped = $line.TrimStart()
                if ($stripped -and -not $stripped.StartsWith(';') -and -not $stripped.StartsWith('#') -and $line -match '=') {
                    $key = ($line -split '=', 2)[0].Trim()
                    if ($key -eq 'version' -and -not $updated) {
                        $out += "version = $newVer"
                        $updated = $true
                        continue
                    }
                }
                $out += $line
            }
            if (-not $updated) { $out += "version = $newVer" }
            # 保持 UTF-8 无 BOM 写入（与程序读取方式一致）
            [System.IO.File]::WriteAllLines($iniPath, $out, (New-Object System.Text.UTF8Encoding($false)))
            Write-Log ("Config 版本号已更新为 " + $newVer)
        } else {
            Write-Log ('Config 配置文件不存在，跳过版本号更新：' + $iniPath)
        }
    }

    # ---- 3. 重新启动主程序 ----
    Start-Process -FilePath $exe -WorkingDirectory $appDir
    Write-Log '新版本已启动'

    # ---- 4. 清理 ----
    Remove-Item -Recurse -Force (Join-Path $appDir '_update')
    if (Test-Path $exeOld) { Remove-Item -Force $exeOld }
    Write-Log '更新完成，清理临时文件'
}
catch {
    Write-Log ("更新失败：" + $_.Exception.Message)
    # 回滚：恢复备份的程序文件与旧 exe
    $backup = Join-Path $appDir '_update\old_program'
    if (Test-Path $backup) {
        Get-ChildItem $backup -Force | ForEach-Object {
            Move-Item -Force $_.FullName (Join-Path $appDir $_.Name)
        }
        Write-Log '已从备份恢复程序文件'
    }
    $exeOld = Join-Path $appDir 'main.exe.old'
    if ((Test-Path $exeOld) -and -not (Test-Path (Join-Path $appDir 'main.exe'))) {
        Move-Item -Force $exeOld (Join-Path $appDir 'main.exe')
        Write-Log '已恢复旧版 main.exe'
    }
}
"""


def launch_updater(app_dir: str, pid: int) -> bool:
    """以隐藏窗口启动 PowerShell 更新器，然后由调用方退出主程序。"""
    ps_script: str = os.path.join(app_dir, '_update', 'apply_update.ps1')
    if not os.path.isfile(ps_script):
        logger.error(f"更新器脚本不存在：{ps_script}")
        return False
    try:
        creation_flags: int = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        subprocess.Popen(
            ['powershell.exe', '-NoProfile', '-WindowStyle', 'Hidden',
             '-ExecutionPolicy', 'Bypass', '-File', ps_script, str(pid)],
            cwd=app_dir, creationflags=creation_flags,
        )
        logger.info("更新器已启动，等待主程序退出后替换文件")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error(f"启动更新器失败：{exc}")
        return False


# ================================================================
#  QThread 工作线程（供设置窗口 / main.py 使用）
# ================================================================
class UpdateWorker(QThread):
    """后台更新线程。

    用法：
      worker = UpdateWorker(task=UpdateWorker.TASK_CHECK,
                            current_version=theme.version)
      worker.check_done.connect(on_check_done)
      worker.start()
      # 必须持有 worker 引用，防止被 GC
    """

    TASK_CHECK: str = 'check'
    TASK_APPLY: str = 'apply'

    # 检查完成：signal(UpdateInfo|None, error:str)
    check_done = Signal(object, str)
    # 下载进度：signal(已下载, 总字节)
    progress = Signal(int, int)
    # 应用完成：signal(是否已启动更新器, 错误信息)
    apply_done = Signal(bool, str)

    def __init__(self, task: str, info: Optional[UpdateInfo] = None,
                 current_version: str = '', parent: Optional[Any] = None) -> None:
        super().__init__(parent)
        self._task: str = task
        self._info: Optional[UpdateInfo] = info
        self._current_version: str = current_version

    # ------------------------------------------------------------------
    def run(self) -> None:  # noqa: C901
        if self._task == self.TASK_CHECK:
            self._run_check()
        elif self._task == self.TASK_APPLY:
            self._run_apply()
        else:
            self.check_done.emit(None, f"未知任务：{self._task}")

    def _run_check(self) -> None:
        info, error = fetch_manifest()
        self.check_done.emit(info, error)

    def _run_apply(self) -> None:
        if self._info is None:
            self.apply_done.emit(False, "缺少更新信息")
            return
        app_dir: str = app_root()
        try:
            # 1. 选择下载目标
            payload, is_delta = pick_payload(self._info, self._current_version)
            show_url: str = str(payload.get('url') or '')
            if not show_url:
                part_list: List[Dict[str, Any]] = list(payload.get('parts') or [])
                if part_list:
                    show_url = str(part_list[0].get('url', ''))
            logger.info(f"开始下载更新包（{'差分' if is_delta else '全量'}）：{show_url}")

            # 2. 下载（带进度；大文件按分片下载后合并）
            tmp_zip: str = os.path.join(app_dir, '_update_tmp.zip')
            if os.path.exists(tmp_zip):
                os.remove(tmp_zip)
            ok: bool = download_payload(payload, tmp_zip, self.progress.emit)
            if not ok:
                self.apply_done.emit(False, "下载更新包失败，请检查网络后重试")
                return

            # 3. 校验 SHA-256
            actual: str = sha256_file(tmp_zip)
            sha256: str = str(payload.get('sha256') or '')
            if sha256 and actual.lower() != sha256.lower():
                logger.error(f"SHA-256 校验失败：期望 {sha256}，实际 {actual}")
                self.apply_done.emit(False, "更新包校验失败（文件可能被篡改），已中止")
                return

            # 4. 解压暂存 + 生成更新器脚本
            ok, err = stage_update(tmp_zip, self._info, app_dir, is_delta=is_delta)
            if not ok:
                self.apply_done.emit(False, err)
                return

            # 5. 清理临时 zip
            try:
                os.remove(tmp_zip)
            except OSError:
                pass

            # 6. 启动更新器（隐藏 PowerShell），随后调用方退出主程序
            pid: int = os.getpid()
            launched: bool = launch_updater(app_dir, pid)
            self.apply_done.emit(launched, '' if launched else "启动更新器失败")
        except Exception as exc:  # noqa: BLE001
            logger.exception("应用更新过程发生异常")
            self.apply_done.emit(False, f"更新过程异常：{exc}")


# ================================================================
#  便捷函数（供脚本/调试使用）
# ================================================================
def check_for_update(current_version: str) -> Tuple[Optional[UpdateInfo], Optional[str]]:
    """同步检查更新（阻塞），返回 (info, error)。"""
    return fetch_manifest()


if __name__ == '__main__':
    # 手动调试：python schedule_updater.py
    info, error = check_for_update('4.0.0.0')
    if error:
        print(f"检查失败：{error}")
    elif info is None:
        print("未发现更新")
    else:
        print(f"最新版本：{info.version}")
        print(f"全量包：{info.full_url}（{info.full_size} 字节）")
        print(f"差分包：{info.delta_from} → {info.delta_url}" if info.delta_url else "无差分包")
        print(f"是否可更新：{is_newer(info.version, '4.0.0.0')}")
