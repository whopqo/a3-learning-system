"""
Resource Agent —— 多模态资源生成器
产出至少5种学习资源：讲解文档、思维导图、练习题、拓展阅读、代码案例、PPT大纲、视频脚本
参考 MetaGPT SOP流水线 + DeepTutor Research Agent
"""
import json
import re
import time
from typing import Dict, Any, List
from agents.base_agent import BaseAgent
from config import AGENT_SYSTEM_PROMPTS, RESOURCE_TYPES
from rag.engine import retrieve_knowledge, retrieve_context, KB_ONLY_RULE, extract_reading_materials, extract_stories


def _mindmap_from_markdown(topic: str, md_text: str) -> str:
    """AI 输出了 Markdown 标题 → 直接传给前端用 Markmap 渲染。无交互导图，零语法错误"""
    if not md_text:
        return _default_mindmap(topic)
    # 确保有根标题
    txt = md_text.strip()
    if not txt.startswith("#"):
        txt = f"# {topic}\n{txt}"
    return txt


def _default_mindmap(topic: str) -> str:
    return f"# {topic}\n\n## 基本概念\n### 定义与背景\n### 核心思想\n\n## 关键方法\n### 主要算法\n### 评估指标\n\n## 应用场景\n### 经典案例\n### 工具与框架"


class ResourceAgent(BaseAgent):
    """资源生成Agent —— 生成7种类型的学习资源"""

    def __init__(self):
        super().__init__(
            name="ResourceGenerator",
            role="课件生成师",
            system_prompt=AGENT_SYSTEM_PROMPTS["resource_generator"],
        )

    def plan_resources(self, student_profile: dict, topic: str, outline: dict = None) -> dict:
        """资源规划 —— 根据学生画像决定生成哪些资源"""
        # 先检索知识库
        rag_result = retrieve_knowledge(topic, k=5)

        prompt = f"""请根据学生画像和知识库内容，制定资源生成计划。

【学生画像】
{json.dumps(student_profile, ensure_ascii=False, indent=2)}

【主题】{topic}

【知识库内容】
{rag_result[:2000]}

返回JSON格式的资源计划：
{{
    "topic": "主题",
    "plan": [
        {{
            "type": "资源类型",
            "title": "资源标题",
            "difficulty": "入门/中等/进阶",
            "order": 排序号,
            "reason": "为什么生成这个资源"
        }}
    ]
}}

资源类型可选：lecture_notes, mind_map, exercises, reading_materials, extended_reading, code_example, ppt_outline, video_script
至少规划5种类型。只输出纯JSON。"""

        result = self._call_llm_json(prompt, temperature=0.4, max_tokens=1000,
                                     max_retries=2, fallback=None)
        if result and result.get("plan"):
            return result
        return {"topic": topic, "plan": [
            {"type": "lecture_notes", "title": f"{topic}讲解文档", "difficulty": "中等", "order": 1},
            {"type": "mind_map", "title": f"{topic}思维导图", "difficulty": "入门", "order": 2},
            {"type": "exercises", "title": f"{topic}练习题", "difficulty": "中等", "order": 3},
            {"type": "extended_reading", "title": f"{topic}拓展阅读", "difficulty": "进阶", "order": 4},
            {"type": "code_example", "title": f"{topic}代码案例", "difficulty": "中等", "order": 5},
        ]}

    def generate_lecture_notes(self, topic: str, profile: dict, rag_context: str) -> str:
        """生成Markdown讲解文档 —— 根据画像个性化"""
        style = profile.get('cognitive_style', '综合型')
        level = profile.get('difficulty_level', '中级')
        abs_level = profile.get('abstraction_level', 0.5)
        gaps = ', '.join(profile.get('struggling_topics', [topic]) or [topic])
        prefs = ', '.join(profile.get('preferred_formats', ['文档']))

        # 根据画像生成不同的写作风格要求
        style_guide = ""
        if abs_level < 0.4 or '动手型' in style or '视觉型' in style:
            style_guide = ("\n写作风格（因为学生偏好生动具体）："
                           "\n- 每个概念必须配一个生活化的比喻或故事"
                           "\n- 大量使用emoji和表情符号增加趣味"
                           "\n- 用「就像…」「想象一下…」这类引导语"
                           "\n- 避免大段抽象定义，用场景化描述替代")
        elif abs_level > 0.7 or '文字型' in style:
            style_guide = ("\n写作风格（因为学生偏好严谨规范）："
                           "\n- 术语严格准确，必要时标注英文原文"
                           "\n- 数学公式用LaTeX，推导步骤完整"
                           "\n- 结构用正式学术层级（定义→定理→推论→例题）"
                           "\n- 引用经典教材和论文作为依据")

        prompt = f"""请根据知识库内容，写一份关于「{topic}」的完整Markdown讲解文档。

【知识库参考】
{rag_context[:3000]}

【学生画像】
- 认知风格：{style}
- 难度级别：{level}
- 抽象偏好：{abs_level:.0%}（0=喜欢具象, 1=喜欢抽象）
- 薄弱点：{gaps}
- 偏好格式：{prefs}
{style_guide}

【生成策略】{profile.get('_emphasis', '概念和公式平衡。')}
【语言风格】{profile.get('_tone', '平衡学术严谨和通俗易懂。')}

要求：
1. 至少3个小节，结构清晰
2. 根据上方生成策略调整内容深度，根据语言风格调整表达方式
3. 对学生的薄弱点要有专门的重点讲解
4. 在关键概念后标注 📌 参考来源
5. 直接输出Markdown内容，不要写开场白，直接从正文第一行开始。
{KB_ONLY_RULE}"""

        raw = self._call_llm(prompt, temperature=0.5, max_tokens=2500)
        # Strip any LLM preamble/intro
        bad_prefixes = ["好的，作为","好的！","好的,","OK，","好的我","好的 我","作为"]
        for bp in bad_prefixes:
            idx = raw.find(bp)
            if 0 <= idx < 80:
                nl = raw.find("\n", idx)
                if nl > 0: raw = raw[nl+1:].lstrip()
                break
        if not raw.startswith("#"):
            for i, ch in enumerate(raw):
                if ch == '#': raw = raw[i:]; break
        return raw

    def generate_mind_map(self, topic: str, rag_context: str) -> str:
        """AI 用 Markdown 标题写思维导图，交给前端 Markmap 渲染——可折叠交互，零语法错误"""
        prompt = f"""为「{topic}」写一个 Markdown 标题大纲，前端会自动转成可折叠的思维导图。

知识库参考：
{rag_context[:1200]}

格式要求：
- 用 # 到 #### 的层级标题，和写笔记一样
- 3-5 个二级话题，每个下面 2-4 个细节点
- 标题 8 字以内，直接用中文术语
- 不输出代码块（```），不输出 JSON，就纯 Markdown 标题行
{KB_ONLY_RULE}

直接输出 Markdown 标题，像这样：
# 决策树
## 划分准则
### 信息增益
### 增益率
### 基尼指数
## 剪枝
### 预剪枝
### 后剪枝"""

        raw = self._call_llm(prompt, temperature=0.3, max_tokens=800)
        return _mindmap_from_markdown(topic, raw) if raw else _default_mindmap(topic)

    def generate_exercises(self, topic: str, profile: dict, rag_context: str) -> List[dict]:
        """生成练习题 —— 题数按画像水平动态调整"""
        fd = profile.get('knowledge_foundation', {})
        avg = (fd.get('math',0.4) + fd.get('programming',0.4) + fd.get('ml_prerequisites',0.4)) / 3

        # 根据基础水平定题量和题型配比
        if avg < 0.4:
            total_q = 5
            type_mix = "2道单选题 + 1道多选题 + 1道判断题 + 1道简答题"
        elif avg < 0.7:
            total_q = 7
            type_mix = "3道单选题 + 1道多选题 + 1道判断题 + 2道简答题"
        else:
            total_q = 8
            type_mix = "3道单选题 + 2道多选题 + 1道判断题 + 2道简答题"

        weakness_hint = ""
        weak = profile.get('struggling_topics', [])
        if weak:
            weakness_hint = f"学生薄弱点：{', '.join(weak[:3])}。请在相关方向多加1道题。"

        # 难度自适应：按最近答题正确率升降档（学 EduGemma 的滚动准确率思路）
        acc = profile.get('_recent_accuracy')
        diff_hint = ""
        if isinstance(acc, (int, float)):
            if acc < 0.4:
                diff_hint = f"学生最近答题正确率只有{acc:.0%}，本次整体降一档难度：以入门级概念理解题为主，不出进阶题。"
            elif acc > 0.8:
                diff_hint = f"学生最近答题正确率高达{acc:.0%}，本次整体升一档难度：多出中等和进阶的综合应用题。"

        # 错因针对性：学生常犯哪类错就往哪个方向出题
        ep = profile.get('error_patterns') or {}
        ep_hint = ""
        if isinstance(ep, dict) and ep:
            top = max(ep, key=ep.get)
            tips = {"概念混淆": "多出概念辨析型选择题（相近概念做干扰项）",
                    "计算失误": "多出需要动手推算的计算题",
                    "审题不清": "题干里适当设置干扰信息考查审题",
                    "知识空白": "从基础定义和公式考起"}
            if tips.get(top):
                ep_hint = f"学生的主要错因是「{top}」，{tips[top]}。"

        prompt = f"""请基于知识库内容，出{total_q}道关于「{topic}」的练习题。题型配比：{type_mix}。{weakness_hint}{diff_hint}{ep_hint}

【知识库内容】
{rag_context[:2500]}

【学生水平】基础评分{avg:.0%}（0=零基础，1=很强）
【生成策略】{profile.get('_emphasis', '概念题和实战题各半。')}

要求：
- 选择题必须有4个具体选项（不能用\"选项A\"这种占位符）
- 每题都要有正确答案(options之外的answer字段)和详细解析
- 难度分布要根据生成策略调整，薄弱点多出概念理解题，已掌握部分多出实战应用题
- 题干直接问知识本身，禁止出现"根据知识库""根据教材""根据上述内容"这类字样

返回JSON数组：
[
    {{
        "type": "单选题/多选题/判断题/简答题",
        "question": "题目内容",
        "options": ["具体的选项内容A", "具体的选项内容B", "具体的选项内容C", "具体的选项内容D"],
        "answer": "正确选项的完整文字",
        "explanation": "详细解析",
        "difficulty": "入门/中等/进阶",
        "knowledge_point": "考查的知识点"
    }}
]

判断题options填[\"对\",\"错\"]，answer填\"对\"或\"错\"。简答题不填options。
{KB_ONLY_RULE}
只输出纯JSON数组。"""

        raw = self._call_llm_json(prompt, temperature=0.3, max_tokens=3000, fallback=[])
        if not raw or not isinstance(raw, list) or len(raw) == 0:
            # 兜底：基于知识库内容生成几道基础题
            return [
                {"type": "单选题", "question": f"{topic}属于机器学习的哪个分支？", "options": ["监督学习", "无监督学习", "强化学习", "以上都有可能"], "answer": "以上都有可能", "explanation": f"请查阅{topic}章节的讲义了解详情", "difficulty": "入门", "knowledge_point": topic},
                {"type": "判断题", "question": f"{topic}是机器学习领域的核心内容", "options": ["对", "错"], "answer": "对", "explanation": f"{topic}在机器学习中占有重要地位，请参考讲义深入学习", "difficulty": "入门", "knowledge_point": topic},
                {"type": "简答题", "question": f"请简述{topic}的核心思想", "answer": f"请参考{topic}章节的讲义内容", "explanation": "简答题请用自己的话总结，再对照讲义检查", "difficulty": "中等", "knowledge_point": topic},
            ]
        # 双保险：LLM没听话的话，把题干里的"根据知识库"这类前缀直接删掉
        import re as _re
        for q in raw:
            if isinstance(q, dict) and q.get("question"):
                q["question"] = _re.sub(r'^(根据|依据|基于)(知识库|教材|上述|以上)[^，,、]{0,6}[，,、]?\s*', '', str(q["question"])).strip()
        return raw

    def generate_reading_materials(self, topic: str, rag_context: str) -> str:
        """从知识库提取阅读材料和参考文献"""
        refs = extract_reading_materials(topic)
        if refs and len(refs) > 20:
            return refs
        prompt = f"""请从以下知识库内容中提取与「{topic}」相关的阅读材料和参考文献。
{rag_context[:3000]}
只输出原文中存在的阅读材料和参考文献部分。如没有输出「暂无」。"""
        raw = self._call_llm(prompt, temperature=0.2, max_tokens=1000)
        return raw if len(raw) > 20 else "暂无相关阅读材料"

    def generate_extended_reading(self, topic: str, rag_context: str) -> List[str]:
        """拓展阅读 → 知识库「休息一会儿」小故事"""
        stories = extract_stories()
        if stories and len(stories) > 20:
            parts = [p.strip() for p in stories.split("---") if p.strip() and len(p.strip()) > 15]
            return parts[:3] if parts else []
        # 兜底：LLM 生成基于KB的故事推荐
        prompt = f"""请根据知识库内容推荐3篇拓展阅读。每行一个：序号. 标题 - 理由。
{rag_context[:1500]}
{KB_ONLY_RULE}"""
        raw = self._call_llm(prompt, temperature=0.4, max_tokens=400)
        lines = [l.strip() for l in raw.split("\n") if l.strip() and len(l.strip()) > 8]
        return lines[:3] if lines else [f"《机器学习》周志华 - {topic}相关章节"]

    def generate_code_example(self, topic: str, profile: dict, rag_context: str) -> str:
        """生成Python代码实操案例 —— 根据编程水平个性化"""
        prog_level = (profile.get('knowledge_foundation') or {}).get('programming', 0.5)
        style = profile.get('cognitive_style', '综合型')

        comment_style = "注释要非常详细，每行都解释，像教小学生一样" if prog_level < 0.5 else "注释简洁专业，只解释关键步骤"

        prompt = f"""请写一段关于「{topic}」的完整Python实操代码。

【知识库参考】{rag_context[:1500]}

【学生编程水平】{prog_level:.0%}（1=专家, 0=新手）
【注释要求】{comment_style}
【生成策略】{profile.get('_emphasis', '完整实战流程。')}

要求：
1. 代码完整可运行，用sklearn等常用库
2. {comment_style}
3. 包含：数据加载 → 模型训练 → 预测 → 评估的完整流程
4. 适当加入matplotlib可视化
5. 代码{'30-50行（精简版，适合新手）' if prog_level < 0.5 else '60-100行（完整版）'}
6. 直接输出Python代码，不用markdown代码块
{KB_ONLY_RULE}"""

        raw = self._call_llm(prompt, temperature=0.4, max_tokens=2000)
        # 清理可能的```python标记
        raw = raw.replace("```python", "").replace("```", "").strip()
        return raw

    def generate_ppt_outline(self, topic: str, rag_context: str) -> str:
        """生成PPT大纲"""
        prompt = f"""请为「{topic}」生成一份教学PPT大纲。

【知识库内容】
{rag_context[:2000]}

要求：
1. 15-20页的详细大纲
2. 每页标注：页码、标题、核心要点（3-5个bullet point）
3. 结构：封面→目录→背景引入→核心概念→方法详解→案例→练习→总结→参考资料
4. 用Markdown格式输出，每页用 ## 标记

直接输出Markdown格式的大纲。{KB_ONLY_RULE}"""

        return self._call_llm(prompt, temperature=0.4, max_tokens=3500)

    def generate_video_script(self, topic: str, profile: dict, rag_context: str) -> str:
        """生成 Manim 动画代码 —— 保证可渲染的简化模板"""
        prompt = f"""请为「{topic}」写一段 Manim 动画代码。要求代码简单、保证能运行。

【知识库内容】{rag_context[:1500]}

必须遵守的规则：
1. 只用 from manim import *，定义 class ExplainScene(Scene):
2. 只用 Text() 不用 Tex/MathTex（避免LaTeX依赖）
3. 只用 Write/FadeIn 两种动画
4. 每个动画后必须 self.wait(1)
5. 总共 4-6 个步骤
6. 不要用 self.play(title.animate.to_edge(...))，用完直接 self.remove
7. 绝对不要用 numpy、matplotlib 或其他库
8. 字体大小选 36-48，颜色用 BLUE/WHITE/YELLOW/GREEN/RED
9. 内容侧重：{profile.get('_emphasis', '概念解释和实例演示')}

输出模板：
```python
from manim import *

class ExplainScene(Scene):
    def construct(self):
        title = Text("{topic}", font_size=48, color=BLUE)
        self.play(Write(title))
        self.wait(1)
        self.remove(title)

        # 步骤1
        step1 = Text("...", font_size=36, color=WHITE)
        self.play(Write(step1))
        self.wait(2)
        self.remove(step1)

        # 更多步骤...

        end = Text("谢谢观看", font_size=40, color=YELLOW)
        self.play(FadeIn(end))
        self.wait(2)
```

只输出代码，不要任何其他文字。{KB_ONLY_RULE}"""

        raw = self._call_llm(prompt, temperature=0.3, max_tokens=2000)
        raw = raw.replace("```python", "").replace("```", "").strip()
        if "from manim" not in raw:
            raw = "from manim import *\n\n" + raw
        if "class ExplainScene" not in raw and "class " not in raw:
            raw += "\n\nclass ExplainScene(Scene):\n    def construct(self):\n        pass\n"
        return raw

    def generate_all_resources(self, topic: str, profile: dict, outline: dict = None) -> dict:
        """生成所有类型的资源"""
        self.log(f"开始为「{topic}」生成资源...")

        # 1. 检索知识库
        rag_context = retrieve_knowledge(topic, k=5)
        self.log(f"知识库检索完成，获取 {len(rag_context)} 字符")

        # 引文溯源：出处由代码从检索结果里拿，不让 LLM 自己写（会编）
        sources = []
        try:
            for c in retrieve_context(topic, k=5):
                s = c.get("source", "")
                if s and s not in sources:
                    sources.append(s)
        except Exception:
            pass

        result = {
            "topic": topic,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "citations": sources,
        }

        # 2. 依次生成各类资源（每种资源独立调用，避免单次失败影响全局）
        resource_types = [
            ("lecture_notes", "讲解文档", lambda: self.generate_lecture_notes(topic, profile, rag_context)),
            ("mind_map", "思维导图", lambda: self.generate_mind_map(topic, rag_context)),
            ("exercises", "练习题", lambda: self.generate_exercises(topic, profile, rag_context)),
            ("extended_reading", "拓展阅读", lambda: self.generate_extended_reading(topic, rag_context)),
            ("code_example", "代码案例", lambda: self.generate_code_example(topic, profile, rag_context)),
            ("ppt_outline", "PPT大纲", lambda: self.generate_ppt_outline(topic, rag_context)),
            ("video_script", "视频脚本", lambda: self.generate_video_script(topic, profile, rag_context)),
        ]

        for key, label, generator in resource_types:
            try:
                self.log(f"正在生成: {label}...")
                result[key] = generator()
                self.log(f"{label} 生成完成")
                time.sleep(1)  # 防止API频率限制
            except Exception as e:
                self.log_error(f"{label}生成失败: {e}")
                result[key] = "" if key in ("lecture_notes", "mind_map", "code_example", "ppt_outline", "video_script") else []
                time.sleep(2)  # 失败后多等一会

        # 讲义末尾附上真实的知识库出处
        if sources and result.get("lecture_notes"):
            result["lecture_notes"] += "\n\n---\n\n📖 **内容依据**（知识库检索）：" + "、".join(sources[:4])

        return result

    def process(self, **kwargs) -> Dict[str, Any]:
        topic = kwargs.get("topic", "")
        profile = kwargs.get("profile", {})
        outline = kwargs.get("outline")

        if not topic:
            # 从画像推断主题
            struggling = profile.get("struggling_topics", [])
            topic = struggling[0] if struggling else profile.get("target_course", "机器学习")

        resources = self.generate_all_resources(topic, profile, outline)
        return {"agent": self.name, "resources": resources, "topic": topic}
