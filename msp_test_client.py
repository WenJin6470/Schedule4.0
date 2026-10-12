# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║        🧪 电子课表 MSP 测试客户端                                         ║
╚══════════════════════════════════════════════════════════════════════════╝

这是一个**独立的 MSP 节点**，用来测试课表程序对外提供的 3 个接口和 2 个信号。

用法（必须先启动课表程序 main.py）：
    cd D:\\DELL\\Code\\七月项目\\Schedule4.0\\Code
    venv\\Scripts\\python.exe msp_test_client.py

然后输入数字选择要调用的接口，返回值会打印在这里。

📌 它做了什么
═══════════════════════════════════════════════════════════════════════════
· 用 `Preset.LOCAL_AI` 启动一个节点（会主动发现同机的其它 MSP 节点）
· 通过共享目录 ~/.msp/nodes/ 发现课表节点 `schedule4` 并建立连接
· 后台一直在订阅 `schedule.**`，课表的上下课信号一到就打印出来
· 菜单里的每一项对应课表的一个接口；参数会逐个询问

📌 关于上下课信号
═══════════════════════════════════════════════════════════════════════════
课表节点按**它当前正在使用的那份时间表**（由 Display_Rules 按日期解析）
判断上下课。所以信号什么时候来，取决于课表现在用的是哪一版时间表。
本客户端只是被动接收，不参与判断。

⚠️ MSP 不做缓存：订阅方没连上时发出的信号会丢。所以本客户端启动后
   建议先调一次 get-lesson-state 对齐当前状态，再等增量信号。
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ================================================================
#  ★ 解释器守卫 —— 必须在 import msp 之前执行 ★
# ================================================================
def _ensure_msp_importable() -> None:
    """当前解释器里没有 msp 时，自动改用项目 venv 的解释器重新执行本脚本。

    典型场景：直接 `python msp_test_client.py`（系统 Python、或 VS Code 默认
    解释器）—— 而 msp 只装在课表项目的 venv 里，于是只会看到一句
    `ModuleNotFoundError: No module named 'msp'`。这里自动切过去，
    省得每次手敲 venv 的完整路径。
    """
    try:
        import msp  # noqa: F401
        return                          # 已经可用，什么都不做
    except ImportError:
        pass

    code_dir = Path(__file__).resolve().parent
    venv_py = code_dir / 'venv' / 'Scripts' / 'python.exe'
    argv0 = sys.argv[0] if sys.argv else ''
    script = Path(argv0).resolve() if argv0 else None
    already = os.environ.get('MSP_CLIENT_REEXEC') == '1'

    can_reexec = (
        venv_py.exists()
        and not already
        and script is not None
        and script.suffix == '.py'
        and script.exists()
        and Path(sys.executable).resolve() != venv_py.resolve()
    )

    if can_reexec:
        print(
            '[bootstrap] 当前解释器里没有 msp，改用项目 venv 重新执行：\n'
            f'            {sys.executable}\n'
            f'         -> {venv_py}\n',
            flush=True,
        )
        # 注意：刻意不用 os.execve —— 实测它在 Windows 上会以
        # 0xC0000005（访问冲突）直接崩溃，subprocess 才可靠。
        try:
            rc = subprocess.call(
                [str(venv_py), str(script), *sys.argv[1:]],
                env=dict(os.environ, MSP_CLIENT_REEXEC='1'),
            )
        except KeyboardInterrupt:
            rc = 130
        raise SystemExit(rc)

    # 无法自动修复 —— 给出可操作的指引
    print('\n[错误] 没有找到 msp 包。', flush=True)
    if not venv_py.exists():
        print(f'  项目 venv 不存在：{venv_py}')
        print('  请在 Code 目录先执行：')
        print('      venv\\Scripts\\python.exe -m pip install -r requirements.txt')
    else:
        print('  请用项目 venv 的解释器运行：')
        print(f'      "{venv_py}" msp_test_client.py')
    raise SystemExit(1)


_ensure_msp_importable()

# 走到这里说明 msp 一定可用
from msp import MSPNode, Preset  # type: ignore  # noqa: E402

#: 要连接的课表节点 id（见 msp_bridge.py 的 MSPBridge.NODE_ID）
TARGET_NODE = 'schedule4'
#: 本客户端自己的节点 id（规范要求 [a-z0-9_-]+）
CLIENT_NODE = 'schedule4_client'


# ================================================================
#  收到的信号缓存（回调在后台线程里执行，只做收集 + 打印）
# ================================================================
_received: List[Tuple[float, str, Dict[str, Any]]] = []


def _on_signal(sig: Any) -> None:
    """课表发来的信号回调（在 MSP 的读线程里执行）。"""
    _received.append((time.time(), sig.path, dict(sig.payload or {})))
    stamp = time.strftime('%H:%M:%S')
    print(f"\n  📣 [{stamp}] 收到信号 {sig.path}", flush=True)
    print(f"       {json.dumps(sig.payload, ensure_ascii=False)}", flush=True)
    print("  （按回车继续）", end='', flush=True)


# ================================================================
#  菜单
# ================================================================
MENU = [
    {
        'tool': 'get-lesson-state',
        'label': '查询实时上课状态（无参数）',
        'params': [],
    },
    {
        'tool': 'get-today-schedule',
        'label': '获取当天/指定星期的完整课表',
        'params': [('day', '目标星期 Monday~Sunday（留空取当天）', '')],
    },
    {
        'tool': 'swap-course',
        'label': '临时换课',
        'params': [
            ('day_name', '星期，如 Monday', 'Monday'),
            ('lesson_key', '课时键，如 lesson_2', 'lesson_2'),
            ('old_subject', '原科目（留空自动取当前科目）', ''),
            ('new_subject', '新科目，如 数学', '数学'),
            ('swap_date', '生效日期 YYYY-MM-DD（留空取该星期下一个匹配日）', ''),
        ],
    },
]


def show_menu() -> None:
    print("\n" + "=" * 66)
    print(f"  请选择要向课表节点（{TARGET_NODE}）申请的接口：")
    for idx, item in enumerate(MENU, start=1):
        print(f"    {idx}. {item['tool']:<20} —— {item['label']}")
    print(f"    4. {'查看已收到的信号':<20} —— 共 {len(_received)} 条")
    print(f"    5. {'查看课表节点的能力清单':<20} —— tools / signals")
    print("    0. 退出")
    print("=" * 66)


def ask_params(item: Dict[str, Any]) -> Dict[str, Any]:
    """按菜单声明逐个询问参数。"""
    args: Dict[str, Any] = {}
    for name, prompt, default in item['params']:
        hint = f"（回车用 {default}）" if default else "（可留空）"
        raw = input(f"      请输入 {name} —— {prompt} {hint}: ").strip()
        if raw:
            args[name] = raw
        elif default:
            args[name] = default
        # 留空且无默认值 → 不传该参数，让课表端用自己的默认值
    return args


def call_tool(node: MSPNode, item: Dict[str, Any]) -> None:
    """调用课表的接口并打印返回值。"""
    args = ask_params(item)
    print(f"\n      → 向 {TARGET_NODE} 请求 {item['tool']}({args}) ……", flush=True)

    started = time.time()
    result = node.call(TARGET_NODE, item['tool'], args, timeout=10.0)
    elapsed = time.time() - started

    if result.is_error:
        print(f"      ✗ 失败（{elapsed:.2f}s）：{result.error}", flush=True)
        return

    data: Any = result.unwrap()
    print(f"      ✓ 成功（{elapsed:.2f}s）返回：", flush=True)
    print(json.dumps(data, ensure_ascii=False, indent=8), flush=True)


def show_signals() -> None:
    """打印已收到的信号。"""
    if not _received:
        print("\n      （还没收到任何信号）")
        print("      课表的上下课信号只在「状态切换的那一刻」发出。")
        print("      想马上看到效果，可以临时改 Config/debug_config.ini 把")
        print("      模拟时间调到某节课开始/结束的前后几秒，然后等切换。")
        return
    print(f"\n      共 {len(_received)} 条信号：")
    for ts, path, payload in _received:
        stamp = time.strftime('%H:%M:%S', time.localtime(ts))
        print(f"        [{stamp}] {path}")
        print(f"                 {json.dumps(payload, ensure_ascii=False)}")


def show_manifest(node: MSPNode) -> None:
    """打印课表节点的能力清单。"""
    manifest: Optional[Dict[str, Any]] = node.peer_manifest(TARGET_NODE)
    if not manifest:
        print("\n      （还没拿到能力清单，可能尚未握手完成）")
        return
    tools = [t.get('name') for t in (manifest.get('tools') or [])]
    print("\n      课表节点宣告的能力：")
    print(f"        tools        = {tools}")
    print(f"        signals      = {[s.get('path') for s in (manifest.get('signals') or [])]}")
    print(f"        patterns     = {manifest.get('patterns')}")
    print(f"        capabilities = {manifest.get('capabilities')}")
    for t in (manifest.get('tools') or []):
        print(f"\n        · {t.get('name')} —— {t.get('description', '')}")
        print(f"          inputSchema = {json.dumps(t.get('inputSchema'), ensure_ascii=False)}")


# ================================================================
#  主流程
# ================================================================
def main() -> None:
    print("=" * 66)
    print("  电子课表 MSP 测试客户端")
    print("=" * 66)

    node: MSPNode = MSPNode(CLIENT_NODE, preset=Preset.LOCAL_AI)
    node.start(settle=False)
    print(f"[client] 本节点已启动：{CLIENT_NODE}  endpoint={node.endpoint}")

    # 后台订阅：课表的上下课信号
    node.on('schedule.**')(_on_signal)
    print("[client] 已订阅 schedule.**（等待课表的上下课信号）")

    # 等待发现并连接课表节点
    print(f"\n  正在发现课表节点（{TARGET_NODE}）……")
    deadline = time.time() + 30
    while time.time() < deadline and TARGET_NODE not in node.connections():
        time.sleep(0.3)

    if TARGET_NODE not in node.connections():
        print(f"\n  ✗ 30 秒内没能连上 {TARGET_NODE}（当前已连接：{node.connections()}）")
        print("    请先启动课表程序 main.py，并确认启动日志里出现：")
        print("      [MSP] 课表节点已启动：node_id=schedule4 ...")
        print("    若课表日志显示「MSP SDK 未安装」，则先在 Code 目录执行：")
        print("      venv\\Scripts\\python.exe -m pip install -r requirements.txt")
        node.stop()
        return

    print(f"  ✓ 已连接：{node.connections()}")
    print("\n  提示：先调一次 1 对齐当前状态，再等课表的增量信号。")

    def clear_screen() -> None:
        """清空终端，让屏幕上只留本次操作的结果。

        Windows 用 cls、其它平台用 clear。刻意**不用** ANSI 转义序列
        （如 '\033[2J'）—— 万一终端没开 VT 处理，那串字符会原样显示成乱码。
        """
        os.system('cls' if os.name == 'nt' else 'clear')

    try:
        show_menu()
        shown_once = False          # 第一次不清屏，方便你看清完整输出
        while True:
            raw = input("\n  请输入编号: ").strip()

            if raw in ('0', 'q', 'quit', 'exit'):
                break

            # 先判断这次输入是不是一个有效动作。
            # 无效输入**不清屏** —— 保留当前菜单，方便对照着重新输入。
            is_valid = (
                raw in ('4', '5')
                or (raw.isdigit() and 1 <= int(raw) <= len(MENU))
            )
            if not is_valid:
                print(f"  无效输入 {raw!r}，请输入 0 ~ 5 之间的数字。")
                continue

            # 第二次及以后：执行前先清屏，保证终端相对整洁
            if shown_once:
                clear_screen()

            if raw == '4':
                show_signals()
            elif raw == '5':
                show_manifest(node)
            else:
                call_tool(node, MENU[int(raw) - 1])

            shown_once = True
            show_menu()

    except (KeyboardInterrupt, EOFError):
        print()
    finally:
        print("\n[client] 正在退出……")
        try:
            node.stop()
        except Exception:  # noqa: BLE001
            pass
        print("[client] 已退出")


if __name__ == '__main__':
    main()
