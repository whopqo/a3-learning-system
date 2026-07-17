"""
轻量日志模块 —— 内存 + 文件双路输出（参考 inkos 的 sink 设计）
内存存最近 500 条给界面快速查询，文件按天滚动存 db/logs/ 不怕重启丢失
"""
import os
import json
import time
import threading
from collections import deque

_logs = deque(maxlen=500)
_lock = threading.Lock()
_start_time = time.time()

_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db", "logs")

def info(msg: str, source: str = "system"):
    _add("INFO", source, msg)

def warn(msg: str, source: str = "system"):
    _add("WARN", source, msg)

def error(msg: str, source: str = "system"):
    _add("ERROR", source, msg)

def debug(msg: str, source: str = "system"):
    _add("DEBUG", source, msg)

def _add(level: str, source: str, msg: str):
    entry = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "level": level,
        "source": source,
        "message": str(msg)[:500],
    }
    with _lock:
        _logs.append(entry)
        _write_file(entry)
    # 也打一行到 stdout
    print(f"[{entry['time']}] [{source}] [{level}] {msg}")

def _write_file(entry: dict):
    """按天滚动写 JSON Lines 文件，一行一条"""
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        fname = os.path.join(_LOG_DIR, f"app-{time.strftime('%Y%m%d')}.log")
        with open(fname, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # 写日志失败不能影响主流程

def get_recent(n: int = 50, level: str = None, source: str = None) -> list:
    """获取最近 n 条日志，可按级别、来源过滤。内存不够时从今天的文件补"""
    with _lock:
        logs = list(_logs)
    if not logs:
        logs = _read_today_file()
    if level:
        logs = [l for l in logs if l["level"] == level.upper()]
    if source:
        logs = [l for l in logs if l.get("source") == source]
    return logs[-n:]

def _read_today_file(max_lines: int = 500) -> list:
    try:
        fname = os.path.join(_LOG_DIR, f"app-{time.strftime('%Y%m%d')}.log")
        if not os.path.exists(fname):
            return []
        with open(fname, "r", encoding="utf-8") as f:
            lines = f.readlines()[-max_lines:]
        return [json.loads(l) for l in lines if l.strip()]
    except Exception:
        return []

def get_sources() -> list:
    """当前内存日志里出现过的来源，给前端做筛选下拉"""
    with _lock:
        return sorted({l.get("source", "system") for l in _logs})

def get_stats() -> dict:
    """获取系统运行统计"""
    with _lock:
        total = len(_logs)
        errors = sum(1 for l in _logs if l["level"] == "ERROR")
        warnings = sum(1 for l in _logs if l["level"] == "WARN")
    return {
        "uptime_seconds": int(time.time() - _start_time),
        "total_logs": total,
        "errors": errors,
        "warnings": warnings,
        "info": total - errors - warnings,
    }
