"""
LLM 服务管理器 —— 模型配置中心（参考 inkos 的 service-presets 设计）
普通配置存 db/models.json，API 密钥单独存 db/secrets.json 不进 git
切换模型运行时立即生效，不用重启服务
"""
import os
import json
import threading
from contextvars import ContextVar
from openai import OpenAI

from config import PROJ_ROOT

# 内置服务商预设表，地址都预填好，用户只需要贴 Key
# api 字段是协议格式: openai(默认,/chat/completions) 或 anthropic(/messages)
PRESETS = {
    "deepseek": {"label": "DeepSeek", "base_url": "https://api.deepseek.com/v1",
                 "known_models": ["deepseek-v4-flash", "deepseek-chat", "deepseek-reasoner"]},
    "spark": {"label": "讯飞星火", "base_url": "https://spark-api-open.xf-yun.com/v1",
              "known_models": ["lite", "generalv3", "generalv3.5", "4.0Ultra"]},
    "qwen": {"label": "通义千问", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
             "known_models": ["qwen-plus", "qwen-turbo", "qwen-max", "qwen-long"]},
    "glm": {"label": "智谱GLM", "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "known_models": ["glm-4-flash", "glm-4-air", "glm-4-plus"]},
    "moonshot": {"label": "Kimi", "base_url": "https://api.moonshot.cn/v1",
                 "known_models": ["moonshot-v1-8k", "moonshot-v1-32k", "kimi-latest"]},
    "anthropic": {"label": "Anthropic (Claude)", "base_url": "https://api.anthropic.com/v1",
                  "api": "anthropic",
                  "known_models": ["claude-sonnet-5", "claude-opus-4-8", "claude-haiku-4-5-20251001"]},
    "siliconflow": {"label": "硅基流动", "base_url": "https://api.siliconflow.cn/v1",
                    "known_models": ["deepseek-ai/DeepSeek-V3", "Qwen/Qwen2.5-72B-Instruct"]},
    "openrouter": {"label": "OpenRouter", "base_url": "https://openrouter.ai/api/v1",
                   "known_models": ["openai/gpt-4o-mini", "anthropic/claude-sonnet-4.5"]},
    "ollama": {"label": "Ollama本地", "base_url": "http://localhost:11434/v1",
               "known_models": ["qwen2.5:7b", "llama3.1:8b"], "no_key": True},
    "custom": {"label": "自定义接口", "base_url": "", "known_models": []},
}

_MODELS_FILE = os.path.join(PROJ_ROOT, "db", "models.json")
_SECRETS_FILE = os.path.join(PROJ_ROOT, "db", "secrets.json")

_lock = threading.Lock()
_state = None          # models.json 内容的内存缓存
_secrets = None        # secrets.json 内容的内存缓存
_clients = {}          # (base_url, api_key) -> OpenAI 客户端，避免重复创建

# 会话级模型覆盖，聊天时临时指定用哪个模型
_override: ContextVar = ContextVar("llm_override", default=None)

def _load():
    global _state, _secrets
    if _state is not None:
        return
    with _lock:
        if _state is not None:
            return
        try:
            with open(_MODELS_FILE, "r", encoding="utf-8") as f:
                _state = json.load(f)
        except Exception:
            _state = None
        try:
            with open(_SECRETS_FILE, "r", encoding="utf-8") as f:
                _secrets = json.load(f)
        except Exception:
            _secrets = {}
        if not _state:
            # 首次运行：从老的 config.py 配置迁移过来
            import config
            svc = config.LLM_PROVIDER if config.LLM_PROVIDER in PRESETS else "deepseek"
            _state = {
                "active": {"service": svc, "model": config.LLM_MODEL},
                "services": {svc: {"model": config.LLM_MODEL, "base_url": ""}},
            }
            _save_state()

def _save_state():
    os.makedirs(os.path.dirname(_MODELS_FILE), exist_ok=True)
    with open(_MODELS_FILE, "w", encoding="utf-8") as f:
        json.dump(_state, f, ensure_ascii=False, indent=2)

def _save_secrets():
    os.makedirs(os.path.dirname(_SECRETS_FILE), exist_ok=True)
    with open(_SECRETS_FILE, "w", encoding="utf-8") as f:
        json.dump(_secrets, f, ensure_ascii=False, indent=2)

def _get_key(service: str) -> str:
    """密钥读取顺序：secrets.json → 环境变量 → ollama不需要"""
    _load()
    key = (_secrets.get(service) or {}).get("api_key", "")
    if not key:
        key = os.getenv(f"{service.upper()}_API_KEY", "")
    if not key and PRESETS.get(service, {}).get("no_key"):
        key = "ollama"
    return key

def _get_base_url(service: str) -> str:
    _load()
    cfg = _state["services"].get(service) or {}
    return cfg.get("base_url") or PRESETS.get(service, {}).get("base_url", "")

def _get_api_format(service: str) -> str:
    """协议格式：服务商自己配置的优先，否则用预设的，默认 openai"""
    _load()
    cfg = _state["services"].get(service) or {}
    return cfg.get("api_format") or PRESETS.get(service, {}).get("api", "openai")

def _make_client(base_url: str, api_key: str, api_format: str):
    if api_format == "anthropic":
        from utils.anthropic_compat import AnthropicClient
        return AnthropicClient(base_url=base_url, api_key=api_key or "empty", timeout=120)
    return OpenAI(base_url=base_url, api_key=api_key or "empty", timeout=120)

def get_client_and_model(service: str = None, model: str = None):
    """拿到当前该用的客户端和模型名。优先级：显式参数 > 会话覆盖 > 全局激活"""
    _load()
    if not service:
        ov = _override.get()
        if ov:
            service, model = ov.get("service"), ov.get("model")
    if not service:
        service = _state["active"]["service"]
    if not model:
        # 用户明确激活的模型优先；服务商配置里存的只是"上次编辑表单的值"，不能压过激活记录
        if service == _state["active"]["service"] and _state["active"].get("model"):
            model = _state["active"]["model"]
        else:
            cfg = _state["services"].get(service) or {}
            model = cfg.get("model") or ""
        if not model:
            km = PRESETS.get(service, {}).get("known_models") or [""]
            model = km[0]

    base_url = _get_base_url(service)
    api_key = _get_key(service)
    api_format = _get_api_format(service)
    ck = (base_url, api_key, api_format)
    with _lock:
        if ck not in _clients:
            _clients[ck] = _make_client(base_url, api_key, api_format)
        return _clients[ck], model

def set_session_override(service: str, model: str):
    """聊天会话临时切换模型，只影响当前这次处理"""
    if service and service in PRESETS or (service and service in (_state or {}).get("services", {})):
        _override.set({"service": service, "model": model})

def clear_session_override():
    _override.set(None)

def get_state() -> dict:
    """给前端的完整状态：预设列表 + 已配置服务 + 当前激活"""
    _load()
    services = []
    for sid, preset in PRESETS.items():
        cfg = _state["services"].get(sid)
        key = _get_key(sid)
        services.append({
            "id": sid,
            "label": preset["label"],
            "base_url": (cfg or {}).get("base_url") or preset["base_url"],
            "configured": cfg is not None,
            "has_key": bool(key),
            "key_preview": (key[:6] + "***") if key else "",
            "model": (cfg or {}).get("model", ""),
            "known_models": preset["known_models"],
            "no_key": preset.get("no_key", False),
            "api_format": _get_api_format(sid),
        })
    return {"active": dict(_state["active"]), "services": services}

def save_service(service: str, api_key: str = "", base_url: str = "", model: str = "", api_format: str = ""):
    """保存一个服务商的配置，密钥和普通配置分开落盘"""
    _load()
    if service not in PRESETS:
        return {"ok": False, "error": f"未知服务商: {service}"}
    # 密钥卫生检查：贴错东西（中文/换行）会让 HTTP 层报奇怪的错，提前拦住
    if api_key and not all(32 <= ord(c) < 127 for c in api_key):
        return {"ok": False, "error": "API 密钥里有中文或特殊字符，请检查是不是复制错了"}
    with _lock:
        cfg = _state["services"].get(service) or {}
        if base_url:
            cfg["base_url"] = base_url
        if model:
            cfg["model"] = model
        if api_format in ("openai", "anthropic"):
            cfg["api_format"] = api_format
        _state["services"][service] = cfg
        _save_state()
        if api_key:
            _secrets[service] = {"api_key": api_key}
            _save_secrets()
        _clients.clear()  # 配置变了，客户端缓存全部作废
    return {"ok": True}

def delete_service(service: str):
    _load()
    with _lock:
        _state["services"].pop(service, None)
        _secrets.pop(service, None)
        # 删的是当前激活的话，切回还剩下的第一个
        if _state["active"]["service"] == service:
            rest = list(_state["services"].keys())
            if rest:
                _state["active"] = {"service": rest[0],
                                    "model": _state["services"][rest[0]].get("model", "")}
        _save_state()
        _save_secrets()
        _clients.clear()
    return {"ok": True}

def set_active(service: str, model: str = ""):
    """全局切换当前模型，立即生效"""
    _load()
    with _lock:
        if service not in PRESETS:
            return {"ok": False, "error": f"未知服务商: {service}"}
        cfg = _state["services"].get(service) or {}
        if model:
            cfg["model"] = model
        _state["services"][service] = cfg
        _state["active"] = {"service": service, "model": model or cfg.get("model", "")}
        _save_state()
    return {"ok": True, "active": dict(_state["active"])}

def test_connection(service: str, api_key: str = "", base_url: str = "", api_format: str = "") -> dict:
    """真实调一次上游 /models 接口验证连通性，成功顺便带回模型列表
    没指定协议格式时自动探测：先按预设格式试，不行换另一种（参考 inkos 的 probe 思路）"""
    _load()
    url = base_url or _get_base_url(service)
    key = api_key or _get_key(service)
    if not url:
        return {"ok": False, "error": "base_url 为空，自定义接口需要填写地址"}

    formats = [api_format] if api_format in ("openai", "anthropic") else None
    if formats is None:
        first = _get_api_format(service)
        formats = [first, "anthropic" if first == "openai" else "openai"]

    last_err = ""
    for fmt in formats:
        try:
            if fmt == "anthropic":
                from utils.anthropic_compat import AnthropicClient
                client = AnthropicClient(base_url=url, api_key=key or "empty", timeout=10)
            else:
                client = OpenAI(base_url=url, api_key=key or "empty", timeout=10)
            resp = client.models.list()
            models = [m.id for m in resp.data][:50]
            out = {"ok": True, "models": models, "source": "api", "detected_format": fmt}
            if fmt != formats[0]:
                out["note"] = f"自动识别为 {'Anthropic' if fmt == 'anthropic' else 'OpenAI'} 协议"
            return out
        except Exception as e:
            err = str(e)[:200]
            # 密钥错就别换格式白试了，直接报
            if "401" in err or "403" in err or "invalid_api_key" in err.lower():
                return {"ok": False, "error": f"密钥无效或无权限: {err}"}
            # 有些服务商不开放 /models 接口，回退内置清单
            known = PRESETS.get(service, {}).get("known_models") or []
            if known and ("404" in err or "not found" in err.lower()):
                return {"ok": True, "models": known, "source": "fallback", "detected_format": fmt,
                        "note": "该服务商不支持列出模型，使用内置清单"}
            last_err = err
    return {"ok": False, "error": last_err}
