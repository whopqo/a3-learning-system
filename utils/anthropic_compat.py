"""
Anthropic 协议翻译器 —— 让 Claude 格式的接口伪装成 OpenAI 客户端
base_agent 不用改一行代码，照常调 client.chat.completions.create()
协议差异（参考 inkos provider.ts 的实现）：
  地址 /messages、密钥放 x-api-key 头、system 提示词放顶层、max_tokens 必填
  流式事件: content_block_delta 取正文, message_stop 是正常结束标志
"""
import json
import httpx
from types import SimpleNamespace


class AnthropicClient:
    """接口形状模仿 openai.OpenAI，只实现项目里用到的部分"""

    def __init__(self, base_url: str, api_key: str, timeout: int = 120):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.models = SimpleNamespace(list=self._list_models)

    def _headers(self):
        return {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
            # 非官方网关有的认 Bearer，两个都带上兼容性最好
            "Authorization": f"Bearer {self.api_key}",
        }

    def _build_payload(self, model, messages, max_tokens, temperature, stream):
        # anthropic 的 messages 里不允许 system 角色，要提出来放顶层
        sys_parts = [m["content"] for m in messages if m["role"] == "system"]
        payload = {
            "model": model,
            "messages": [m for m in messages if m["role"] != "system"],
            "max_tokens": max_tokens or 2048,  # anthropic 必填
            "temperature": temperature,
            "stream": stream,
        }
        if sys_parts:
            payload["system"] = "\n\n".join(sys_parts)
        return payload

    def _create(self, model=None, messages=None, max_tokens=None, temperature=None,
                stream=False, stream_options=None, **kwargs):
        payload = self._build_payload(model, messages, max_tokens, temperature, stream)
        if stream:
            return self._stream(payload)
        r = httpx.post(f"{self.base_url}/messages", headers=self._headers(),
                       json=payload, timeout=self.timeout)
        if r.status_code >= 400:
            raise RuntimeError(f"Anthropic接口错误 {r.status_code}: {r.text[:200]}")
        data = r.json()
        text = "".join(p.get("text", "") for p in data.get("content", []))
        usage = data.get("usage", {})
        pt, ct = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
        # 拼成 OpenAI 返回的形状
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
            usage=SimpleNamespace(prompt_tokens=pt, completion_tokens=ct, total_tokens=pt + ct),
        )

    def _stream(self, payload):
        """流式：SSE 逐事件解析，转成 OpenAI chunk 的形状 yield 出去"""
        pt = ct = 0
        got_stop = False
        with httpx.stream("POST", f"{self.base_url}/messages", headers=self._headers(),
                          json=payload, timeout=self.timeout) as r:
            if r.status_code >= 400:
                r.read()
                raise RuntimeError(f"Anthropic接口错误 {r.status_code}: {r.text[:200]}")
            for line in r.iter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw:
                    continue
                try:
                    ev = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                et = ev.get("type", "")
                if et == "message_start":
                    pt = ev.get("message", {}).get("usage", {}).get("input_tokens", 0)
                elif et == "content_block_delta":
                    d = ev.get("delta", {})
                    if d.get("type") == "text_delta" and d.get("text"):
                        yield SimpleNamespace(usage=None, choices=[SimpleNamespace(
                            delta=SimpleNamespace(content=d["text"]))])
                elif et == "message_delta":
                    ct = ev.get("usage", {}).get("output_tokens", 0)
                elif et == "message_stop":
                    got_stop = True
        # 网关中途掐断时流会"正常"关闭但没有结束标志，要报错让上层重试而不是当成写完了
        if not got_stop:
            raise RuntimeError("流式响应被中途截断（未收到 message_stop）")
        yield SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=pt, completion_tokens=ct, total_tokens=pt + ct),
            choices=[])

    def _list_models(self):
        r = httpx.get(f"{self.base_url}/models", headers=self._headers(), timeout=10)
        if r.status_code >= 400:
            raise RuntimeError(f"{r.status_code}: {r.text[:150]}")
        data = r.json().get("data", [])
        return SimpleNamespace(data=[SimpleNamespace(id=m.get("id", "")) for m in data])
