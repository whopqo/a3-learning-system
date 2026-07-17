"""
Agent 有向图引擎 —— 多智能体协同的真正运行时

每个节点 = Agent + 质量门 + 流式输出
边 = pass/fail 两种走向
环 = 质量门不通过回到上游，形成自反馈闭环
"""
import re, time
from typing import Dict, Any, Optional, Generator

class GraphNode:
    """图节点"""
    def __init__(self, name: str, agent: Any,
                 on_pass: str = None, on_fail: str = None):
        self.name = name
        self.agent = agent
        self.on_pass = on_pass
        self.on_fail = on_fail

class AgentGraph:
    """多智能体协同有向图 —— 运行时引擎

    图结构:
        profile ─够→ path ─有阶段→ resource ─KB匹配→ done
          ↑不够        ↑无阶段        ↑不匹配
          └─追问       └─重规划       └─换topic

        evaluate ─掌握→ done ─没掌握→ resource(出题) → profile(更新)
    """

    MAX_LOOPS = 5

    def __init__(self, learning_system):
        self.sys = learning_system
        self.nodes: Dict[str, GraphNode] = {}
        self._build()

    def _build(self):
        self.nodes["profile"] = GraphNode("profile", self.sys.profile_agent,
                                          on_pass="path", on_fail="profile")
        self.nodes["path"] = GraphNode("path", self.sys.path_agent,
                                       on_pass="resource", on_fail="path")
        self.nodes["resource"] = GraphNode("resource", self.sys.resource_agent,
                                           on_pass="done", on_fail="resource")
        self.nodes["tutor"] = GraphNode("tutor", self.sys.tutor_agent,
                                        on_pass="done")
        self.nodes["evaluate"] = GraphNode("evaluate", self.sys.evaluate_agent,
                                           on_pass="done", on_fail="resource")

    # 核心: 沿图行走，流式输出 SSE 事件

    def walk(self, start: str, ctx: dict) -> Generator[dict, None, dict]:
        """从 start 节点出发，走到 done。yield SSE事件，返回最终ctx。

        协同时序:
          1. 执行当前节点 → yield progress + text
          2. 执行质量门 → 通过则前进，不通过则回到上游
          3. 走到 done → 终点
          4. 评估节点特殊: 不通过时反馈到 profile 再回到 resource
        """
        current = start
        visited = {}
        ctx["_graph_path"] = []

        while current and current != "done":
            if visited.get(current, 0) >= self.MAX_LOOPS:
                yield {"type":"text","content":f"\n(系统提示: {current}已重试{self.MAX_LOOPS}次,跳过)\n"}
                break
            visited[current] = visited.get(current, 0) + 1
            ctx["_graph_path"].append(current)

            node = self.nodes.get(current)
            if not node:
                break

            # 执行节点 → 流式输出
            yield from self._run_node(node, ctx)

            # 质量门
            passed, fail_reason = self._check_node(node, ctx)
            if passed:
                current = node.on_pass
            else:
                # 评估节点失败 → 反馈画像+调整路径
                if node.name == "evaluate":
                    ctx["_retry_reason"] = fail_reason
                    yield {"type":"text","content":f"\n掌握度偏低,需要加强练习\n"}
                    self._feedback_eval_to_profile(ctx)
                    current = "resource"  # 回资源节点出针对性题
                # 资源节点失败 → 换个知识点
                elif node.name == "resource":
                    fallback = self._pick_fallback_topic(ctx)
                    if fallback:
                        ctx["_topic"] = fallback
                        yield {"type":"text","content":f"\n改用章节「{fallback}」\n"}
                        current = "resource"
                    else:
                        yield {"type":"text","content":"\n所有章节均已尝试,请手动输入新的知识点\n"}
                        current = "done"
                else:
                    current = node.on_fail

        ctx["_done"] = True
        return ctx

    # 节点执行

    def _run_node(self, node: GraphNode, ctx: dict) -> Generator[dict, None, None]:
        yield {"type":"progress","step":1,"total":2,"label":f"{node.name}工作中…"}

        if node.name == "profile":
            result = self._exec_profile(ctx)
        elif node.name == "path":
            result = self._exec_path(ctx)
        elif node.name == "resource":
            yield from self._exec_resource(ctx)
            return
        elif node.name == "tutor":
            yield from self._exec_tutor(ctx)
            return
        elif node.name == "evaluate":
            yield from self._exec_evaluate(ctx)
            return
        else:
            return

        yield {"type":"progress","step":2,"total":2,"label":f"{node.name}完成"}

    # ── 各节点实际逻辑 ──

    def _exec_profile(self, ctx: dict) -> dict:
        conv = ctx.get("_conversation","")
        profile = ctx.get("profile")
        result = self.sys.profile_agent.process(
            conversation=conv, current_profile=profile,
            round_num=ctx.get("_round",1))
        ctx["profile"] = result.get("profile", profile)
        ctx["_guide_question"] = result.get("guide_question")
        return result

    def _exec_path(self, ctx: dict) -> dict:
        profile = ctx.get("profile") or {}
        result = self.sys.path_agent.process(profile=profile)
        ctx["learning_path"] = result.get("learning_path",{})
        return result

    def _exec_resource(self, ctx: dict) -> Generator[dict, None, None]:
        profile = ctx.get("profile") or {}
        topic = ctx.get("_topic", "机器学习基础")
        sess = ctx.get("_session") or {}

        # 先构建资源生成任务列表 (用于计算总进度)
        from config import RESOURCE_TYPES
        gens = [
            ("lecture_notes","讲解文档", lambda:self.sys.resource_agent.generate_lecture_notes(topic,{},""),True),
            ("mind_map","思维导图", lambda:self.sys.resource_agent.generate_mind_map(topic,""),True),
            ("exercises","练习题", lambda:self.sys.resource_agent.generate_exercises(topic,{},""),True),
            ("reading_materials","阅读材料", lambda:self.sys.resource_agent.generate_reading_materials(topic,""),True),
            ("extended_reading","拓展阅读", lambda:self.sys.resource_agent.generate_extended_reading(topic,""),True),
            ("code_example","代码案例", lambda:self.sys.resource_agent.generate_code_example(topic,{},""),True),
            ("ppt_outline","PPT大纲", lambda:self.sys.resource_agent.generate_ppt_outline(topic,""),True),
            ("video_script","视频脚本", lambda:self.sys.resource_agent.generate_video_script(topic,{},""),True),
        ]
        exercise_only_count = ctx.get("_exercises_only", False)
        task_preview = [(k, l, g) for k, l, g, _ in gens if not exercise_only_count or k == "exercises"]
        total = len(task_preview) + 2  # 检索1 + 生成N + 整理1

        # 检查KB
        from rag.engine import check_topic_relevance, retrieve_knowledge
        yield {"type":"progress","step":1,"total":total,"label":f"检索「{topic}」相关知识"}
        kb_check = check_topic_relevance(topic)
        if not kb_check.get("relevant"):
            clean_topic = re.split(r'[（(]', topic)[0].strip()
            kb3 = check_topic_relevance(clean_topic[:6], threshold=0.30)
            if not kb3.get("relevant"):
                ctx["_kb_failed"] = True
                ctx["_kb_score"] = kb_check.get("score",0)
                yield {"type":"text","content":f"\n「{topic}」暂未在知识库中找到,请尝试其他章节\n"}
                return
        rag_ctx = retrieve_knowledge(topic, k=5)

        # 个性化策略
        fd = (profile.get("knowledge_foundation") or {})
        avg = (fd.get("ml_prerequisites",0.4)+fd.get("programming",0.4)+fd.get("math",0.4))/3
        enriched = dict(profile)
        if avg<0.4:
            enriched["_emphasis"] = "基础概念为主,配生活化类比。先理解是什么再谈为什么。"
        elif avg<0.7:
            enriched["_emphasis"] = "概念和公式平衡,关注算法间联系和对比。"
        else:
            enriched["_emphasis"] = "深入数学推导和算法细节,关注前沿改进。"

        # 语言风格偏好
        lang = profile.get("language_style", "")
        if "严谨" in lang or "学术" in lang:
            enriched["_tone"] = "使用严谨的学术语言,术语准确,数学公式用LaTeX,结构用定义→定理→推论格式。"
        elif "生动" in lang or "比喻" in lang:
            enriched["_tone"] = "用生动的比喻和故事讲解概念。避免大段数学公式,用通俗语言解释。大量使用类比和具体例子。"

        # 注入 topic 和薄弱点信息
        weak = profile.get("struggling_topics",[]) or []
        mastered = profile.get("mastered_topics",[]) or []
        if any(w for w in weak if w in topic or topic in w):
            enriched["_emphasis"] += " 这是学生的薄弱点,放慢节奏。"
        if any(m for m in mastered if m in topic or topic in m):
            enriched["_emphasis"] += " 学生已有基础,加速基础部分。"

        # 替换为带真实数据的生成器（进度计算用占位已完成）
        gens = [
            ("lecture_notes","讲解文档", lambda:self.sys.resource_agent.generate_lecture_notes(topic,enriched,rag_ctx),True),
            ("mind_map","思维导图", lambda:self.sys.resource_agent.generate_mind_map(topic,rag_ctx),True),
            ("exercises","练习题", lambda:self.sys.resource_agent.generate_exercises(topic,enriched,rag_ctx),True),
            ("reading_materials","阅读材料", lambda:self.sys.resource_agent.generate_reading_materials(topic,rag_ctx),True),
            ("extended_reading","拓展阅读", lambda:self.sys.resource_agent.generate_extended_reading(topic,rag_ctx),True),
            ("code_example","代码案例", lambda:self.sys.resource_agent.generate_code_example(topic,enriched,rag_ctx),True),
            ("ppt_outline","PPT大纲", lambda:self.sys.resource_agent.generate_ppt_outline(topic,rag_ctx),True),
            ("video_script","视频脚本", lambda:self.sys.resource_agent.generate_video_script(topic,enriched,rag_ctx),True),
        ]

        exercises_only = ctx.get("_exercises_only", False)
        resources = {"topic":topic,"generated_at":time.strftime("%Y-%m-%d %H:%M:%S")}

        # 过滤要生成的资源
        tasks = [(key, label, gen_fn) for key, label, gen_fn, _ in gens
                 if not exercises_only or key == "exercises"]

        # 并行生成：8个任务一轮跑完。子线程默认不继承contextvar，
        # 要手动复制上下文，不然聊天框选的模型和教学模式在这里会失效
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import contextvars
        idx = 0
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {}
            for key, label, gen_fn in tasks:
                cv = contextvars.copy_context()
                futures[pool.submit(cv.run, gen_fn)] = (key, label)
            for f in as_completed(futures):
                key, label = futures[f]
                idx += 1
                yield {"type":"progress","step":idx+1,"total":total,"label":f"已完成{label}"}
                try:
                    resources[key] = f.result()
                except Exception:
                    resources[key] = f"[生成超时] {label}" if key != "exercises" else []

        yield {"type":"progress","step":total,"total":total,"label":"整理完成"}
        ctx["resources"] = resources
        # 同步到 session：最新一份 + 历史累积（刷新后资源库还能看到之前生成的）
        if sess:
            sess["resources"] = resources
            hist = sess.get("resources_history") or []
            hist.append(resources)
            sess["resources_history"] = hist[-30:]
            sess["phase"] = "learning"

        # 生成个性化描述文本
        desc = self._build_resource_description(topic, profile, resources, ctx, exercises_only)
        ctx["_desc"] = desc
        yield {"type":"text","content":desc}

    def _exec_tutor(self, ctx: dict) -> Generator[dict, None, None]:
        question = ctx.get("_question","")
        profile = ctx.get("profile") or {}

        yield {"type":"progress","step":1,"total":3,"label":"分析问题中…"}
        analysis = self.sys.tutor_agent.analyze_question(question, profile)

        yield {"type":"progress","step":2,"total":3,"label":"生成解答…"}
        answer = self.sys.tutor_agent.answer_with_rag(question, analysis, profile)

        if "知识库中暂时没有" not in answer:
            yield {"type":"progress","step":3,"total":3,"label":"生成图解…"}
            diagram = self.sys.tutor_agent.generate_diagram(analysis.get("knowledge_point",question))
            if diagram and len(diagram)>10:
                answer += f"\n\n### 图解说明\n\n```mermaid\n{diagram}\n```"
            else:
                # 图解生成失败要留下线索，不然排查没门
                from utils import logger
                logger.warn(f"图解生成为空: {analysis.get('knowledge_point', question)[:30]}", "tutor")

        ctx["_tutor_answer"] = answer
        yield {"type":"text","content":answer}

    def _exec_evaluate(self, ctx: dict) -> Generator[dict, None, None]:
        exs = (ctx.get("resources") or {}).get("exercises",[])
        if not exs:
            yield {"type":"text","content":"还没有练习题,先生成一些吧。"}
            return

        ans = ctx.get("_answers","")
        profile = ctx.get("profile") or {}
        yield {"type":"progress","step":1,"total":2,"label":"正在批改…"}
        result = self.sys.evaluate_agent.process(
            exercises=exs, student_answers=ans, profile=profile,
            learning_history=ctx.get("_eval_history",[]),
            error_records=ctx.get("_error_records",[]))

        evaluation = result.get("evaluation",{})
        ctx["_evaluation"] = evaluation
        ctx["_mastery_updates"] = result.get("mastery_updates", {})

        score = evaluation.get("total_score",0)
        text = f"## 评估报告\n\n总分: {score:.0f}/100\n"
        if evaluation.get("suggestion"):
            text += f"\n{evaluation['suggestion']}"
        yield {"type":"text","content":text}

    # 质量门

    def _check_node(self, node: GraphNode, ctx: dict) -> tuple:
        if node.name == "profile":
            asked = (ctx.get("profile") or {}).get("_asked_dims",[])
            if len(asked) >= 7:
                return (True, "")
            return(False, f"画像仅{len(asked)}维")

        if node.name == "path":
            phases = (ctx.get("learning_path") or {}).get("phases",[])
            return (len(phases)>0, "路径无阶段" if not phases else "")

        if node.name == "resource":
            if ctx.get("_kb_failed"):
                return (False, f"「{ctx.get('_topic','')}」不在知识库中")
            return (True, "")

        if node.name == "evaluate":
            score = (ctx.get("_evaluation") or {}).get("total_score",0)
            return (score>=50, f"掌握度{score}%")

        return (True, "")

    # 辅助

    def _pick_fallback_topic(self, ctx: dict) -> str | None:
        """从学习路径找下一个未尝试的章节名"""
        tried = set(ctx.get("_tried_topics", []) or [])
        tried.add(ctx.get("_topic",""))
        ctx["_tried_topics"] = list(tried)

        lp = ctx.get("learning_path") or {}
        for p in (lp.get("phases") or []):
            for ch in (p.get("chapters") or []):
                clean = ch.split("（")[0].strip() if "（" in ch else ch
                if clean not in tried:
                    return clean
        # 全部试过了→返回None中止循环
        return None

    def _feedback_eval_to_profile(self, ctx: dict):
        """评估→画像 反馈闭环: 薄弱点 + 已掌握 + 基础评分"""
        evaluation = ctx.get("_evaluation") or {}
        profile = ctx.get("profile") or {}
        mastery = ctx.get("_mastery_updates") or {}

        # 薄弱点更新
        if evaluation.get("weaknesses"):
            existing = list(profile.get("struggling_topics",[]) or [])
            for w in evaluation["weaknesses"]:
                if w[:30] not in existing:
                    existing.append(w[:30])
            profile["struggling_topics"] = existing

        # 掌握度更新—做对的题目标记已掌握
        for kp, val in mastery.items():
            if val >= 0.7:
                mastered = list(profile.get("mastered_topics",[]) or [])
                if kp not in mastered:
                    mastered.append(kp)
                profile["mastered_topics"] = mastered

        profile["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")

    def _build_resource_description(self, topic: str, profile: dict,
                                     resources: dict, ctx: dict,
                                     exercises_only: bool) -> str:
        """生成个性化资源描述"""
        fd = (profile or {}).get("knowledge_foundation",{}) or {}
        avg = (fd.get("ml_prerequisites",0.4)+fd.get("programming",0.4)+fd.get("math",0.4))/3
        goal = profile.get("short_term_goal","") or ""
        style = profile.get("cognitive_style","") or ""
        weak = profile.get("struggling_topics",[]) or []

        parts = [f"## 「{topic}」学习资源包\n"]
        if avg<0.35: parts.append(f"> 你的ML基础偏弱,学习节奏可以放慢一些,先理解概念再动手。")
        elif avg<0.55: parts.append(f"> 你有一些基础但还不牢固,建议边学边练。")
        elif avg<0.75: parts.append(f"> 基础不错,可以适当加快节奏,多关注算法原理和数学推导。")
        else: parts.append(f"> 基础很强,建议直接深入算法细节和实战项目。")
        if "考研" in goal: parts.append(f"> 针对考研需求,注意理解算法数学原理和推导过程。")
        elif "就业" in goal or "工作" in goal: parts.append(f"> 面向就业,建议多动手实践。")
        elif "考试" in goal: parts.append(f"> 针对考试,重点掌握核心概念和经典题型。")
        if style=="动手型": parts.append(f"> 动手型学习者建议先跑代码案例,再回来看讲义。")
        elif "视觉" in style: parts.append(f"> 可以多看看思维导图,视觉化理解知识结构。")
        if weak: parts.append(f"> 薄弱点: {'、'.join(weak[:4])},学完可回头加强。")
        parts.append("")

        lp = ctx.get("learning_path") or {}
        for p in (lp.get("phases") or []):
            for ch in (p.get("chapters") or []):
                if topic in ch or ch in topic:
                    parts.append(f"所属阶段: 阶段{p.get('phase','?')} {p.get('title','')}")
                    break

        if exercises_only:
            parts.append(f"练习题 {len(resources.get('exercises',[]))}道")
        else:
            if resources.get("lecture_notes"): parts.append("讲解文档 已生成")
            if resources.get("mind_map"): parts.append("思维导图 已生成")
            if resources.get("exercises"): parts.append(f"练习题 {len(resources.get('exercises',[]))}道")
            if resources.get("reading_materials"): parts.append("阅读材料 已生成")
            if resources.get("extended_reading"): parts.append(f"拓展阅读 {len(resources.get('extended_reading',[]))}篇")
            if resources.get("code_example"): parts.append("代码案例 已生成")
            if resources.get("ppt_outline"): parts.append("PPT大纲 已生成")
            if resources.get("video_script"): parts.append("视频脚本 已生成")
        parts.append("\n在资源库页面查看 | 点击路径标签页查看完整学习计划")
        return "\n".join(parts)
