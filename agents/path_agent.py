"""
Path Agent —— 个性化学习路径规划师
基于学生画像 + 知识图谱 + LLM 生成阶段式学习计划
"""
import json
import time
from typing import Dict, Any, List, Set
from agents.base_agent import BaseAgent
from config import AGENT_SYSTEM_PROMPTS
from utils.knowledge_graph import get_knowledge_graph
from rag.engine import retrieve_knowledge, retrieve_context

def _score_label(v: float) -> str:
    if v < 0.25: return "零基础"
    if v < 0.4: return "接近零基础"
    if v < 0.55: return "一般"
    if v < 0.75: return "不错"
    return "很强"

class PathAgent(BaseAgent):
    """学习路径规划师 —— 个性化阶段式路径"""

    def __init__(self):
        super().__init__(
            name="PathPlanner",
            role="学习路径规划师",
            system_prompt=AGENT_SYSTEM_PROMPTS["path_planner"],
        )
        self.kg = get_knowledge_graph()

    def _match_node(self, node_name: str, topic_text: str) -> bool:
        nl = node_name.lower()
        tl = topic_text.lower()
        return nl in tl or tl in nl

    def analyze_knowledge_state(self, profile: dict) -> tuple[Set[str], List[str]]:
        """从画像推断已掌握章节"""
        mastered = set()
        weaknesses = []
        mastered_topics = profile.get("mastered_topics", [])
        struggling_topics = profile.get("struggling_topics", [])
        foundation = profile.get("knowledge_foundation", {})

        all_nodes = sorted(self.kg.get_all_nodes(), key=lambda n: n.get("order", 999))

        # 画像里明确说掌握了的话题
        for node in all_nodes:
            node_name = node.get("name", "")
            for mt in mastered_topics:
                if self._match_node(node_name, mt):
                    mastered.add(node["id"])
                    break
            for st in struggling_topics:
                if self._match_node(node_name, st):
                    weaknesses.append(node["id"])
                    break

        # 根据知识基础推断可跳过的入门章
        if not mastered:
            math = foundation.get("math", 0.4)
            prog = foundation.get("programming", 0.4)
            ml = foundation.get("ml_prerequisites", 0.4)
            avg = (math + prog + ml) / 3
            if avg >= 0.8:
                skip = 2  # 跳过绪论和模型评估
            elif avg >= 0.7:
                skip = 1  # 跳绪论
            else:
                skip = 0
            for node in all_nodes:
                order = node.get("order", 0)
                if 0 < order <= skip:
                    mastered.add(node["id"])

        return mastered, weaknesses

    def _build_profile_snapshot(self, profile: dict) -> str:
        """把画像转成一段人能读懂的文字"""
        fd = profile.get("knowledge_foundation", {})
        ml_val = fd.get("ml_prerequisites", 0.4)
        prog_val = fd.get("programming", 0.4)
        math_val = fd.get("math", 0.4)

        levels = [(0.0, "零基础"), (0.3, "接近零基础"), (0.45, "一般"), (0.65, "不错"), (0.85, "很强")]
        ml_str = _score_label(fd.get("ml_prerequisites", 0.4))
        prog_str = _score_label(fd.get("programming", 0.4))
        math_str = _score_label(fd.get("math", 0.4))

        parts = [f"- ML基础：{ml_str}"]
        parts.append(f"- 编程水平：{prog_str}")
        parts.append(f"- 数学基础：{math_str}")
        if profile.get("short_term_goal"):
            parts.append(f"- 学习目标：{profile['short_term_goal']}")
        if profile.get("cognitive_style"):
            parts.append(f"- 学习风格：{profile['cognitive_style']}")
        if profile.get("struggling_topics"):
            parts.append(f"- 薄弱点：{', '.join(profile['struggling_topics'][:5])}")
        if profile.get("mastered_topics"):
            parts.append(f"- 已掌握：{', '.join(profile['mastered_topics'][:5])}")
        return "\n".join(parts)

    def generate_personalized_path(self, profile: dict) -> dict:
        """根据画像用 LLM 生成阶段式个性化学习路径"""
        snapshot = self._build_profile_snapshot(profile)

        # 注入已掌握/薄弱知识点（来自analyze_knowledge_state）
        mastered, weaknesses = self.analyze_knowledge_state(profile)
        if mastered:
            mastered_names = [n.get("name","") for n in self.kg.get_all_nodes() if n.get("id") in mastered]
            snapshot += f"\n- 已掌握（可跳过）：{', '.join(mastered_names[:6])}"
        if weaknesses:
            weak_names = [n.get("name","") for n in self.kg.get_all_nodes() if n.get("id") in weaknesses]
            snapshot += f"\n- 薄弱点（需加强）：{', '.join(weak_names[:6])}"

        # 从知识库获取课程大纲信息（KB未构建时有兜底）
        try:
            kb_info = retrieve_knowledge("机器学习 绪论 目录 章节", k=6)
            kb_info = kb_info[:3000] if kb_info else "（知识库内容）"
        except Exception:
            kb_info = "机器学习课程知识库内容"

        # 从知识图谱获取全部章节列表
        all_nodes = sorted(self.kg.get_all_nodes(), key=lambda n: n.get("order", 999))
        chapter_list = "\n".join([
            f"- {n.get('name','')}（{n.get('difficulty','中等')}·约{n.get('hours',2)}h）"
            for n in all_nodes if n.get("order", 999) < 900
        ])

        eval_ctx = ""
        if profile.get('_eval_feedback'):
            eval_ctx = f"""
【最近评估反馈】
{profile['_eval_feedback']}
【当前学习进度】
{profile.get('_current_progress')}
根据评估结果调整后续阶段的难度和内容。"""

        prompt = f"""你是一位有10年高校教学经验的课程设计师。请根据学生画像，设计一份**个性化的阶段式学习路径**。

【学生画像】
{snapshot}
{eval_ctx}

【课程知识库内容摘录】
{kb_info}

【课程全部章节】（供你挑选和组合）
{chapter_list}

要求：
1. 根据画像定制阶段数和内容。零基础学生可能需要5-6个阶段从预备知识开始，有基础的学生可以压缩到3个阶段
2. 每个阶段要有：阶段名称、时长、学习目标、具体内容（哪些章节+额外建议）、动手任务、推荐资源
3. 学习路径必须引用知识库中存在的章节（不要编造章节名），但可以补充学习建议
4. 根据薄弱点加强对应内容，已掌握的可以标注"跳过"或"快速复习"
5. 不要照搬章节顺序，要根据学生的实际水平重新组织

输出 JSON：
{{
    "course_name": "机器学习个性化学习路径",
    "overview": "针对该学生的整体学习建议（2-3句话）",
    "phases": [
        {{
            "phase": 1,
            "title": "阶段名称（如：预备知识补强）",
            "duration": "2-4周",
            "goal": "这个阶段的学习目标",
            "chapters": ["知识库存在的章节名1", "章节名2"],
            "extra_content": "补充内容描述（数学基础、编程练习等具体建议）",
            "tasks": ["动手任务1", "动手任务2"],
            "resources": ["推荐书/课程1", "推荐书/课程2"],
            "difficulty": "入门"
        }}
    ],
    "total_phases": 阶段数,
    "estimated_total_weeks": "总共需要多少周"
}}

只输出纯 JSON。"""

        try:
            result = self._call_llm_json(prompt, temperature=0.5, max_tokens=3000, fallback=None)
            if result and result.get("phases"):
                result["created_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                result["type"] = "personalized"
                return result
        except Exception:
            pass

        # LLM 失败 → 退回到简化版个性化路径
        return self._fallback_personalized_path(profile, all_nodes)

    def _fallback_personalized_path(self, profile: dict, all_nodes: list) -> dict:
        """简化版个性化路径——按画像分组章节"""
        fd = profile.get("knowledge_foundation", {})
        math_val = fd.get("math", 0.4)
        prog_val = fd.get("programming", 0.4)
        ml_val = fd.get("ml_prerequisites", 0.4)
        goal = profile.get("short_term_goal", "学习机器学习")
        avg = (math_val + prog_val + ml_val) / 3

        phases = []
        chapter_nodes = [n for n in all_nodes if n.get("order", 999) < 900]

        if avg < 0.5:
            # 零基础 → 加上预备阶段
            phases.append({
                "phase": 1, "title": "预备知识补强",
                "duration": "2-4周",
                "goal": "打好Python和数学基础",
                "chapters": [],
                "extra_content": "Python编程基础、线性代数入门、概率统计概念",
                "tasks": ["用Python写简单的数据处理脚本", "理解梯度下降的直观含义"],
                "resources": ["吴恩达《机器学习》课程", "3Blue1Brown数学视频"],
                "difficulty": "入门",
            })

        # 基础阶段
        beginner_nodes = [n for n in chapter_nodes if n.get("difficulty") == "入门"]
        phases.append({
            "phase": len(phases) + 1, "title": "机器学习基础",
            "duration": "3-4周",
            "goal": "掌握机器学习基本概念和简单模型",
            "chapters": [n["name"] for n in beginner_nodes[:3]],
            "extra_content": "理解监督学习vs无监督学习，掌握模型评估方法",
            "tasks": ["用sklearn跑通线性回归和决策树"],
            "resources": ["《机器学习》周志华 前3章", "sklearn官方教程"],
            "difficulty": "入门",
        })

        # 核心算法阶段
        core_nodes = [n for n in chapter_nodes if n.get("difficulty") in ("中等", "进阶")][:5]
        phases.append({
            "phase": len(phases) + 1, "title": "核心算法深入",
            "duration": "4-6周",
            "goal": "掌握主流ML算法原理和实战",
            "chapters": [n["name"] for n in core_nodes],
            "extra_content": "每个算法都要手写核心代码+调包对比",
            "tasks": ["在真实数据集上对比5种算法的效果"],
            "resources": ["sklearn文档", "Kaggle入门竞赛"],
            "difficulty": "中等",
        })

        return {
            "course_name": "机器学习个性化学习路径",
            "overview": f"针对{goal}目标定制的学习计划，基础水平评估：{'入门' if avg < 0.5 else '进阶'}",
            "phases": phases,
            "total_phases": len(phases),
            "type": "personalized",
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    def process(self, **kwargs) -> Dict[str, Any]:
        profile = kwargs.get("profile", {})
        current_path = kwargs.get("current_path")
        evaluation = kwargs.get("evaluation")

        # 评优反馈调整——将当前进度注入prompt
        if evaluation and current_path:
            profile = dict(profile)
            profile["_eval_feedback"] = json.dumps(evaluation, ensure_ascii=False)
            profile["_current_progress"] = json.dumps(current_path.get("phases", current_path.get("steps",[]))[:3], ensure_ascii=False)

        path = self.generate_personalized_path(profile)

        return {"agent": self.name, "learning_path": path}
