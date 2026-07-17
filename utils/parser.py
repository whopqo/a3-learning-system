"""
解析器 —— 把LLM返回的自由文本提取出JSON
被 BaseAgent._call_llm_json 调用，不要直接使用
"""
import json
import re

def extract_json(text: str) -> str:
    """从文本里提取JSON，去掉markdown代码块等噪音"""
    if not text or not isinstance(text, str):
        raise ValueError("输入为空或不是字符串")

    text = text.strip()

    # 推理型模型会带 <think>...</think> 思考块，先剥掉再找JSON
    text = re.sub(r'<think>[\s\S]*?</think>', '', text).strip()

    # 尝试匹配 ```json ... ``` 或 ``` ... ``` 代码块
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if m:
        return m.group(1).strip()

    # 没有代码块，看数组和对象谁先出现。数组开头在前的话必须按数组截取，
    # 不然会把外层[]丢掉，返回"{...},{...}"这种解析必炸的东西
    brace = text.find("{")
    bracket = text.find("[")
    if bracket != -1 and (brace == -1 or bracket < brace):
        end = text.rfind("]")
        if end > bracket:
            return text[bracket:end + 1]
    if brace != -1:
        end = text.rfind("}")
        if end > brace:
            return text[brace:end + 1]

    return text

def sanitize_json(text: str) -> str:
    """处理JSON字符串中的控制字符（在字符串值内部转义）"""
    result = []
    in_string = False
    escape_next = False
    mapping = {"\n": "n", "\r": "r", "\t": "t", "\b": "b", "\f": "f"}
    for ch in text:
        if escape_next:
            result.append(ch)
            escape_next = False
            continue
        if ch == "\\" and in_string:
            result.append(ch)
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
        if in_string and ch in mapping:
            result.append("\\" + mapping[ch])
        else:
            result.append(ch)
    return "".join(result)
