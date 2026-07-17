"""
Agent基类 —— 统一LLM调用接口、JSON解析、日志记录、错误处理
"""
import time
import json
import traceback
from abc import ABC, abstractmethod
from typing import Any

import config
from config import LLM_TEMPERATURES
from config import LLM_RETRY_BASE_DELAY
from utils.parser import extract_json
from utils import llm_manager


class BaseAgent(ABC):
    """所有智能体的基类"""

    def __init__(self, name: str, role: str, system_prompt: str = ""):
        self.name = name
        self.role = role
        self.system_prompt = system_prompt
        self.total_tokens = 0
        self.total_calls = 0

    # 每次调用时从模型管理器动态取，切换模型不用重启
    @property
    def client(self):
        c, _ = llm_manager.get_client_and_model()
        return c

    @property
    def model(self):
        _, m = llm_manager.get_client_and_model()
        return m

    def _with_skills(self, system_prompt: str) -> str:
        """当前请求启用了教学模式的话，把规则拼进系统提示词"""
        from utils import skill_manager
        rules = skill_manager.get_active_rules()
        if not rules:
            return system_prompt
        return (system_prompt + "\n\n" + rules) if system_prompt else rules

    def _fit_max_tokens(self, max_tokens: int) -> int:
        """推理型模型的思考文字也占token配额，正文容易被挤断——自动放大上限"""
        m = (self.model or "").lower()
        if any(k in m for k in ("reasoner", "-r1", "think", "-pro")):
            return max(max_tokens, 4000)
        return max_tokens

    def _call_llm(
        self,
        user_prompt: str,
        system_prompt: str = None,
        temperature: float = None,
        max_tokens: int = 2048,
        response_format: dict = None,
    ) -> str:
        """非流式LLM调用，带指数退避重试"""
        if system_prompt is None:
            system_prompt = self.system_prompt
        system_prompt = self._with_skills(system_prompt)
        if temperature is None:
            temperature = LLM_TEMPERATURES.get("resource_generation", 0.7)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        extra = {}
        if response_format:
            extra["response_format"] = response_format

        last_error = None
        for attempt in range(config.MAX_LLM_RETRIES):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=self._fit_max_tokens(max_tokens),
                    temperature=temperature,
                    **extra,
                )
                self.total_calls += 1
                if resp.usage:
                    self.total_tokens += resp.usage.total_tokens
                return resp.choices[0].message.content
            except Exception as e:
                last_error = e
                err_str = str(e)
                if attempt >= config.MAX_LLM_RETRIES - 1:
                    raise
                if "AppIdNoAuthError" in err_str or "401" in err_str or "403" in err_str:
                    raise  # 认证/授权错误不重试
                if "11200" in err_str or "rate_limit" in err_str.lower() or "429" in err_str:
                    wait = min((attempt + 1) * 3, 10)
                else:
                    wait = min(LLM_RETRY_BASE_DELAY * (2 ** attempt), 12)
                self.log(f"LLM调用失败(第{attempt+1}次)，{wait}秒后重试: {err_str[:80]}")
                time.sleep(wait)

    def _call_llm_stream(
        self,
        user_prompt: str,
        system_prompt: str = None,
        temperature: float = None,
        max_tokens: int = 2048,
    ):
        """流式LLM调用 —— 用于对话、资源生成等需要实时反馈的场景"""
        if system_prompt is None:
            system_prompt = self.system_prompt
        system_prompt = self._with_skills(system_prompt)
        if temperature is None:
            temperature = LLM_TEMPERATURES.get("resource_generation", 0.7)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        for attempt in range(config.MAX_LLM_RETRIES):
            try:
                stream = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=self._fit_max_tokens(max_tokens),
                    temperature=temperature,
                    stream=True,
                    stream_options={"include_usage": True},
                )
                self.total_calls += 1
                for chunk in stream:
                    if chunk.usage:
                        self.total_tokens += chunk.usage.total_tokens
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        yield delta.content
                return  # 成功完成
            except Exception as e:
                if attempt >= config.MAX_LLM_RETRIES - 1:
                    raise
                err_str = str(e)
                if "AppIdNoAuthError" in err_str or "401" in err_str or "403" in err_str:
                    raise
                wait = min(LLM_RETRY_BASE_DELAY * (2 ** attempt), 12)
                self.log(f"流式调用失败(第{attempt+1}次)，{wait}秒后重试: {err_str[:80]}")
                time.sleep(wait)

    def _call_llm_json(
        self,
        user_prompt: str,
        temperature: float = None,
        max_tokens: int = 800,
        max_retries: int = 3,
        fallback: Any = None,
        system_prompt: str = None,
    ) -> Any:
        """调用 LLM 并解析 JSON 返回，自动提取 markdown 代码块、自动重试"""
        prompt = user_prompt
        for attempt in range(max_retries):
            raw = self._call_llm(
                prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
            )
            try:
                clean = extract_json(raw)
                return json.loads(clean)
            except (json.JSONDecodeError, ValueError) as e:
                if attempt >= max_retries - 1:
                    if fallback is not None:
                        return fallback
                    raise
                prompt = (
                    user_prompt
                    + f"\n\n⚠️ 上次输出格式错误（{str(e)[:80]}）。"
                    + "请只输出纯 JSON，不要加 ``` 标记或多余解释。"
                )

    def log(self, msg: str, level: str = "INFO"):
        """统一的日志输出，进内存+文件日志方便界面查看"""
        from utils import logger
        if level == "ERROR":
            logger.error(msg, self.name)
        elif level == "WARN":
            logger.warn(msg, self.name)
        else:
            logger.info(msg, self.name)

    def log_error(self, msg: str):
        """错误日志"""
        self.log(msg, "ERROR")
        traceback.print_exc()

    @abstractmethod
    def process(self, **kwargs) -> Any:
        """子类必须实现的主处理逻辑"""
        ...

    def get_stats(self) -> dict:
        """获取Agent运行统计"""
        return {
            "name": self.name,
            "role": self.role,
            "total_calls": self.total_calls,
            "total_tokens": self.total_tokens,
        }
