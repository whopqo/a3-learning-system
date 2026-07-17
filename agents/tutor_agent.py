"""
Tutor Agent —— 智能辅导老师
多模态答疑 + 引导式教学 + 类比讲解
参考 DeepTutor 的 Solver Agent 双循环架构
"""
import json, re
from typing import Dict, Any
from agents.base_agent import BaseAgent
from config import AGENT_SYSTEM_PROMPTS
from rag.engine import retrieve_knowledge, KB_ONLY_RULE, check_topic_relevance

# 知识库无内容时的统一回复
KB_NOT_FOUND_MSG = (
    "📚 知识库中暂时没有关于这个问题的详细内容。\n\n"
    "建议你先从知识库已覆盖的章节开始学习，或者试试问这些：\n"
    "• 决策树、SVM、神经网络、聚类、线性回归等核心算法\n"
    "• 模型评估、过拟合、正则化等基础概念\n"
    "• 输入「帮我规划学习路径」让我帮你梳理学习路线"
)

class TutorAgent(BaseAgent):
    """一对一辅导老师 —— 加分项"""

    def __init__(self):
        super().__init__(
            name="SmartTutor",
            role="一对一辅导老师",
            system_prompt=AGENT_SYSTEM_PROMPTS["tutor"],
        )

    def analyze_question(self, question: str, profile: dict) -> dict:
        """分析学生问题的深层需求"""
        prompt = f"""分析学生的这个问题，了解他真正困惑的地方。

【学生问题】{question}

【学生画像】
- 薄弱点：{', '.join(profile.get('struggling_topics', []))}
- 错误模式：{', '.join(profile.get('error_patterns', []))}
- 认知风格：{profile.get('cognitive_style', '综合型')}
- 知识基础：{json.dumps(profile.get('knowledge_foundation', {}), ensure_ascii=False)}

返回JSON：
{{
    "core_question": "学生真正想问的核心问题",
    "knowledge_point": "涉及的知识点",
    "difficulty_level": "对学生来说的难度：简单/中等/困难",
    "misunderstanding": "学生可能的误解/困惑点",
    "tutoring_level": 1-4,
    "suggested_analogy": "适合的类比方向"
}}

辅导等级：
1=直接解答，2=提示引导，3=类比讲解，4=苏格拉底追问
只输出纯JSON。"""

        return self._call_llm_json(prompt, temperature=0.3, max_tokens=500, fallback={
            "core_question": question, "knowledge_point": "", "difficulty_level": "中等",
            "misunderstanding": "", "tutoring_level": 2, "suggested_analogy": "",
        })

    def answer_with_rag(self, question: str, analysis: dict, profile: dict) -> str:
        """基于知识库的详细解答 —— 无KB内容则拒绝"""
        rag_context = retrieve_knowledge(question, k=4)

        # 检查知识库是否真的有相关内容
        if self.is_kb_empty(rag_context):
            return KB_NOT_FOUND_MSG

        level = analysis.get("tutoring_level", 2)
        try:
            level = int(level)
            level = max(1, min(4, level))
        except (ValueError, TypeError):
            level = 2
        kb_rule = f"\n{KB_ONLY_RULE}"

        prompts_by_level = {
            1: f"""请直接回答学生的问题。用简单清晰的语言，给出详细的解答。

【知识库参考】
{rag_context[:2500]}

【学生问题】{question}

要求：直接、完整、清晰。用Markdown格式，适当使用emoji。{kb_rule}""",

            2: f"""请用"引导式"的方式回答学生问题。先给出1-2个关键提示，让学生自己思考一下，然后再给出详细解答。

【知识库参考】
{rag_context[:2500]}

【学生问题】{question}

格式：
## 💡 先思考一下
（给出1-2个提示）

## 📖 详细解答
（完整解答）{kb_rule}""",

            3: f"""请用一个生活化的类比来解释这个概念，然后再给出技术上的解答。

【知识库参考】
{rag_context[:2500]}

【学生问题】{question}
【建议类比方向】{analysis.get('suggested_analogy', '生活场景')}

格式：
## 🌟 打个比方
（生活化类比）

## 📖 回到技术
（正式解答）{kb_rule}""",

            4: f"""请用苏格拉底式追问法引导学生。不要直接给答案，而是提出一系列递进的问题，引导学生自己想通。

【知识库参考】
{rag_context[:2500]}

【学生问题】{question}

格式：
## 🤔 我们一起想一想
（提出3-5个递进的问题）

## 💡 自己试试看
鼓励学生自己推导{kb_rule}""",
        }

        prompt = prompts_by_level.get(level, prompts_by_level[2])
        answer = self._call_llm(prompt, temperature=0.5, max_tokens=2000)
        # 引文溯源：出处从检索结果里拿，附在答案末尾
        try:
            from rag.engine import retrieve_context
            sources = []
            for c in retrieve_context(question, k=4):
                s = c.get("source", "")
                if s and s not in sources:
                    sources.append(s)
            if answer and sources:
                answer += "\n\n---\n\n📖 **内容依据**（知识库检索）：" + "、".join(sources[:3])
        except Exception:
            pass
        return answer

    def is_kb_empty(self, rag_context: str) -> bool:
        """检查RAG是否真的返回了相关内容"""
        return "未在知识库中找到" in rag_context or "未找到匹配" in rag_context

    def generate_diagram(self, concept: str) -> str:
        """为概念生成Mermaid流程图——LLM只出节点和连线的JSON，图代码由程序拼，语法必然合法"""
        if not concept or len(concept) < 2:
            return ""
        kb_ref = retrieve_knowledge(concept, k=3)
        prompt = f"""为「{concept}」设计一个概念流程图的结构。知识库里已经有这个概念的定义和原理，你只需要梳理它们之间的逻辑流程。

知识库参考（术语从这里取）：
{kb_ref[:2000]}

把核心步骤或子概念串成一条推理链。边上如果能有简短文字描述就更好（如 B --计算--> C 这种），需要8-14个节点，标注主要内容。返回 JSON：
{{
  "nodes": [{{"id": "A", "label": "节点文字(10字内)"}}, {{"id": "B", "label": "..."}}, ...],
  "edges": [["A", "B"], ["B", "C"], ...]
}}
要求：id 用大写字母，edges 里的 id 必须在 nodes 里存在。节点文字纯中文。写清楚节点之间的关系和流动。
只输出纯 JSON，连 ``` 都不要。"""

        data = self._call_llm_json(prompt, temperature=0.3, max_tokens=1200, fallback={})
        return self._build_mermaid(data)

    @staticmethod
    def _build_mermaid(data: dict) -> str:
        """从节点/连线数据拼mermaid代码，标签强制清洗，拼出来的语法不会炸"""
        if not isinstance(data, dict):
            return ""
        nodes = data.get("nodes") or []
        edges = data.get("edges") or []
        if len(nodes) < 2 or not edges:
            return ""
        lines = ["flowchart TD"]
        ids = set()
        for n in nodes[:12]:
            nid = re.sub(r'[^A-Za-z0-9_]', '', str(n.get("id", "")))[:8]
            label = re.sub(r'[\[\]{}()（）"\'`:：;；,，<>|#&\n]', ' ', str(n.get("label", ""))).strip()[:16]
            if nid and label:
                ids.add(nid)
                lines.append(f'{nid}["{label}"]')
        for e in edges[:22]:
            if isinstance(e, (list, tuple)) and len(e) >= 2:
                a = re.sub(r'[^A-Za-z0-9_]', '', str(e[0]))[:8]
                b = re.sub(r'[^A-Za-z0-9_]', '', str(e[1]))[:8]
                if a in ids and b in ids and a != b:
                    lbl = re.sub(r'[\[\]{}()（）"\'`<>#&|\n]', ' ', str(e[2] or "")).strip() if len(e) >= 3 else ""
                    if lbl and len(lbl) <= 12:
                        lines.append(f'{a} -- {lbl} --> {b}')
                    else:
                        lines.append(f'{a} --> {b}')
        # 得有节点也得有线，否则不如不给
        if len(lines) < 4 or not any('-->' in l for l in lines):
            return ""
        return "\n".join(lines)

    @staticmethod
    def _sanitize_mermaid(raw: str) -> str:
        """把LLM输出清洗成尽量不炸的mermaid：去围栏、掐掉解说文字、标签去危险字符"""
        if not raw:
            return ""
        raw = raw.replace("```mermaid", "").replace("```", "").strip()
        idx = raw.find("flowchart")
        if idx == -1:
            return ""  # 连flowchart开头都没有，不要了
        raw = raw[idx:]
        # 节点标签里的括号引号冒号这些字符是语法炸弹，统一换成空格
        def _clean(m):
            inner = re.sub(r'[\[\]{}()（）"\'`:：;；,，<>|#&]', ' ', m.group(1))
            return '[' + (inner.strip() or '节点') + ']'
        raw = re.sub(r'\[([^\]]*)\]', _clean, raw)
        # 只保留像mermaid语句的行，LLM夹带的解说文字丢掉
        lines = [l.rstrip() for l in raw.splitlines() if l.strip()]
        keep = [lines[0]]
        for l in lines[1:]:
            s = l.strip()
            if ("-->" in s or "---" in s or re.match(r'^[A-Za-z0-9_]+\[', s)
                    or s.startswith(("subgraph", "end", "classDef", "class ", "style "))):
                keep.append(l)
        if len(keep) < 3:
            return ""  # 太残缺不如不给，前端有兜底
        return "\n".join(keep)

    def generate_mini_video_script(self, concept: str, explanation: str) -> str:
        """为概念生成1分钟微课脚本 —— 基于已校验的解答内容"""
        prompt = f"""请为「{concept}」写一段60秒的短视频讲解脚本。

核心内容（已通过知识库校验）：{explanation[:500]}

格式：
---
【0-10秒】引入
画面：...
旁白：...

【10-30秒】核心讲解
画面：...
旁白：...

【30-50秒】实例演示
画面：...
旁白：...

【50-60秒】总结
画面：...
旁白：...
---

旁白要口语化，画面描述要具体可执行。
{KB_ONLY_RULE}
直接输出脚本。"""

        return self._call_llm(prompt, temperature=0.6, max_tokens=800)

    def process(self, **kwargs) -> Dict[str, Any]:
        question = kwargs.get("question", "")
        profile = kwargs.get("profile", {})
        include_diagram = kwargs.get("include_diagram", True)
        include_video = kwargs.get("include_video", False)

        analysis = self.analyze_question(question, profile)
        self.log(f"问题分析: {analysis.get('core_question', question)}")

        answer = self.answer_with_rag(question, analysis, profile)

        diagram = None
        if include_diagram:
            try:
                diagram = self.generate_diagram(analysis.get("knowledge_point", question))
            except Exception:
                pass

        video_script = None
        if include_video:
            try:
                video_script = self.generate_mini_video_script(
                    analysis.get("knowledge_point", question), answer)
            except Exception:
                pass

        return {
            "agent": self.name,
            "analysis": analysis,
            "answer": answer,
            "diagram": diagram,
            "video_script": video_script,
        }
