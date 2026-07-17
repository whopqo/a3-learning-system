"""
编排处理器 —— 消息收发 + SSE流式 + 会话管理
调度委托给 agents.graph.AgentGraph (有向图多Agent协同)
"""
import json, re, time, traceback, os
from typing import Dict, Any, Optional, Generator

from agents.supervisor import SupervisorAgent
from agents.profile_agent import ProfileAgent
from agents.resource_agent import ResourceAgent
from agents.path_agent import PathAgent
from agents.tutor_agent import TutorAgent
from agents.evaluate_agent import EvaluateAgent
from agents.memory_agent import MemoryAgent
from agents.graph import AgentGraph
from utils.content_safety import check_content_safety
from rag.engine import message_in_kb_scope

class LearningSystem:
    """多智能体学习系统 —— handler 只管消息收发,调度交给 AgentGraph"""

    def __init__(self):
        self.supervisor = SupervisorAgent()
        self.profile_agent = ProfileAgent()
        self.resource_agent = ResourceAgent()
        self.path_agent = PathAgent()
        self.tutor_agent = TutorAgent()
        self.evaluate_agent = EvaluateAgent()
        self.memory_agent = MemoryAgent()
        self.sessions: Dict[str, dict] = {}
        self.graph = AgentGraph(self)
        self._session_file = os.path.join(os.path.dirname(__file__), "db", "sessions.json")
        self._load_sessions()

    def _load_sessions(self):
        """从磁盘恢复会话（防重启丢数据）"""
        try:
            if os.path.exists(self._session_file):
                with open(self._session_file, "r", encoding="utf-8") as f:
                    self.sessions = json.load(f)
        except Exception:
            pass

    def _save_sessions(self):
        """会话落地到JSON文件"""
        try:
            os.makedirs(os.path.dirname(self._session_file), exist_ok=True)
            # 只清理确实超过2小时不活跃的会话；没标记的按"刚活跃"处理，
            # 不然刚创建还没走到打标记那步的会话会被误删。
            # 注意：原地删除，不能整个换字典——正在处理中的会话会变孤儿
            cutoff = time.time() - 7200
            stale = [k for k, v in self.sessions.items()
                     if v.get("_last_active", time.time()) < cutoff]
            for k in stale:
                self.sessions.pop(k, None)
            with open(self._session_file, "w", encoding="utf-8") as f:
                json.dump(self.sessions, f, ensure_ascii=False, indent=2, default=str)
        except Exception:
            pass

    def ensure_session(self, session_id: str) -> dict:
        if session_id not in self.sessions:
            self.sessions[session_id] = {
                "phase": "profile_building", "profile": None, "outline": None,
                "resources": None, "learning_path": None, "evaluation_history": [],
                "error_records": [], "conversation_round": 0,
                "conversation_history": [], "agent_logs": [], "progress": {},
            }
        return self.sessions[session_id]

    # ── LLM 分类 prompt ──
    _CLASSIFY_PROMPT = """分析消息返回JSON。

{context}
用户:「{msg}」

{{"category":"ml/casual/flow/off_topic","intent":"resource_generation/path_planning/tutoring/evaluation/profile_building/general_chat","topic":"知识点名或空","resource_type":"full/exercises_only","should_reject":true/false}}

关键规则:
- resource_generation: 生成资料/出题/获取资源("生成""出题""资料""学习资料""给我""讲义""PPT"都算) 注意:"帮我生成学习资料""有资料吗"→resource_generation!
- evaluation: 批改已做的题("批改""打分""对了吗") 出题≠评估!
- off_topic: 与ML完全无关才拒绝(天气/娱乐/其他学科)
- ml/casual/flow 基本都是放行的
只输出JSON。"""

    @staticmethod
    def _is_gibberish(msg: str) -> bool:
        if not msg or not isinstance(msg, str): return True
        m = msg.strip()
        if not m: return True
        if len(m) == 1 and any('一' <= c <= '鿿' for c in m): return False
        clean = re.sub(r'[\s\W\d]', '', m, flags=re.UNICODE)
        if len(clean) <= 1: return True
        if len(set(m)) == 1 and len(m) > 3: return True
        alpha = re.sub(r'[^a-zA-Z]', '', m)
        if len(alpha) > 6:
            if sum(1 for c in alpha.lower() if c in 'aeiou') == 0: return True
            for row in ["qwertyuiop","asdfghjkl","zxcvbnm"]:
                for i in range(len(row)-4):
                    if row[i:i+5].lower() in alpha.lower(): return True
        # 连续4个以上英文辅音 → 乱码。只对纯英文消息启用，
        # 中文消息里夹的"Python"这种正常单词不能误伤（y不算辅音）
        if not any('一' <= c <= '鿿' for c in m):
            # 中英文混杂+大小写交替 → 纯英文乱码（"aBcDeFg"）
            if len(alpha) > 3 and (re.search(r'[A-Z][a-z]+[A-Z]', m) or re.search(r'[a-z]{2,}[A-Z]{2,}', m)):
                return True
            # 连续4个以上英文辅音
            if re.search(r'[bcdfghjklmnpqrstvwxz]{4,}', m, re.IGNORECASE):
                return True
        return False

    def _classify(self, msg: str, session: dict) -> dict:
        m = msg.strip()
        if len(m) <= 2:
            return {"category":"casual","intent":"general_chat","topic":"","should_reject":False}
        if not message_in_kb_scope(m, threshold=0.12):
            return {"category":"off_topic","intent":"general_chat","topic":"","should_reject":True}

        context = ""
        if session:
            conv = session.get("conversation_history", [])[-4:]
            if conv:
                lines = [f"{'用户' if x['role']=='user' else '系统'}: {x['content'][:120]}" for x in conv]
                context = "最近对话:\n" + "\n".join(lines)

        prompt = self._CLASSIFY_PROMPT.format(context=context, msg=m[:300])
        result = self.supervisor._call_llm_json(prompt, temperature=0.1, max_tokens=300,
            fallback={"category":"ml","intent":"general_chat","topic":"","should_reject":False,"resource_type":"full"})
        return result or {"category":"ml","intent":"general_chat","topic":"","should_reject":False}

    def _extract_topic(self, session: dict) -> str:
        conv = session.get("conversation_history", [])[-8:]
        if not conv: return ""
        lines = [f"{'用户' if x['role']=='user' else '系统'}: {x['content'][:150]}" for x in conv]
        prompt = f"从对话提取最近讨论的ML知识点。\n{chr(10).join(lines)}\n返回JSON: {{\"topic\":\"知识点名或空\"}}"
        r = self.supervisor._call_llm_json(prompt, temperature=0.1, max_tokens=100, fallback={"topic":""})
        return (r or {}).get("topic","").strip()

    @staticmethod
    def _flat_steps(lp: dict) -> list:
        if not lp: return []
        phases = lp.get("phases", [])
        if phases:
            flat = []
            for p in phases:
                for ch in (p.get("chapters") or []):
                    flat.append({"name":ch, "difficulty":p.get("difficulty","中等"),
                                 "step":len(flat)+1, "estimated_hours":2,
                                 "reason":f"阶段{p.get('phase','?')}: {p.get('title','')}"})
            return flat
        return lp.get("steps") or []

    def _pick_first_chapter(self, lp: dict, profile: dict) -> str:
        phases = lp.get("phases", [])
        for p in sorted(phases, key=lambda x: x.get("phase",99)):
            chs = p.get("chapters", [])
            for ch in chs:
                # 去掉LLM附带的额外信息如"绪论（入门·约1.5h）"→"绪论"
                clean = re.sub(r'[（(][^)）]*[)）]', '', ch).strip()
                if clean: return clean
        return "机器学习基础"

    # 主入口

    def process_message_stream(self, user_message: str,
                               session_id: str = "default") -> Generator[dict, None, None]:
        session = self.ensure_session(session_id)
        session["conversation_round"] += 1
        round_num = session["conversation_round"]

        # 安全检查
        safe, reason = check_content_safety(user_message)
        if not safe:
            yield {"type":"done","result":{"type":"error","content":f"内容安全检查未通过: {reason}"}}
            return

        session["conversation_history"].append({
            "role":"user","content":user_message,"time":time.strftime("%H:%M:%S")})

        # 乱码
        if self._is_gibberish(user_message):
            tip = "请输入有效的内容，或者聊聊你想学的机器学习知识点～"
            for ch in tip: yield {"type":"text","content":ch}; time.sleep(0.01)
            yield {"type":"done","result":{"type":"chat","content":tip}}
            return

        # 不管走哪条路，先给个即时反馈——分类那次LLM调用是静默的，不发这个用户就干瞪"思考中"
        yield {"type":"progress","step":1,"total":2,"label":"正在理解你的消息…"}

        # 分类。画像期的普通回答（不带指令词）不用劳烦LLM分类，省一次调用提速
        _cmd_words = ("帮我", "生成", "出题", "出几道", "讲讲", "讲解", "规划",
                      "路径", "资源", "是什么", "为什么", "批改", "评估", "做题", "练习题")
        if (session["phase"] == "profile_building"
                and not (session.get("profile") or {}).get("_all_asked")
                and not any(w in user_message for w in _cmd_words)):
            classification = {"category": "ml", "intent": "profile_building",
                              "topic": "", "should_reject": False}
        else:
            classification = self._classify(user_message, session)
        intent = classification.get("intent","general_chat")
        in_profile = session["phase"] == "profile_building"

        # 非画像阶段 → 非ML拒绝
        if not in_profile and classification.get("should_reject"):
            off = "我的知识库目前只覆盖机器学习课程内容,暂时没法回答这个问题。\n\n试试问我某个ML知识点,或者让我出几道题巩固一下。"
            for ch in off: yield {"type":"text","content":ch}; time.sleep(0.008)
            yield {"type":"done","result":{"type":"chat","content":off}}
            return

        result = {"type":"chat","content":"","metadata":{}}

        try:
            # ── 快捷指令："先规划路径再生成资源"（画像就绪才接，没建完落到画像分支） ──
            _combo_ready = ("路径" in user_message and "资源" in user_message
                            and session.get("phase") in ("learning", "profile_building")
                            and (not in_profile or (session.get("profile") or {}).get("_all_asked")))
            if _combo_ready:
                text = "好的,先规划学习路径再生成资源…"
                for ch in text: yield {"type":"text","content":ch}; time.sleep(0.01)
                # Step 1: 路径
                ctx = {"profile": session.get("profile") or {}}
                yield from self.graph.walk("path", ctx)
                session["learning_path"] = ctx.get("learning_path",{})
                # Step 2: 取第一个章节
                first = self._pick_first_chapter(ctx.get("learning_path",{}), session.get("profile") or {})
                # Step 3: 资源
                res_ctx = {"profile": session.get("profile") or {},
                           "_topic": first, "_session": session,
                           "learning_path": ctx.get("learning_path")}
                yield from self.graph.walk("resource", res_ctx)
                result["type"] = "resources"
                result["content"] = "路径+资源已生成"
                result["metadata"] = {"learning_path": session["learning_path"]}
                yield {"type":"done","result":result,"metadata":result.get("metadata",{})}
                return

            # ── 画像阶段 ──
            elif session["phase"] == "profile_building":
                profile_ok = self.profile_agent.is_sufficient(session.get("profile") or {})
                if intent in ("resource_generation","tutoring","path_planning","evaluation") and profile_ok:
                    # 画像已完成 → 处理明确意图，阶段顺势翻到学习期
                    session["phase"] = "learning"
                    yield from self._dispatch_intent(intent, user_message, session, classification, result)
                elif intent in ("resource_generation","tutoring","path_planning","evaluation"):
                    asked = (session.get("profile") or {}).get("_asked_dims",[])
                    if len(user_message) >= 25 or not asked:
                        # 长句大概率是自我介绍顺带提要求，里面全是画像信息不能扔；
                        # 一个维度还没收集时也直接开始画像引导（"先回答当前问题"会没头没脑）
                        yield from self._profile_step(session, round_num, result)
                    else:
                        # 短指令 → 提示而非当画像回答
                        text = f"画像还没建完（已收集{len(asked)}/8个维度），再聊几句就帮你生成～先回答当前问题吧"
                        for ch in text: yield {"type":"text","content":ch}; time.sleep(0.01)
                        result["content"] = text
                else:
                    # 画像未完成 → 当成画像回答继续追问
                    yield from self._profile_step(session, round_num, result)

            # ── 学习阶段 ──
            else:
                yield from self._dispatch_intent(intent, user_message, session, classification, result)

        except Exception as e:
            traceback.print_exc()
            err_text = f"抱歉,出了点问题: {str(e)[:100]}\n请再试一次。"
            for ch in err_text: yield {"type":"text","content":ch}; time.sleep(0.01)
            result = {"type":"chat","content":err_text}

        session["conversation_history"].append({
            "role":"assistant","content":result.get("content","")[:1500],
            "time":time.strftime("%H:%M:%S")})
        session["_last_active"] = int(time.time())
        session["progress"] = {"steps":[],"current":0,"label":""}
        try: self._save_sessions()
        except: pass

        if not session.pop("_skip_routing", None):
            yield {"type":"done","result":result,"metadata":result.get("metadata",{})}

    # 意图分发 → 委托给 AgentGraph

    def _dispatch_intent(self, intent: str, msg: str, session: dict,
                         classification: dict, result: dict):
        profile = session.get("profile") or {}

        if intent == "resource_generation":
            yield from self._handle_resource(msg, session, result, classification)

        elif intent == "path_planning":
            yield from self._handle_path(session, result)

        elif intent == "tutoring":
            # 被动画像更新：记下问过的知识点，同一个概念反复问说明没懂（零额外LLM调用）
            topic = (classification.get("topic") or "").strip()
            if topic and profile:
                asked = profile.get("_asked_topics") or {}
                asked[topic] = int(asked.get(topic, 0)) + 1
                profile["_asked_topics"] = asked
                if asked[topic] >= 2 and topic not in (profile.get("mastered_topics") or []):
                    if topic not in (profile.get("struggling_topics") or []):
                        profile.setdefault("struggling_topics", []).append(topic)
                    # 掌握度也压一下，让每日一练和出题都能感知
                    from utils import mastery as mastery_mod
                    mastery_mod.update_kp(profile, topic, 0.3)
                session["profile"] = profile
            yield from self._handle_tutor(msg, session, result)

        elif intent == "evaluation":
            yield from self._handle_evaluate(msg, session, result)

        elif intent == "profile_building":
            yield from self._profile_step(session, session["conversation_round"], result)

        else:  # general_chat
            cat = classification.get("category","ml")
            yield from self._handle_chat(msg, session, result, cat)

    # 画像构建

    def _profile_step(self, session: dict, round_num: int, result: dict):
        # 提取要调一次LLM，先给个即时反馈别让用户干等"思考中"
        yield {"type":"progress","step":1,"total":2,"label":"正在分析你的回答…"}
        conv_text = "\n".join([
            f"{'学生' if m['role']=='user' else '系统'}: {m['content'][:300]}"
            for m in session["conversation_history"]
        ])
        profile_result = self.profile_agent.process(
            conversation=conv_text, current_profile=session.get("profile"),
            round_num=round_num)
        session["profile"] = profile_result["profile"]
        guide = profile_result.get("guide_question")
        profile_new = session["profile"]

        # 7维以上直接放行（快速开始一句话就能集齐）；不够的至少聊够6轮防止过早结束
        asked_cnt = len((profile_new or {}).get("_asked_dims", []))
        if guide is None and self.profile_agent.is_sufficient(profile_new) and (round_num >= 6 or asked_cnt >= 7):
            # 画像完成 → 图: path → resource
            session["phase"] = "learning"
            session["_profile_done_shown"] = True

            yield {"type":"progress","step":1,"total":3,"label":"画像收集完毕，开始规划路径…"}
            ctx = {"profile": profile_new}
            yield from self.graph.walk("path", ctx)
            yield {"type":"progress","step":2,"total":3,"label":"路径规划完成，正在生成学习资料…"}

            lp = ctx.get("learning_path", {})
            session["learning_path"] = lp
            phases = lp.get("phases", [])
            first = self._pick_first_chapter(lp, profile_new)

            text = f"对你了解得差不多了!\n\n根据你的画像定制了个性化学习路径,共 **{len(phases)} 个阶段**:\n\n"
            for p in phases[:5]:
                e = {"入门":"[入门]","中等":"[中等]","进阶":"[进阶]"}.get(p.get("difficulty","中等"),"")
                chs = p.get("chapters",[])
                text += f"{e} 阶段{p.get('phase','?')}: {p.get('title','')} ({p.get('duration','')})\n"
                if chs: text += f"   涵盖: {'、'.join(chs[:3])}\n"
            text += f"\n正在为你生成「{first}」的学习资料…"
            for ch in text: yield {"type":"text","content":ch}; time.sleep(0.01)

            res_ctx = {"profile": profile_new, "_topic": first, "_session": session, "learning_path": lp}
            yield from self.graph.walk("resource", res_ctx)
            text += "\n\n---\n学习资料已生成。点击上方标签页查看完整信息：\n「画像」查看你的学习特征 | 「路径」查看阶段式学习计划 | 「资源库」查看全部8种学习资料 | 「知识库」浏览课程教材 | 「记录」追踪练习成绩"
            for ch in text: yield {"type":"text","content":ch}; time.sleep(0.01)
            result["type"] = "profile_ready"
            result["content"] = text
            result["metadata"] = {"profile":profile_new,"learning_path":lp,"resources":res_ctx.get("resources")}
            return  # 不设_skip_routing，让外层正常yield done
        elif guide:
            asked = (session.get("profile") or {}).get("_asked_dims",[])
            ack = self.profile_agent.get_ack_for_dim(asked[-1]) if asked else ""
            if ack:
                ack = ack + "！"  # 和后面的问题隔开，别连成一句
            progress = f"\n（画像进度 {len(asked)}/8）"
            if ack:
                for ch in ack: yield {"type":"text","content":ch}; time.sleep(0.01)
            for ch in guide: yield {"type":"text","content":ch}; time.sleep(0.015)
            for ch in progress: yield {"type":"text","content":ch}; time.sleep(0.008)
            result["content"] = (ack or "") + guide + progress
            result["metadata"] = {"profile":session["profile"]}
        elif round_num >= 9 and not session.get("_profile_done_shown"):
            session["phase"] = "learning"
            session["_profile_done_shown"] = True
            ctx = {"profile":profile_new}
            yield from self.graph.walk("path", ctx)
            session["learning_path"] = ctx.get("learning_path",{})
            first = self._pick_first_chapter(ctx.get("learning_path",{}), profile_new)
            text = f"聊了这么多,该开始学习了!\n\n正在为你生成「{first}」的学习资料…"
            for ch in text: yield {"type":"text","content":ch}; time.sleep(0.015)
            res_ctx = {"profile":profile_new,"_topic":first,"_session":session,"learning_path":ctx.get("learning_path")}
            yield from self.graph.walk("resource", res_ctx)
            result["content"] = text
            result["metadata"] = {"profile":profile_new,"learning_path":ctx.get("learning_path")}
            return
        else:
            fb = "咱们继续聊聊你的学习情况～"
            for ch in fb: yield {"type":"text","content":ch}; time.sleep(0.01)
            result["content"] = fb

    # 资源生成 → 委托给 AgentGraph

    def _handle_resource(self, msg: str, session: dict, result: dict, classification: dict = None):
        profile = session.get("profile") or {}
        if classification is None:
            classification = {}
        topic = self._clean_topic(msg, session, classification)
        exercises_only = classification.get("resource_type") == "exercises_only"

        ctx = {
            "profile": profile,
            "_topic": topic,
            "_session": session,
            "_exercises_only": exercises_only,
            "learning_path": session.get("learning_path"),
        }
        yield from self.graph.walk("resource", ctx)
        result["type"] = "resources"
        result["content"] = ctx.get("_desc","")
        result["metadata"] = {"resources": ctx.get("resources",{}), "topic": topic}
        return  # 不设_skip_routing，让外层正常yield done

    def _clean_topic(self, msg: str, session: dict, classification: dict = None) -> str:
        topic = msg.strip()
        for p in ["帮我生成","帮我写","给我生成","请生成","生成","我想要","给我","讲讲","我想学","我想了解","学习资料","资源","资料","关于","从 "]:
            if topic.startswith(p) and len(topic)-len(p)>=1: topic=topic[len(p):].strip(); break
        for s in ["的学习资料","的资料","的学习资源","的资源","学习资料","学习资源","资料","资源","的学习","学习","的练习题","的题","练习题"]:
            if topic.endswith(s) and len(topic)-len(s)>=2: topic=topic[:-len(s)].strip(); break
        # 优先用分类结果里的 topic（已在分类LLM调用中提取）
        class_topic = (classification or {}).get("topic","").strip()
        if class_topic and len(class_topic) >= 2: topic = class_topic
        elif (not topic or len(topic)<2):
            # 兜底：单独调LLM提取
            llm_t = self._extract_topic(session)
            if llm_t and len(llm_t)>=2: topic = llm_t
        if not topic or len(topic)<2:
            flat = self._flat_steps(session.get("learning_path",{}))
            topic = flat[0]["name"] if flat else "机器学习基础"
        return topic

    # 路径规划

    def _handle_path(self, session: dict, result: dict):
        ctx = {"profile": session.get("profile") or {}}
        yield from self.graph.walk("path", ctx)
        session["learning_path"] = ctx.get("learning_path",{})
        result["type"] = "learning_path"
        result["content"] = "路径已规划"
        result["metadata"] = {"learning_path": session["learning_path"]}
        return

    # 辅导答疑 → 委托给 AgentGraph

    def _handle_tutor(self, msg: str, session: dict, result: dict):
        ctx = {
            "_question": msg,
            "profile": session.get("profile") or {},
        }
        yield from self.graph.walk("tutor", ctx)
        result["type"] = "tutoring"
        result["content"] = ctx.get("_tutor_answer","")

    # 学习评估 → 委托给 AgentGraph (含反馈闭环)

    def _handle_evaluate(self, msg: str, session: dict, result: dict):
        exs = (session.get("resources") or {}).get("exercises", [])
        if not exs:
            text = "还没有练习题可以评估哦。先生成一些学习资源吧～"
            for ch in text: yield {"type":"text","content":ch}; time.sleep(0.01)
            result["content"] = text
            return

        if session.get("profile") is None:
            session["profile"] = {}
        ctx = {
            "resources": session.get("resources"),
            "_answers": msg,
            "profile": session["profile"],
            "_eval_history": session.get("evaluation_history",[]),
            "_error_records": session.get("error_records",[]),
            "learning_path": session.get("learning_path"),
            "_session": session,
        }
        yield from self.graph.walk("evaluate", ctx)

        # 反馈闭环已在 graph._feedback_eval_to_profile 中处理
        evaluation = ctx.get("_evaluation",{})
        session.setdefault("evaluation_history",[]).append(evaluation)

        text = f"## 评估报告\n\n总分: {evaluation.get('total_score',0):.0f}/100\n"
        if evaluation.get("suggestion"):
            text += f"\n{evaluation['suggestion']}"
        for ch in text: yield {"type":"text","content":ch}; time.sleep(0.01)
        result["type"] = "evaluate"
        result["content"] = text

    # 闲聊

    def _handle_chat(self, msg: str, session: dict, result: dict, cat: str):
        conv_text = "\n".join([
            f"{'学生' if m['role']=='user' else '系统'}: {m['content'][:150]}"
            for m in session["conversation_history"][-4:]
        ])
        if cat == "casual":
            text = self.supervisor._call_llm(
                f"对话:\n{conv_text}\n\n你是学习助手。学生发了日常寒暄。请自然回应(1句话),然后温和引导回学习。",
                temperature=0.7, max_tokens=120)
        elif cat == "flow":
            text = self.supervisor._call_llm(
                f"对话:\n{conv_text}\n\n你是学习助手。学生发了学习过渡语。请根据上下文自然回应,2-3句话。",
                temperature=0.7, max_tokens=300)
        else:
            lp = session.get("learning_path",{})
            steps = self._flat_steps(lp)
            sn = "、".join([s["name"] for s in steps[:3]]) if steps else "基础知识"
            hint = f"当前路径: {sn}。只讨论ML,无关话题礼貌拒绝引导回ML。"
            text = self.supervisor._call_llm(
                f"对话:\n{conv_text}\n\n你是学习助手。{hint}请自然回复,2-3句话。",
                temperature=0.7, max_tokens=300)
        for ch in text: yield {"type":"text","content":ch}; time.sleep(0.015)
        result["content"] = text

_system: Optional[LearningSystem] = None

def get_learning_system() -> LearningSystem:
    global _system
    if _system is None: _system = LearningSystem()
    return _system
