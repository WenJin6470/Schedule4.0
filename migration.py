r"""
╔══════════════════════════════════════════════════════════════════════════╗
║    📅 电子课表系统 —— migration.py（安装目录迁移：Schedule → Schedule4.0）║
╚══════════════════════════════════════════════════════════════════════════╝

📌 背景
═══════════════════════════════════════════════════════════════════════════
  4.1.6 起，安装包默认安装目录由
      D:\Program Files (x86)\Combox\Digital Class\Schedule
  规范化为
      D:\Program Files (x86)\Combox\Digital Class\Schedule4.0

  对已安装在旧目录、通过自动更新升级到 4.1.6+ 的用户：
    1. 旧版本更新器先完成程序文件替换（此时仍位于旧目录）；
    2. 4.1.6 首次启动时，migrate_install_dir_if_needed() 检测到旧目录，
       启动隐藏的 PowerShell 迁移助手后主动退出；
    3. 迁移助手等待主程序退出，把末级文件夹 Schedule 重命名为
       Schedule4.0，修正注册表（安装位置、自启动 Run 键）与
       桌面/开始菜单快捷方式，然后从新目录重启程序。

📌 双保险
═══════════════════════════════════════════════════════════════════════════
  同一份 PowerShell 脚本（MIGRATE_DIR_SCRIPT）由 publish_update.py 写入
  自动更新仓库（updates/<版本>/migrate_dir.ps1），更新器（4.1.6+）
  会在替换程序文件后执行它；两者共用同一逻辑，防止个别用户启动时
  未触发迁移而残留旧目录。

⚠️ 本模块禁止 import PySide6 等重依赖，保证构建/发布脚本可安全复用。
"""

import logging
import os
import subprocess
import sys
import tempfile
import time

from app_paths import app_root, is_frozen

logger: logging.Logger = logging.getLogger('migration')

# 旧默认安装目录（4.1.5 及之前）与新默认安装目录（4.1.6 起）
LEGACY_INSTALL_DIR: str = r'D:\Program Files (x86)\Combox\Digital Class\Schedule'
NEW_INSTALL_DIR: str = r'D:\Program Files (x86)\Combox\Digital Class\Schedule4.0'

# 迁移脚本文件名（更新仓库与临时目录共用）
MIGRATE_SCRIPT_NAME: str = 'migrate_dir.ps1'

# 迁移失败的最大尝试次数：超过后不再自动迁移，避免“启动→退出→重启”死循环
MAX_MIGRATE_ATTEMPTS: int = 3


def _norm_path(path: str) -> str:
    """规范化路径：绝对化 + 去掉末尾分隔符，用于比较。"""
    try:
        return os.path.normpath(os.path.abspath(str(path))).rstrip('\\/')
    except Exception:  # noqa: BLE001
        return str(path).rstrip('\\/')


def _to_long_path(path: str) -> str:
    """把 Windows 8.3 短路径转换为长路径（转换失败时原样返回）。"""
    try:
        import ctypes  # noqa: PLC0415
        buf = ctypes.create_unicode_buffer(4096)
        length = ctypes.windll.kernel32.GetLongPathNameW(path, buf, len(buf))
        if 0 < length < len(buf):
            return buf.value
    except Exception:  # noqa: BLE001
        pass
    return path


def _attempts_path(app_dir: str) -> str:
    """迁移失败计数字文件（位于安装目录内，随重命名一起移动）。"""
    return os.path.join(app_dir, 'migrate_attempts.txt')


def needs_migration(app_dir: str) -> bool:
    """
    判断给定目录是否需要进行“Schedule → Schedule4.0”迁移。
    ----------------------------------------------------
    仅当目录恰好等于旧默认安装目录（大小写不敏感）且迁移失败次数
    未达到上限时返回 True。
    """
    if not app_dir:
        return False
    actual: str = _norm_path(_to_long_path(app_dir))
    legacy: str = _norm_path(LEGACY_INSTALL_DIR)
    if actual.lower() != legacy.lower():
        return False
    # 新目录已存在（例如用户同时安装了两份）：不迁移，避免覆盖另一份安装
    if os.path.isdir(_norm_path(NEW_INSTALL_DIR)):
        logger.warning(
            f"新安装目录已存在（{NEW_INSTALL_DIR}），跳过旧目录迁移：{actual}"
        )
        return False
    attempts: int = 0
    try:
        with open(_attempts_path(actual), 'r', encoding='utf-8') as f:
            attempts = int((f.read() or '').strip() or 0)
    except Exception:  # noqa: BLE001
        attempts = 0
    if attempts >= MAX_MIGRATE_ATTEMPTS:
        logger.warning(
            f"安装目录迁移已失败 {attempts} 次，达到上限，本次不再尝试：{actual}"
        )
        return False
    return True


def _write_migrate_script(dest: str) -> None:
    """把迁移脚本写入 dest（UTF-8 BOM + CRLF，Windows PowerShell 可读）。"""
    with open(dest, 'w', encoding='utf-8-sig', newline='\r\n') as f:
        f.write(MIGRATE_DIR_SCRIPT)


def migrate_install_dir_if_needed() -> bool:
    """
    启动时调用：若当前位于旧默认安装目录，则启动隐藏 PowerShell 迁移助手
    并返回 True（调用方应立即退出程序，由迁移助手完成重命名后重启）。
    否则返回 False（程序正常继续启动）。
    """
    if not is_frozen():
        return False
    # ★ 必须转换为长路径：Nuitka 下 sys.executable 可能返回 8.3 短路径
    #   （如 D:\PROGRA~2\...），短路径会导致迁移脚本与旧目录匹配失败
    #   （4.1.6 首次发布事故的根因）。needs_migration 内部比较已做转换，
    #   这里转换后再传给迁移脚本，保证脚本收到的也是长路径。
    app_dir: str = _to_long_path(app_root())
    if not needs_migration(app_dir):
        return False
    try:
        work_dir: str = os.path.join(tempfile.gettempdir(), 'Schedule4.0-Migrate')
        os.makedirs(work_dir, exist_ok=True)
        script: str = os.path.join(work_dir, MIGRATE_SCRIPT_NAME)
        _write_migrate_script(script)
        creation_flags: int = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        proc = subprocess.Popen(
            ['powershell.exe', '-NoProfile', '-WindowStyle', 'Hidden',
             '-ExecutionPolicy', 'Bypass', '-File', script,
             '-AppDir', app_dir, '-AppPid', str(os.getpid())],
            cwd=work_dir, creationflags=creation_flags,
        )
        # 存活确认：迁移助手会等待本进程退出（至少数秒）。若 3 秒内
        # 助手进程已经消失，说明其启动即失败——放弃迁移并继续正常运行，
        # 避免“程序退出后无人重启”（4.1.6 首次发布事故的另一根因）。
        time.sleep(3)
        if proc.poll() is not None:
            logger.warning(
                f"迁移助手启动后立即退出（exit={proc.returncode}），"
                f"放弃本次迁移，按原目录继续运行"
            )
            return False
        logger.info(
            f"检测到旧安装目录 {app_dir}，迁移助手已启动，"
            f"程序将退出并在迁移完成后从新目录自动重启"
        )
        return True
    except Exception:  # noqa: BLE001
        logger.exception("启动迁移助手失败，程序按原目录继续运行")
        return False


# ================================================================
#  目录迁移 PowerShell 脚本（唯一权威版本，publish_update.py 复用）
# ================================================================
MIGRATE_DIR_SCRIPT: str = r"""# -*- coding: utf-8 -*-
# Schedule4.0 安装目录迁移脚本（Schedule → Schedule4.0）
# 由 migration.py 生成 / 自动更新仓库分发，在主程序退出后执行。
param(
    [Parameter(Mandatory = $true)][string]$AppDir,
    [Parameter(Mandatory = $true)][int]$AppPid,
    [string]$LegacyPath = 'D:\Program Files (x86)\Combox\Digital Class\Schedule',
    [string]$NewName = 'Schedule4.0'
)

$ErrorActionPreference = 'Continue'

# 把路径统一转换为长路径（Windows 8.3 短路径 → 长路径）。
# 调用方可能传入短路径（如 D:\PROGRA~2\...），必须转换后才能与
# 旧目录常量可靠比对；转换失败时原样返回。
function Get-LongPath([string]$p) {
    try {
        if (-not ('Win32PathConv' -as [type])) {
            Add-Type -Namespace Win32 -Name PathConv -MemberDefinition @'
[DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
public static extern uint GetLongPathNameW(string lpszShortPath, System.Text.StringBuilder lpszLongPath, uint cchBuffer);
'@
        }
        $sb = New-Object System.Text.StringBuilder 1024
        $null = [Win32.PathConv]::GetLongPathNameW($p, $sb, 1024)
        if ($sb.Length -gt 0) { return $sb.ToString() }
    } catch {}
    return $p
}

$appDir = (Get-LongPath $AppDir).TrimEnd('\')
$legacy = (Get-LongPath $LegacyPath).TrimEnd('\')
$newDir = Join-Path (Split-Path -Parent $legacy) $NewName
$logDir = Join-Path $appDir 'log'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir 'migrate.log'

function Write-Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    try { Add-Content -Path $log -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue } catch {}
}

Write-Log ("迁移脚本启动：AppDir=" + $appDir)

# ---- 1. 仅当处于旧默认安装目录时才迁移（PowerShell -eq 大小写不敏感）----
if (-not ($appDir -eq $legacy)) {
    Write-Log '当前目录不是旧默认安装目录，无需迁移'
    # ★ 主程序可能已退出并等待本脚本重启它：任何退出分支都必须负责重启，
    #   否则会出现“程序退出后无人拉起”（双击无反应）。
    if ($AppPid -gt 0 -and (Test-Path -LiteralPath (Join-Path $appDir 'main.exe'))) {
        Start-Process -FilePath (Join-Path $appDir 'main.exe') -WorkingDirectory $appDir
        Write-Log '已按原目录重启主程序'
    }
    exit 0
}

# ---- 2. 目标目录已存在则放弃（避免覆盖/合并另一份安装）----
if (Test-Path -LiteralPath $newDir) {
    Write-Log ("目标目录已存在，跳过迁移：" + $newDir)
    if ($AppPid -gt 0) {
        Start-Process -FilePath (Join-Path $appDir 'main.exe') -WorkingDirectory $appDir
    }
    exit 0
}

# ---- 3. 等待主程序完全退出（最多 5 分钟）----
if ($AppPid -gt 0) {
    $deadline = (Get-Date).AddMinutes(5)
    while ((Get-Process -Id $AppPid -ErrorAction SilentlyContinue) -and ((Get-Date) -lt $deadline)) {
        Start-Sleep -Milliseconds 300
    }
}

# ---- 4. 把当前工作目录移出安装目录，释放目录句柄（否则重命名会失败）----
try { Set-Location $env:TEMP } catch {}

# ---- 5. 重命名末级文件夹 Schedule → Schedule4.0 ----
$moved = $false
try {
    Rename-Item -LiteralPath $appDir -NewName $NewName -ErrorAction Stop
    # 目录已移动：日志文件随之移动到新目录，重新指向日志路径
    $log = Join-Path (Join-Path $newDir 'log') 'migrate.log'
    Write-Log ("目录重命名成功：" + $appDir + "  ->  " + $newDir)
    $moved = $true
} catch {
    Write-Log ("目录重命名失败：" + $_.Exception.Message)
}

$exe = $null
if ($moved) {
    $exe = Join-Path $newDir 'main.exe'

    # ---- 6. 修正注册表安装位置（HKLM，失败不阻断迁移）----
    try {
        $regKey = 'HKLM:\Software\Schedule\Schedule4.0'
        if (Test-Path $regKey) {
            Set-ItemProperty -Path $regKey -Name 'InstallLocation' -Value $newDir
        }
        $unKey = 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Schedule4.0'
        if (Test-Path $unKey) {
            Set-ItemProperty -Path $unKey -Name 'InstallLocation' -Value $newDir
            Set-ItemProperty -Path $unKey -Name 'UninstallString' -Value (Join-Path $newDir 'Uninstall.exe')
            Set-ItemProperty -Path $unKey -Name 'DisplayIcon' -Value (Join-Path $newDir 'images\Icons\DAILY_SCHEDULE.ico')
        }
        Write-Log '注册表安装位置已修正'
    } catch {
        Write-Log ("注册表修正失败（忽略）：" + $_.Exception.Message)
    }

    # ---- 7. 修正开机自启动 Run 键（HKCU，仅当仍指向旧目录）----
    try {
        $runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
        $props = Get-ItemProperty -Path $runKey -Name 'Schedule4.0' -ErrorAction Stop
        $cmd = [string]$props.'Schedule4.0'
        $oldExe = Join-Path $appDir 'main.exe'
        if ($cmd -and (($cmd.Trim().Trim('"')) -eq $oldExe)) {
            Set-ItemProperty -Path $runKey -Name 'Schedule4.0' -Value ('"' + $exe + '"')
            Write-Log '开机自启动 Run 键已修正'
        }
    } catch {}

    # ---- 8. 修正桌面 / 开始菜单快捷方式（仅限指向旧目录的）----
    function Fix-Lnk($lnkPath) {
        if (-not (Test-Path -LiteralPath $lnkPath)) { return }
        try {
            $sh = New-Object -ComObject WScript.Shell
            $lnk = $sh.CreateShortcut($lnkPath)
            $target = [string]$lnk.TargetPath
            if ($target -and (($target | Split-Path -Parent).TrimEnd('\') -eq $appDir)) {
                $lnk.TargetPath = Join-Path $newDir (Split-Path -Leaf $target)
                $lnk.WorkingDirectory = $newDir
                $icon = [string]$lnk.IconLocation
                if ($icon -and $icon.StartsWith($appDir, [System.StringComparison]::OrdinalIgnoreCase)) {
                    $idx = $icon.LastIndexOf(',')
                    $iconPath = $icon
                    $iconIndex = ''
                    if ($idx -gt 0) {
                        $iconPath = $icon.Substring(0, $idx)
                        $iconIndex = $icon.Substring($idx)
                    }
                    $rel = $iconPath.Substring($appDir.Length).TrimStart('\')
                    $lnk.IconLocation = (Join-Path $newDir $rel) + $iconIndex
                }
                $lnk.Save()
                Write-Log ("快捷方式已修正：" + $lnkPath)
            }
        } catch {}
    }
    Fix-Lnk (Join-Path $env:USERPROFILE 'Desktop\电子课表4.0.lnk')
    Fix-Lnk (Join-Path $env:PUBLIC 'Desktop\电子课表4.0.lnk')
    Fix-Lnk (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\电子课表4.0\电子课表4.0.lnk')
    Fix-Lnk (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\电子课表4.0\卸载电子课表4.0.lnk')

    # ---- 9. 移除迁移失败计数字文件（迁移已成功）----
    Remove-Item -Force (Join-Path $newDir 'migrate_attempts.txt') -ErrorAction SilentlyContinue
} else {
    # ---- 10. 重命名失败：记录尝试次数（防止反复重启循环），回到旧目录启动 ----
    try {
        $countFile = Join-Path $appDir 'migrate_attempts.txt'
        $count = 0
        if (Test-Path -LiteralPath $countFile) {
            try { $count = [int](Get-Content -LiteralPath $countFile -Raw).Trim() } catch { $count = 0 }
        }
        $count = $count + 1
        Set-Content -LiteralPath $countFile -Value ([string]$count) -Encoding UTF8
        Write-Log ("迁移失败次数：" + $count)
    } catch {}
    $exe = Join-Path $appDir 'main.exe'
}

# ---- 11. 重启主程序（AppPid=0 为测试模式，跳过等待与重启）----
if ($AppPid -gt 0 -and $exe -and (Test-Path -LiteralPath $exe)) {
    Start-Process -FilePath $exe -WorkingDirectory (Split-Path -Parent $exe)
    Write-Log ("已启动主程序：" + $exe)
}

# ---- 12. 清理更新残留（新旧两个位置都清理，任一处不存在则静默跳过）----
Remove-Item -Recurse -Force (Join-Path $newDir '_update') -ErrorAction SilentlyContinue
Remove-Item -Force (Join-Path $newDir 'main.exe.old') -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force (Join-Path $appDir '_update') -ErrorAction SilentlyContinue
Remove-Item -Force (Join-Path $appDir 'main.exe.old') -ErrorAction SilentlyContinue

exit 0
"""
