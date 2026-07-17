"""
项目设置模块 —— 课程信息、RAG 参数、温度等可调项
存 db/settings.json，覆盖 config.py 里的默认值，改完立即生效
"""
import os
import json
import threading

import config
from utils import logger

_SETTINGS_FILE = os.path.join(config.PROJ_ROOT, "db", "settings.json")
_lock = threading.Lock()

# 允许界面上调的项和它们的类型范围，别的乱七八糟的键一律不收
_EDITABLE = {
    "course_name": str,
    "course_description": str,
    "rag_top_k": int,
    "rag_chunk_size": int,
    "rag_similarity_threshold": float,
    "temp_resource_generation": float,
    "temp_tutoring": float,
    "temp_evaluation": float,
    "max_llm_retries": int,
}


def load_and_apply():
    """启动时调用：读 settings.json 并应用到 config"""
    try:
        with open(_SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        _apply(data)
        return data
    except Exception:
        return {}


def _apply(data: dict):
    """把设置写进 config 的运行时对象，字典原地改立即生效"""
    if "course_name" in data:
        config.COURSE_NAME = data["course_name"]
    if "course_description" in data:
        config.COURSE_DESCRIPTION = data["course_description"]
    if "rag_top_k" in data:
        config.RAG_CONFIG["top_k"] = int(data["rag_top_k"])
    if "rag_chunk_size" in data:
        config.RAG_CONFIG["chunk_size"] = int(data["rag_chunk_size"])
    if "rag_similarity_threshold" in data:
        config.RAG_CONFIG["similarity_threshold"] = float(data["rag_similarity_threshold"])
    if "temp_resource_generation" in data:
        config.LLM_TEMPERATURES["resource_generation"] = float(data["temp_resource_generation"])
    if "temp_tutoring" in data:
        config.LLM_TEMPERATURES["tutoring"] = float(data["temp_tutoring"])
    if "temp_evaluation" in data:
        config.LLM_TEMPERATURES["evaluation"] = float(data["temp_evaluation"])
    if "max_llm_retries" in data:
        config.MAX_LLM_RETRIES = int(data["max_llm_retries"])


def get_settings() -> dict:
    """当前生效的设置（含默认值），给前端渲染表单"""
    return {
        "course_name": config.COURSE_NAME,
        "course_description": config.COURSE_DESCRIPTION,
        "rag_top_k": config.RAG_CONFIG.get("top_k", 5),
        "rag_chunk_size": config.RAG_CONFIG.get("chunk_size", 500),
        "rag_similarity_threshold": config.RAG_CONFIG.get("similarity_threshold", 0.6),
        "temp_resource_generation": config.LLM_TEMPERATURES.get("resource_generation", 0.7),
        "temp_tutoring": config.LLM_TEMPERATURES.get("tutoring", 0.6),
        "temp_evaluation": config.LLM_TEMPERATURES.get("evaluation", 0.2),
        "max_llm_retries": config.MAX_LLM_RETRIES,
    }


def save_settings(data: dict) -> dict:
    """校验 → 应用 → 落盘。未知键丢弃，类型不对报错"""
    clean = {}
    for k, v in (data or {}).items():
        if k not in _EDITABLE:
            continue
        try:
            clean[k] = _EDITABLE[k](v)
        except (ValueError, TypeError):
            return {"ok": False, "error": f"设置项 {k} 的值不合法: {v}"}
    with _lock:
        # 合并已有文件里的内容，避免只提交一项时丢掉其他项
        old = {}
        try:
            with open(_SETTINGS_FILE, "r", encoding="utf-8") as f:
                old = json.load(f)
        except Exception:
            pass
        old.update(clean)
        _apply(old)
        os.makedirs(os.path.dirname(_SETTINGS_FILE), exist_ok=True)
        with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(old, f, ensure_ascii=False, indent=2)
    logger.info(f"项目设置已更新: {', '.join(clean.keys())}", "settings")
    return {"ok": True, "settings": get_settings()}
