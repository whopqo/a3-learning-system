"""
Memory Agent —— 系统记忆管理员
三层记忆架构：L1原始交互 → L2知识点 → L3学习策略
"""
import json
import time
import os
from typing import Dict, Any
from agents.base_agent import BaseAgent
from config import AGENT_SYSTEM_PROMPTS, PROJ_ROOT


class MemoryAgent(BaseAgent):
    """记忆管理Agent —— 管理三层记忆"""

    def __init__(self):
        super().__init__(
            name="MemoryManager",
            role="系统记忆管理员",
            system_prompt=AGENT_SYSTEM_PROMPTS["memory_manager"],
        )
        self.memory_dir = os.path.join(PROJ_ROOT, "db", "memory")
        os.makedirs(self.memory_dir, exist_ok=True)
        self._l1_file = os.path.join(self.memory_dir, "l1_raw_interactions.json")
        self._l2_file = os.path.join(self.memory_dir, "l2_knowledge_state.json")
        self._l3_file = os.path.join(self.memory_dir, "l3_learning_strategy.json")

    def record_interaction(self, session_id: str, user_msg: str, agent_response: str,
                           agent_name: str = "", metadata: dict = None) -> dict:
        """记录L1原始交互"""
        record = {
            "session_id": session_id,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "agent_name": agent_name,
            "user_message": user_msg[:500],
            "agent_response": agent_response[:500],
            "metadata": metadata or {},
        }
        self._append_to_file(self._l1_file, record)
        return record

    def update_knowledge_state(self, student_id: str, knowledge_updates: dict) -> dict:
        """更新L2知识状态"""
        l2_data = self._read_file(self._l2_file) or {}
        student_key = str(student_id)

        if student_key not in l2_data:
            l2_data[student_key] = {
                "mastered_knowledge": {},
                "weak_knowledge": {},
                "learning_history": [],
                "last_updated": "",
            }

        student_data = l2_data[student_key]

        for kp, score in knowledge_updates.items():
            if score >= 0.7:
                student_data["mastered_knowledge"][kp] = {
                    "score": score,
                    "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                student_data["weak_knowledge"].pop(kp, None)
            else:
                student_data["weak_knowledge"][kp] = {
                    "score": score,
                    "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                }

        student_data["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        l2_data[student_key] = student_data
        self._write_file(self._l2_file, l2_data)

        return student_data

    def summarize_learning_strategy(self, student_id: str, l2_data: dict) -> dict:
        """基于L2数据生成L3学习策略"""
        student_data = l2_data.get(str(student_id), {})

        prompt = f"""基于以下学习数据，总结个性化学习策略。

【知识掌握情况】
已掌握：{json.dumps(student_data.get('mastered_knowledge', {}), ensure_ascii=False)}
薄弱点：{json.dumps(student_data.get('weak_knowledge', {}), ensure_ascii=False)}

返回JSON：
{{
    "optimal_session_length": 建议的单次学习时长（分钟）,
    "best_time_of_day": "最佳学习时段",
    "most_effective_resource_type": "最有效的资源类型",
    "recommended_pace": "快/适中/慢",
    "review_interval_days": 建议复习间隔天数,
    "strategy_notes": "其他策略建议"
}}

只输出纯JSON。"""

        strategy = self._call_llm_json(prompt, temperature=0.3, max_tokens=500, fallback={})
        if strategy:
            l3_data = self._read_file(self._l3_file) or {}
            l3_data[str(student_id)] = {
                **strategy,
                "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            self._write_file(self._l3_file, l3_data)
        return strategy

    def retrieve_memory(self, student_id: str, level: str = "L2", query: str = None) -> dict:
        """检索记忆"""
        if level == "L1":
            l1_data = self._read_file(self._l1_file) or []
            if query:
                return [r for r in l1_data if query.lower() in json.dumps(r, ensure_ascii=False).lower()][-20:]
            return l1_data[-50:] if isinstance(l1_data, list) else l1_data
        elif level == "L2":
            l2_data = self._read_file(self._l2_file) or {}
            return l2_data.get(str(student_id), {})
        elif level == "L3":
            l3_data = self._read_file(self._l3_file) or {}
            return l3_data.get(str(student_id), {})
        return {}

    def get_full_context(self, student_id: str) -> dict:
        """获取学生的完整上下文（L1+L2+L3）"""
        return {
            "student_id": student_id,
            "l2_knowledge": self.retrieve_memory(student_id, "L2"),
            "l3_strategy": self.retrieve_memory(student_id, "L3"),
            "retrieved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _read_file(self, filepath: str) -> Any:
        try:
            if os.path.exists(filepath):
                with open(filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return None

    def _write_file(self, filepath: str, data: Any):
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _append_to_file(self, filepath: str, record: dict):
        data = self._read_file(filepath) or []
        if isinstance(data, list):
            data.append(record)
            if len(data) > 1000:
                data = data[-500:]
            self._write_file(filepath, data)

    def process(self, **kwargs) -> Dict[str, Any]:
        action = kwargs.get("action", "record")
        student_id = kwargs.get("student_id", "default")
        session_id = kwargs.get("session_id", "default")

        if action == "record":
            record = self.record_interaction(
                session_id=session_id,
                user_msg=kwargs.get("user_message", ""),
                agent_response=kwargs.get("agent_response", ""),
                agent_name=kwargs.get("agent_name", ""),
                metadata=kwargs.get("metadata"),
            )
            return {"agent": self.name, "action": "record", "record": record}

        elif action == "update_knowledge":
            state = self.update_knowledge_state(
                student_id=student_id,
                knowledge_updates=kwargs.get("knowledge_updates", {}),
            )
            return {"agent": self.name, "action": "update_knowledge", "state": state}

        elif action == "summarize_strategy":
            l2_raw = self.retrieve_memory(student_id, "L2") or {}
            l2_data = {str(student_id): l2_raw}
            strategy = self.summarize_learning_strategy(student_id, l2_data)
            return {"agent": self.name, "action": "summarize_strategy", "strategy": strategy}

        elif action == "retrieve":
            memory = self.retrieve_memory(
                student_id=student_id,
                level=kwargs.get("level", "L2"),
                query=kwargs.get("query"),
            )
            return {"agent": self.name, "action": "retrieve", "memory": memory}

        elif action == "full_context":
            context = self.get_full_context(student_id)
            return {"agent": self.name, "action": "full_context", "context": context}

        return {"agent": self.name, "action": action, "error": "未知操作"}
