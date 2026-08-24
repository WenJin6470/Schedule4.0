"""
╔══════════════════════════════════════════════════════════════════════════╗
║     📅 电子课表系统 —— schedule_translate.py（翻译测试与翻译后端模块）       ║
╚══════════════════════════════════════════════════════════════════════════╝

📌 本模块的角色
═══════════════════════════════════════════════════════════════════════════
本文件属于系统的【后端程序】，不含任何 UI 代码，负责：

  ✅ TranslationMonitor — 定时监测器：每 2.5 小时自动测试候选翻译网站
  ✅ run_translation_tests() — 专门测试函数：
      - 读取 Config/TranslationTest/translation_sites.txt 中的候选网站
      - 从 Config/TranslationTest/Translation_test.csv 任选一条测试词条
      - 对每个网站执行测试翻译，记录「完成翻译耗时」「翻译是否正确」
        「需翻译的中文」「期望的英文」「翻译的英文」
      - 结果写入 Config/TranslationTest/outcome.json（每网站保留最近 20 次）
      - 每次测试后对每网站近 20 次结果拟合出可用度数字分，
        将可用度最高的网站 id 写入 schedule_config.ini 的 translation_site
  ✅ translate_text() — 单次翻译接口（供设置页科目编辑子窗口调用）
  ✅ TranslateWorker — 翻译工作线程（QThread，供 UI 非阻塞调用）
  ✅ get_default_site() — 获取系统默认翻译网站（可用度最高者）

📌 候选翻译网站（免密钥、返回 JSON、标准库 urllib 即可调用）
═══════════════════════════════════════════════════════════════════════════
  bing     — 必应翻译公开接口（cn.bing.com/ttranslatev3）
  youdao   — 有道翻译公开接口（fanyi.youdao.com）
  baidu    — 百度翻译建议接口（fanyi.baidu.com/sug）
  mymemory — MyMemory 翻译 API（api.mymemory.translated.net）

📌 可用度分数（拟合汇总）说明
═══════════════════════════════════════════════════════════════════════════
  score = 100 × 正确率 − 0.5 × min(平均耗时秒, 20)，范围裁剪到 [0, 100]。
  正确率越高分数越高；耗时越长扣分越多；无记录的网站分数为 0。
"""

import json
import logging
import os
import random
import re
import threading
import time
import urllib.parse
import urllib.request
from configparser import ConfigParser
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, QTimer, QThread, Signal
from app_paths import app_root


logger: logging.Logger = logging.getLogger(__name__)


# ==================== 常量 ====================

# 测试相关文件路径（相对于脚本目录）
SITES_FILE: str = 'Config/TranslationTest/translation_sites.txt'
TEST_CSV: str = 'Config/TranslationTest/Translation_test.csv'
OUTCOME_JSON: str = 'Config/TranslationTest/outcome.json'
INI_PATH: str = 'Config/schedule_config.ini'
INI_KEY: str = 'translation_site'

# 定时测试间隔：2.5 小时（毫秒）
TEST_INTERVAL_MS: int = 2_500 * 60 * 60  # 9,000,000 ms
# 首轮测试延迟：应用启动 60 秒后进行（避开启动峰值）
FIRST_TEST_DELAY_MS: int = 60_000

# 每个网站保留的最近测试结果条数
HISTORY_LIMIT: int = 20
# 单次翻译请求超时（秒）
TIMEOUT: float = 8.0
# 网站兜底 id（sites 文件缺失时使用）
DEFAULT_SITE: str = 'bing'

# 必应翻译主页令牌（IG / key / token）缓存时长（秒）
# 服务端 token 有效期约 1 小时，缓存 30 分钟即可安全复用
BING_TOKEN_CACHE_SEC: float = 30 * 60

# 兜底测试词条（CSV 缺失 / 为空时使用）
FALLBACK_TEST_ENTRY: Tuple[str, str] = ('语文', 'Chinese')

# 浏览器 User-Agent（部分翻译接口会拒绝默认 UA）
_USER_AGENT: str = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
)


# ==================== 异常 ====================


class TranslationError(Exception):
    """翻译失败异常（网络错误 / 响应解析失败 / 无结果）。"""


# ==================== 文件路径 ====================


def _script_dir() -> str:
    """返回脚本所在目录。"""
    return app_root()


def _path(rel: str) -> str:
    """把相对路径解析为绝对路径。"""
    return os.path.join(_script_dir(), rel)


# ==================== 候选网站列表 ====================


def load_sites() -> List[Dict[str, str]]:
    """
    读取候选翻译网站列表。
    ---------------------
    文件格式：每行一条 `id|显示名`，以 ; 或 # 开头的行被忽略。

    返回值：
        List[Dict]：[{"id": ..., "name": ...}, ...]；文件缺失时返回空列表
    """
    path: str = _path(SITES_FILE)
    sites: List[Dict[str, str]] = []
    try:
        if not os.path.exists(path):
            logger.warning(f"翻译网站列表不存在：{path}")
            return sites
        with open(path, 'r', encoding='utf-8') as f:
            for raw in f:
                line: str = raw.strip()
                if not line or line.startswith(';') or line.startswith('#'):
                    continue
                parts: List[str] = line.split('|', 1)
                sid: str = parts[0].strip()
                name: str = parts[1].strip() if len(parts) > 1 else sid
                if sid:
                    sites.append({'id': sid, 'name': name})
        logger.info(f"翻译网站列表加载完成：{len(sites)} 个网站")
        return sites
    except OSError as e:
        logger.error(f"读取翻译网站列表失败：{e}")
        return sites


# ==================== 单网站翻译请求 ====================


def _http_get_json(url: str, timeout: float) -> Any:
    """GET 请求并解析 JSON 响应（带浏览器 UA）。"""
    req: urllib.request.Request = urllib.request.Request(
        url, headers={'User-Agent': _USER_AGENT}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        body: bytes = resp.read()
    return json.loads(body.decode('utf-8', errors='replace'))


def _http_post_json(url: str, data: Dict[str, str], timeout: float) -> Any:
    """表单 POST 请求并解析 JSON 响应（带浏览器 UA）。"""
    body: bytes = urllib.parse.urlencode(data).encode('utf-8')
    req: urllib.request.Request = urllib.request.Request(
        url, data=body,
        headers={
            'User-Agent': _USER_AGENT,
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        resp_body: bytes = resp.read()
    return json.loads(resp_body.decode('utf-8', errors='replace'))


def _translate_bing(text: str, timeout: float) -> str:
    """必应翻译公开接口（cn.bing.com/ttranslatev3）。"""
    ig, key, token = _get_bing_tokens(timeout)
    data: Dict[str, str] = {
        'fromLang': 'auto-detect',
        'text': text,
        'to': 'en',
        'token': token,
        'key': key,
    }
    url: str = (
        f'https://cn.bing.com/ttranslatev3?isVertical=1&&IG={ig}'
        '&IID=translator.5028'
    )
    result: Any = _http_post_json(url, data, timeout)
    try:
        translated: str = result[0]['translations'][0]['text']
    except (IndexError, TypeError, KeyError):
        raise TranslationError('必应翻译响应格式异常')
    if not translated or not translated.strip():
        raise TranslationError('必应翻译无翻译结果')
    return translated.strip()


# ==================== 必应翻译令牌（IG / key / token） ====================


# 必应翻译主页令牌缓存：{'ig': ..., 'key': ..., 'token': ..., 'ts': 抓取时刻}
_bing_token_cache: Dict[str, Any] = {'ig': '', 'key': '', 'token': '', 'ts': 0.0}
_bing_token_lock: threading.Lock = threading.Lock()


def _fetch_bing_tokens(timeout: float) -> Tuple[str, str, str]:
    """
    从必应翻译主页抓取令牌。
    ----------------------
    主页 HTML 内嵌两个令牌：
      - IG（_G.IG，用于 ttranslatev3 的查询参数）
      - params_AbusePreventionHelper = [key, token, ttl]（用于 POST 表单）

    返回值：
        Tuple[str, str, str]：(IG, key, token)

    异常：
        TranslationError — 主页抓取失败 / 未找到令牌
    """
    req: urllib.request.Request = urllib.request.Request(
        'https://cn.bing.com/translator?to=en',
        headers={'User-Agent': _USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            html: str = resp.read().decode('utf-8', errors='replace')
    except Exception as e:
        raise TranslationError(f'必应翻译主页抓取失败：{e}') from e
    ig_m: Optional[re.Match] = re.search(
        r'\bIG\s*[:=]\s*["\']([^"\']+)["\']', html
    )
    helper_m: Optional[re.Match] = re.search(
        r'params_AbusePreventionHelper\s*=\s*\[(\d+)\s*,\s*"([^"]+)"\s*,\s*\d+\]',
        html,
    )
    if not ig_m or not helper_m:
        raise TranslationError('必应翻译主页未找到翻译令牌')
    return ig_m.group(1), helper_m.group(1), helper_m.group(2)


def _get_bing_tokens(timeout: float) -> Tuple[str, str, str]:
    """
    获取必应翻译令牌（带缓存，避免每次翻译都抓主页）。
    -------------------------------------------------
    缓存未过期时直接复用；过期或为空时重新抓取（线程安全）。
    """
    with _bing_token_lock:
        if (
            _bing_token_cache['ig']
            and time.monotonic() - _bing_token_cache['ts'] < BING_TOKEN_CACHE_SEC
        ):
            return (
                _bing_token_cache['ig'],
                _bing_token_cache['key'],
                _bing_token_cache['token'],
            )
        ig, key, token = _fetch_bing_tokens(timeout)
        _bing_token_cache.update(
            {'ig': ig, 'key': key, 'token': token, 'ts': time.monotonic()}
        )
        return ig, key, token


def _translate_youdao(text: str, timeout: float) -> str:
    """有道翻译公开接口。"""
    quoted: str = urllib.parse.quote(text, safe='')
    url: str = (
        'https://fanyi.youdao.com/translate'
        f'?doctype=json&type=AUTO&i={quoted}'
    )
    data: Any = _http_get_json(url, timeout)
    try:
        result: str = data['translateResult'][0][0]['tgt']
    except (IndexError, TypeError, KeyError):
        raise TranslationError('有道翻译响应格式异常')
    if not result or not result.strip():
        raise TranslationError('有道翻译无翻译结果')
    return result.strip()


def _translate_baidu(text: str, timeout: float) -> str:
    """百度翻译建议接口（POST）。"""
    data: Any = _http_post_json(
        'https://fanyi.baidu.com/sug', {'kw': text}, timeout
    )
    try:
        items: List[Any] = data.get('data', [])
        if not items:
            raise TranslationError('百度翻译无翻译结果')
        result: str = items[0].get('v', '')
    except (IndexError, TypeError, KeyError, AttributeError):
        raise TranslationError('百度翻译响应格式异常')
    if not result or not result.strip():
        raise TranslationError('百度翻译无翻译结果')
    return result.strip()


def _translate_mymemory(text: str, timeout: float) -> str:
    """MyMemory 翻译 API（zh-CN → en）。"""
    quoted: str = urllib.parse.quote(text, safe='')
    url: str = (
        'https://api.mymemory.translated.net/get'
        f'?q={quoted}&langpair=zh-CN|en'
    )
    data: Any = _http_get_json(url, timeout)
    try:
        if data.get('responseStatus') != 200:
            raise TranslationError(
                f"MyMemory 响应状态异常：{data.get('responseStatus')}"
            )
        result: str = data['responseData']['translatedText']
    except (KeyError, TypeError, AttributeError):
        raise TranslationError('MyMemory 响应格式异常')
    if not result or not result.strip():
        raise TranslationError('MyMemory 无翻译结果')
    return result.strip()


# 网站 id → 请求处理函数注册表
_SITE_HANDLERS: Dict[str, Any] = {
    'bing': _translate_bing,
    'youdao': _translate_youdao,
    'baidu': _translate_baidu,
    'mymemory': _translate_mymemory,
}


# ==================== 单次翻译 ====================


def translate_text(text: str, site_id: str, timeout: float = TIMEOUT) -> Tuple[str, float]:
    """
    使用指定网站翻译文本（中文 → 英文）。
    -----------------------------------
    参数：
        text    （str）：  待翻译文本
        site_id （str）：  网站 id（须在 sites 文件或注册表中）
        timeout （float）：超时秒数，默认 8 秒

    返回值：
        Tuple[str, float]：(译文, 耗时秒)

    异常：
        TranslationError — 未知网站 / 网络错误 / 响应异常
    """
    handler: Optional[Any] = _SITE_HANDLERS.get(site_id)
    if handler is None:
        raise TranslationError(f"未知翻译网站：{site_id}")
    if not text or not text.strip():
        raise TranslationError('待翻译文本为空')

    start: float = time.monotonic()
    try:
        result: str = handler(text.strip(), timeout)
    except TranslationError:
        raise
    except Exception as e:
        raise TranslationError(f"翻译请求失败：{e}") from e
    duration: float = time.monotonic() - start
    logger.info(f"翻译完成：site={site_id} 耗时={duration:.3f}s")
    return result, duration


# ==================== 测试词条 ====================


def pick_test_entry() -> Tuple[str, str]:
    """
    从 Translation_test.csv 任选一条测试词条。
    ---------------------------------------
    CSV 格式：表头 `中文,期望英文`，每行一条词条。
    CSV 缺失 / 为空 / 损坏时使用内置兜底词条。

    返回值：
        Tuple[str, str]：(中文原文, 期望英文)
    """
    path: str = _path(TEST_CSV)
    entries: List[Tuple[str, str]] = []
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                lines: List[str] = [ln.strip() for ln in f if ln.strip()]
            for line in lines[1:]:  # 跳过表头
                parts: List[str] = line.split(',', 1)
                if len(parts) == 2 and parts[0].strip() and parts[1].strip():
                    entries.append((parts[0].strip(), parts[1].strip()))
    except OSError as e:
        logger.warning(f"读取测试词条失败：{e}")
    if not entries:
        logger.warning("测试词条为空，使用内置兜底词条")
        return FALLBACK_TEST_ENTRY
    return random.choice(entries)


# ==================== 正确性判定 ====================


def _normalize(text: str) -> str:
    """归一化译文：去首尾空白、转小写、去尾部标点。"""
    return text.strip().lower().rstrip('。.．!！?？~～')


def check_correct(actual: str, expected: str) -> bool:
    """
    判断实际译文是否与期望值一致（归一化后比较）。
    -------------------------------------------
    参数：
        actual  （str）：网站返回的译文
        expected（str）：期望译文

    返回值：
        bool：True 表示翻译正确
    """
    return _normalize(actual) == _normalize(expected)


# ==================== outcome.json 读写 ====================


def _load_outcome() -> Dict[str, Any]:
    """
    读取测试结果文件。
    ----------------
    兼容空文件（[]）与损坏文件：一律按空结构处理。

    返回值：
        Dict：{"history": {...}, "scores": {...}, "updated_at": "..."}
    """
    default: Dict[str, Any] = {'history': {}, 'scores': {}, 'updated_at': ''}
    path: str = _path(OUTCOME_JSON)
    try:
        if not os.path.exists(path):
            return default
        with open(path, 'r', encoding='utf-8') as f:
            data: Any = json.load(f)
        if not isinstance(data, dict):
            logger.warning("outcome.json 格式异常（非对象），按空处理")
            return default
        return data
    except json.JSONDecodeError as e:
        logger.warning(f"outcome.json 解析失败：{e}，按空处理")
        return default
    except OSError as e:
        logger.warning(f"读取 outcome.json 失败：{e}")
        return default


def _save_outcome(outcome: Dict[str, Any]) -> bool:
    """原子写入 outcome.json（先写临时文件再替换）。"""
    path: str = _path(OUTCOME_JSON)
    tmp_path: str = path + '.tmp'
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(outcome, f, ensure_ascii=False, indent=4)
        os.replace(tmp_path, path)
        return True
    except OSError as e:
        logger.error(f"保存 outcome.json 失败：{e}")
        return False


# ==================== 可用度分数 ====================


def _compute_scores(history: Dict[str, List[Dict]]) -> Dict[str, float]:
    """
    对每个网站近 20 次结果拟合出可用度数字分。
    ---------------------------------------
    公式：score = 100 × 正确率 − 0.5 × min(平均耗时秒, 20)，裁剪到 [0, 100]。
    正确率 = 正确次数 / 总次数（不足 20 条按实际条数）。
    无记录的网站分数为 0。

    参数：
        history（Dict[str, List[Dict]]）：{网站 id: [记录, ...]}

    返回值：
        Dict[str, float]：{网站 id: 分数}
    """
    scores: Dict[str, float] = {}
    for sid, records in history.items():
        if not isinstance(records, list) or not records:
            scores[sid] = 0.0
            continue
        n: int = len(records)
        correct_count: int = sum(
            1 for r in records if isinstance(r, dict) and r.get('correct')
        )
        rate: float = correct_count / n
        durations: List[float] = [
            r.get('duration', 0.0) or 0.0
            for r in records if isinstance(r, dict)
        ]
        avg: float = sum(durations) / len(durations) if durations else 0.0
        score: float = 100.0 * rate - 0.5 * min(avg, 20.0)
        scores[sid] = max(0.0, min(100.0, score))
    return scores


def _best_site(scores: Dict[str, float], sites: List[Dict[str, str]]) -> str:
    """
    返回可用度最高的网站 id（并列时取 sites 文件顺序靠前者）。
    ------------------------------------------------------
    参数：
        scores（Dict[str, float]）：可用度分数
        sites （List[Dict]）：      候选网站列表（决定并列时的次序）

    返回值：
        str：网站 id；无候选网站时返回空字符串
    """
    ordered: List[str] = [s['id'] for s in sites if s.get('id') in scores]
    if not ordered:
        return ''
    best: str = ordered[0]
    best_score: float = scores.get(best, 0.0)
    for sid in ordered[1:]:
        sc: float = scores.get(sid, 0.0)
        if sc > best_score:
            best = sid
            best_score = sc
    return best


# ==================== schedule_config.ini 读写 ====================


def _read_ini_site() -> str:
    """从 schedule_config.ini 读取默认翻译网站 id（读不到返回空串）。"""
    path: str = _path(INI_PATH)
    try:
        if not os.path.exists(path):
            return ''
        parser: ConfigParser = ConfigParser()
        parser.read(path, encoding='utf-8')
        return parser.get('Schedule', INI_KEY, fallback='').strip()
    except Exception as e:
        logger.warning(f"读取 INI translation_site 失败：{e}")
        return ''


def _write_ini_site(site_id: str) -> bool:
    """
    把默认翻译网站 id 写入 schedule_config.ini（保留注释的逐行替换）。
    -------------------------------------------------------------
    规则：
      - [Schedule] 节已有 translation_site 键 → 替换该行
      - 有 [Schedule] 节但无该键 → 在节头后插入一行
      - 无 [Schedule] 节 → 在文件末尾追加 [Schedule] 节
    """
    path: str = _path(INI_PATH)
    lines: List[str] = []
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except OSError as e:
            logger.error(f"读取 INI 失败：{e}")
            return False

    section: str = ''
    replaced: bool = False
    schedule_header_idx: int = -1
    out: List[str] = []

    for line in lines:
        stripped: str = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            section = stripped[1:-1]
            if section == 'Schedule' and schedule_header_idx < 0:
                schedule_header_idx = len(out)
        if stripped.startswith(';') or stripped.startswith('#'):
            out.append(line)
            continue
        if '=' in line and section == 'Schedule':
            key: str = line.split('=', 1)[0].strip()
            if key == INI_KEY and not replaced:
                out.append(f"{INI_KEY} = {site_id}\n")
                replaced = True
                continue
        out.append(line)

    if not replaced:
        if schedule_header_idx >= 0:
            out.insert(schedule_header_idx + 1, f"{INI_KEY} = {site_id}\n")
        else:
            if not out or not out[-1].endswith('\n'):
                out.append('\n')
            out.append(f"[Schedule]\n{INI_KEY} = {site_id}\n")

    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.writelines(out)
        logger.info(f"已把默认翻译网站写入 INI：{INI_KEY} = {site_id}")
        return True
    except OSError as e:
        logger.error(f"写入 INI 失败：{e}")
        return False


# ==================== 默认网站 ====================


def get_default_site() -> str:
    """
    获取系统默认翻译网站 id（可用度最高者）。
    --------------------------------------
    优先级：
      1. schedule_config.ini 的 translation_site（且仍在候选列表中）
      2. outcome.json 中 scores 最高者
      3. sites 文件第一条
      4. 内置兜底 'bing'

    返回值：
        str：网站 id
    """
    sites: List[Dict[str, str]] = load_sites()
    known_ids: List[str] = [s['id'] for s in sites]

    ini_site: str = _read_ini_site()
    if ini_site and ini_site in known_ids:
        return ini_site

    outcome: Dict[str, Any] = _load_outcome()
    scores: Any = outcome.get('scores', {}) if isinstance(outcome, dict) else {}
    if isinstance(scores, dict) and scores:
        best: str = _best_site(scores, sites)
        if best:
            return best

    if known_ids:
        return known_ids[0]
    return DEFAULT_SITE


# ==================== 定时测试 ====================


def run_translation_tests() -> Dict[str, Any]:
    """
    【专门测试函数】对全部候选翻译网站执行一轮测试翻译。
    -------------------------------------------------
    流程：
      1. 读取候选网站列表
      2. 从 CSV 任选一条测试词条
      3. 对每个网站执行测试翻译，记录 (完成翻译耗时, 翻译是否正确,
         需翻译的中文, 期望的英文, 翻译的英文)
      4. 写入 outcome.json（每网站保留最近 20 次）
      5. 对每网站近 20 次结果拟合出可用度分数并保存
      6. 将可用度最高的网站 id 写入 schedule_config.ini

    返回值：
        Dict：更新后的 outcome 数据（含 history 与 scores）
    """
    sites: List[Dict[str, str]] = load_sites()
    if not sites:
        logger.warning("无候选翻译网站，跳过本轮测试")
        return _load_outcome()

    source, expected = pick_test_entry()
    logger.info(
        f"开始翻译测试：共 {len(sites)} 个网站，测试词条「{source}」→「{expected}」"
    )

    outcome: Dict[str, Any] = _load_outcome()
    history: Any = outcome.get('history', {})
    if not isinstance(history, dict):
        history = {}

    now_str: str = time.strftime('%Y-%m-%d %H:%M:%S')

    for site in sites:
        sid: str = site['id']
        t0: float = time.monotonic()
        try:
            actual, _dur = translate_text(source, sid)
            correct: bool = check_correct(actual, expected)
            duration: float = _dur
            logger.info(f"  [{sid}] 译文「{actual}」正确={correct} 耗时={duration:.3f}s")
        except Exception as e:
            duration = time.monotonic() - t0
            correct = False
            actual = ''  # 测试失败时无实际译文，记为空白
            logger.warning(f"  [{sid}] 测试失败：{e} 耗时={duration:.3f}s")
        record: Dict[str, Any] = {
            'ts': now_str,
            'duration': round(duration, 3),
            'correct': correct,
            'Need Teanslate': source,
            'Expected English': expected,
            'Translation': actual,
        }
        records: Any = history.get(sid, [])
        if not isinstance(records, list):
            records = []
        records.append(record)
        history[sid] = records[-HISTORY_LIMIT:]

    outcome['history'] = history
    outcome['scores'] = _compute_scores(history)
    outcome['updated_at'] = now_str
    _save_outcome(outcome)

    best: str = _best_site(outcome['scores'], sites)
    if best:
        _write_ini_site(best)
        logger.info(
            f"翻译测试完成：可用度最高网站 = {best}，"
            f"scores = {outcome['scores']}"
        )
    else:
        logger.warning("翻译测试完成，但无法确定可用度最高网站")

    return outcome


# ==================== 定时监测器 ====================


class TranslationMonitor(QObject):
    """
    # TranslationMonitor — 翻译网站定时监测器

    应用启动 60 秒后进行首轮测试，之后每 2.5 小时测试一轮。
    测试在后台线程执行（daemon），不阻塞 UI；用锁防止重入。
    ---

    对外接口：
      - start()        启动监测（首轮延迟 + 周期定时）
      - stop()         停止监测
      - run_test_now() 手动立即触发一轮测试（不等待定时器）
    """

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._lock: threading.Lock = threading.Lock()

        self._timer: QTimer = QTimer(self)
        self._timer.setInterval(TEST_INTERVAL_MS)
        self._timer.timeout.connect(self._on_timer)

        self._first_shot: QTimer = QTimer(self)
        self._first_shot.setSingleShot(True)
        self._first_shot.setInterval(FIRST_TEST_DELAY_MS)
        self._first_shot.timeout.connect(self._on_timer)

        logger.info(
            f"TranslationMonitor 初始化完成：周期 {TEST_INTERVAL_MS / 3600000}h"
        )

    # ================================================================
    #  公开接口
    # ================================================================
    def start(self) -> None:
        """启动监测：安排首轮测试并启动周期定时器。"""
        self._timer.start()
        self._first_shot.start()
        logger.info("TranslationMonitor 已启动（首轮 60 秒后执行）")

    def stop(self) -> None:
        """停止监测。"""
        self._timer.stop()
        self._first_shot.stop()
        logger.info("TranslationMonitor 已停止")

    def run_test_now(self) -> None:
        """手动立即触发一轮测试（不等待定时器）。"""
        self._run_in_thread()

    # ================================================================
    #  内部实现
    # ================================================================
    def _on_timer(self) -> None:
        """定时器触发 → 后台线程执行测试。"""
        self._run_in_thread()

    def _run_in_thread(self) -> None:
        """在后台线程执行一轮测试（防重入）。"""
        if not self._lock.acquire(blocking=False):
            logger.info("上一轮翻译测试尚未结束，跳过本轮")
            return

        def worker() -> None:
            try:
                outcome: Dict[str, Any] = run_translation_tests()
                logger.info(f"定时翻译测试完成：scores={outcome.get('scores')}")
            except Exception as e:
                logger.error(f"定时翻译测试异常：{e}")
            finally:
                self._lock.release()

        threading.Thread(target=worker, daemon=True).start()


# ==================== 翻译工作线程（供 UI 调用） ====================


class TranslateWorker(QThread):
    """
    # TranslateWorker — 翻译工作线程

    供设置页科目编辑子窗口使用：在后台线程执行翻译，
    通过信号把连接状态 / 翻译状态 / 结果回传 UI，避免阻塞界面。
    ---

    信号：
      status_changed(str) — 状态变化：'connecting'（连接中）/ 'connected'（连接成功）/ 'failed'（连接失败）
      finished_ok(str, float)   — 翻译成功：(译文, 耗时秒)
      finished_fail(str)        — 翻译失败：(错误信息)
    """

    status_changed = Signal(str)
    finished_ok = Signal(str, float)
    finished_fail = Signal(str)

    def __init__(self, text: str, site_id: str, timeout: float = TIMEOUT,
                 parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._text: str = text
        self._site_id: str = site_id
        self._timeout: float = timeout
        self._cancelled: bool = False

    def cancel(self) -> None:
        """取消：结果返回后不再发射完成信号（仅影响 UI 更新）。"""
        self._cancelled = True

    def run(self) -> None:  # noqa: D102
        self.status_changed.emit('connecting')
        try:
            result, duration = translate_text(
                self._text, self._site_id, timeout=self._timeout
            )
        except Exception as e:
            self.status_changed.emit('failed')
            if not self._cancelled:
                self.finished_fail.emit(str(e))
            return
        self.status_changed.emit('connected')
        if not self._cancelled:
            self.finished_ok.emit(result, duration)
