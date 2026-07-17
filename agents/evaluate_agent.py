"""
Evaluate Agent —— 学习效果评估师
多维度评估 + 掌握度计算 + 动态调整建议
参考 DeepTutor mastery.py 的加权算法 + 知识追踪研究
"""
import json
import time
from typing import Dict, Any
from agents.base_agent import BaseAgent
from config import AGENT_SYSTEM_PROMPTS

class EvaluateAgent(BaseAgent):
    """学习评估师 —— 加分项"""

    _RECENCY_WEIGHTS = (0.5, 0.7, 0.85, 0.95, 1.0)
    _CONFIDENCE_CAP = {1: 0.5, 2: 0.8}

    def __init__(self):
        super().__init__(
            name="Evaluator",
            role="学习评估师",
            system_prompt=AGENT_SYSTEM_PROMPTS["evaluator"],
        )

    def compute_mastery(self, correctness: list[bool]) -> float:
        """计算掌握度 —— 参考 DeepTutor compute_mastery 算法"""
        if not correctness:
            return 0.0

        weights = self._RECENCY_WEIGHTS
        recent = correctness[-len(weights):]
        w = weights[-len(recent):]

        score = sum(wt * (1.0 if c else 0.0) for wt, c in zip(w, recent)) / sum(w)
        return min(score, self._CONFIDENCE_CAP.get(len(recent), 1.0))

    def evaluate_answers(self, exercises: list, student_answers: str, profile: dict) -> dict:
        """批改学生的练习答案"""
        details = []
        total_correct = 0

        if not exercises:
            return {"total_score": 0, "details": [], "strengths": [], "weaknesses": [], "mastery_updates": {}, "suggestion": "没有题目可供评估"}
        for i, ex in enumerate(exercises[:8]):
            question_text = ex.get("question", "")
            correct_answer = ex.get("answer", "")
            question_type = ex.get("type", "题目")

            prompt = f"""请批改学生这道题的答案。

【题目】({question_type}) {question_text}
选项：{json.dumps(ex.get('options', []), ensure_ascii=False)}
【正确答案】{correct_answer}
【学生答案】{student_answers}

返回JSON：
{{
    "is_correct": true或false,
    "comment": "简短评语（20字以内）"
}}
只输出纯JSON。"""

            result = self._call_llm_json(prompt, temperature=0.1, max_tokens=300, max_retries=2,
                                          fallback={"is_correct": False, "comment": "评分解析失败"})
            details.append({
                "question": question_text[:80],
                "student_answer": student_answers[:80],
                "correct_answer": correct_answer,
                "is_correct": result.get("is_correct", False),
                "comment": result.get("comment", ""),
            })
            if result.get("is_correct"):
                total_correct += 1

        total = len(exercises[:8])
        score = round(total_correct / total * 100) if total > 0 else 0

        summary_prompt = f"""学生做了{total}道题，答对了{total_correct}道。
题目涉及：{', '.join([e.get('question', '')[:30] for e in exercises[:5]])}
学生薄弱点：{', '.join(profile.get('struggling_topics', []))}

请生成简短的学习建议（2-3句话）。直接输出文字，不要JSON。"""
        suggestion = self._call_llm(summary_prompt, temperature=0.4, max_tokens=200)

        return {
            "total_score": score,
            "details": details,
            "strengths": [f"答对了{total_correct}/{total}道题"],
            "weaknesses": [d["question"][:50] for d in details if not d.get("is_correct")] or ["无"],
            "mastery_updates": {},
            "suggestion": suggestion.strip(),
        }

    def evaluate_learning_progress(self, learning_history: list, profile: dict) -> dict:
        """评估一段时间的学习进展"""
        if not learning_history:
            return {"trend": "数据不足", "improvement_rate": 0, "insights": []}

        prompt = f"""分析以下学习数据，评估学生的进步情况。

【学习历史】
{json.dumps(learning_history[-20:], ensure_ascii=False, indent=2)}

【学生画像】
{json.dumps(profile, ensure_ascii=False, indent=2)}

返回JSON：
{{
    "trend": "进步明显/稳步提升/原地踏步/有所退步",
    "improvement_rate": 0.0-1.0,
    "strongest_area": "最强领域",
    "weakest_area": "最弱领域",
    "learning_efficiency": "高/中/低",
    "insights": ["洞察1", "洞察2"],
    "recommendations": ["建议1", "建议2"]
}}

只输出纯JSON。"""

        return self._call_llm_json(prompt, temperature=0.3, max_tokens=800, fallback={
            "trend": "数据不足", "improvement_rate": 0, "insights": []})

    def analyze_error_patterns(self, error_records: list) -> dict:
        """分析错误模式，发现系统性知识缺陷"""
        if not error_records:
            return {"systematic_errors": [], "root_causes": []}

        prompt = f"""分析以下错误记录，识别系统性的知识缺陷和错误模式。

【错误记录】
{json.dumps(error_records, ensure_ascii=False, indent=2)}

返回JSON：
{{
    "systematic_errors": [
        {{
            "pattern": "错误模式描述",
            "frequency": 出现次数,
            "root_cause": "根因分析",
            "severity": "高/中/低"
        }}
    ],
    "root_causes": ["深层原因1", "深层原因2"],
    "urgent_actions": ["需要立即处理的问题"]
}}

只输出纯JSON。"""

        return self._call_llm_json(prompt, temperature=0.3, max_tokens=800, fallback={
            "systematic_errors": [], "root_causes": []})

    def process(self, **kwargs) -> Dict[str, Any]:
        exercises = kwargs.get("exercises", [])
        student_answers = kwargs.get("student_answers", "")
        profile = kwargs.get("profile", {})
        learning_history = kwargs.get("learning_history", [])
        error_records = kwargs.get("error_records", [])

        result = {"agent": self.name}

        if exercises and student_answers:
            evaluation = self.evaluate_answers(exercises, student_answers, profile)
            result["evaluation"] = evaluation

            if evaluation.get("details"):
                kp_correctness = {}
                for detail in evaluation["details"]:
                    kp = detail.get("question", "")[:30]
                    if kp not in kp_correctness:
                        kp_correctness[kp] = []
                    kp_correctness[kp].append(detail.get("is_correct", False))

                mastery_updates = {}
                for kp, correctness in kp_correctness.items():
                    mastery_updates[kp] = round(self.compute_mastery(correctness), 2)
                result["mastery_updates"] = mastery_updates

        if learning_history:
            progress = self.evaluate_learning_progress(learning_history, profile)
            result["progress"] = progress

        if error_records:
            error_analysis = self.analyze_error_patterns(error_records)
            result["error_analysis"] = error_analysis

        return result
