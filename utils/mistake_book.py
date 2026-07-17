"""
错题本 —— 错题落盘存储 + 复习卷生成（学 DeepTutor 的错题追踪）
存 db/mistakes.json，按会话分组，每题记知识点方便针对性复习
"""
import os
import json
import time
import threading

from config import PROJ_ROOT

_FILE = os.path.join(PROJ_ROOT, "db", "mistakes.json")
_lock = threading.Lock()

def _load() -> dict:
    try:
        with open(_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def add_mistakes(session_id: str, topic: str, wrong_results: list, exercises: list):
    """把这次答错的题存进错题本，带上知识点"""
    if not session_id or not wrong_results:
        return
    entries = []
    for r in wrong_results:
        idx = r.get("index", -1)
        kp = exercises[idx].get("knowledge_point", "") if 0 <= idx < len(exercises) else ""
        entries.append({
            "time": time.strftime("%Y-%m-%d %H:%M"),
            "topic": topic,
            "question": r.get("question", "")[:200],
            "student_answer": r.get("student_answer", "")[:100],
            "correct_answer": r.get("correct_answer", "")[:100],
            "explanation": r.get("explanation", "")[:300],
            "knowledge_point": kp,
        })
    with _lock:
        data = _load()
        lst = data.get(session_id, [])
        lst.extend(entries)
        data[session_id] = lst[-100:]  # 每个会话最多留100道
        os.makedirs(os.path.dirname(_FILE), exist_ok=True)
        with open(_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

def list_mistakes(session_id: str, n: int = 50) -> list:
    data = _load()
    return data.get(session_id, [])[-n:]

def clear_mistakes(session_id: str):
    with _lock:
        data = _load()
        data.pop(session_id, None)
        with open(_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

def build_review_prompt(mistakes: list, rag_context: str) -> str:
    """根据错题生成复习卷的提示词，出变式题而不是原题"""
    wrong_text = "\n".join(
        f"- [{m.get('knowledge_point') or m.get('topic','')}] {m['question'][:80]}（学生答错：{m['student_answer'][:40]}，正确：{m['correct_answer'][:40]}）"
        for m in mistakes[-10:])
    return f"""学生之前做错了下面这些题，请针对同样的知识点出5道【新的变式题】帮他复习巩固。
不要出原题，要换角度考同一个知识点。

【学生的错题】
{wrong_text}

【知识库内容】
{rag_context[:2000]}

返回JSON数组，每题格式：
{{"type": "单选题/判断题/简答题", "question": "题目", "options": ["A","B","C","D"], "answer": "正确答案", "explanation": "解析", "knowledge_point": "知识点"}}
判断题options填["对","错"]。简答题不填options。选择题选项必须具体。
题干直接问知识本身，不要出现"根据知识库/教材"字样。
只输出纯JSON数组。"""
