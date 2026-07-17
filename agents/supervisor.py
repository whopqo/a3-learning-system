"""
Supervisor Agent —— 多智能体系统的中央协调者
主要用途：提供通用 LLM 调用能力给 handler 层的 _smart_guide 和 general_chat
"""
from typing import Any
from agents.base_agent import BaseAgent
from config import AGENT_SYSTEM_PROMPTS

class SupervisorAgent(BaseAgent):
    """协调者Agent —— handler 通过它调用 LLM 做引导和闲聊"""

    def __init__(self):
        super().__init__(
            name="EduSupervisor",
            role="学习协调者",
            system_prompt=AGENT_SYSTEM_PROMPTS["supervisor"],
        )

    def process(self, **kwargs) -> dict[str, Any]:
        """占位——实际路由由 handler._quick_intent 完成"""
        return {"agent": self.name, "status": "ok"}
