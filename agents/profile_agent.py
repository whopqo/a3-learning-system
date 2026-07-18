"""
Profile Agent —— LLM驱动的自然对话画像构建
不再使用固定问卷，LLM根据对话上下文决定下一个问题
"""
import json, re, time
from typing import Dict, Any
from agents.base_agent import BaseAgent
from config import AGENT_SYSTEM_PROMPTS

class ProfileAgent(BaseAgent):
    """学情分析师 —— LLM驱动的自然对话画像"""

    # 必须收集的维度——统一用短名
    _REQUIRED_DIMS = ["ml", "prog", "math", "goal", "style", "time", "weak", "lang"]
    # 短名→长名字段映射
    _SHORT_TO_FIELD = {"ml":"ml_prerequisites","prog":"programming","math":"math",
                       "goal":"short_term_goal","style":"cognitive_style",
                       "time":"time_per_week","weak":"struggling","lang":"language_style"}
    # 长名→短名(从_SHORT_TO_FIELD反向生成)
    _LONG2SHORT = {v:k for k,v in _SHORT_TO_FIELD.items()}
    # 补充短名→短名映射(让get("style","style")能正确返回"style")
    _LONG2SHORT.update({k:k for k in _SHORT_TO_FIELD})

    def __init__(self):
        super().__init__(
            name="ProfileBuilder",
            role="学情分析师",
            system_prompt=AGENT_SYSTEM_PROMPTS["profile_builder"],
        )

    def _get_asked_dims(self, profile: dict) -> list:
        return profile.get("_asked_dims", [])

    def _remaining_dims(self, profile: dict) -> list:
        """返回还没问的短维度名列表。_asked_dims和_REQUIRED_DIMS统一用短名"""
        asked = set(self._get_asked_dims(profile))
        return [d for d in self._REQUIRED_DIMS if d not in asked]

    def _infer_dim(self, question: str, fallback: str, remaining: list = None) -> str:
        """根据LLM实际生成的问题文字推断维度——返回短名。
        一个问题可能命中多组关键词（"喜欢看视频还是写代码"既像style又像prog），
        优先选还没问过的维度，避免把回答记错地方"""
        q = question
        rules = [
            ("ml",   ["ML","机器学习","了解","接触","算法","听过"]),
            ("prog", ["编程","Python","代码","写","敲"]),
            ("math", ["数学","线代","概率","高数","微积分"]),
            ("goal", ["目标","考研","工作","考试","方向","打算","为了"]),
            ("style",["视频","看书","实践","习惯","风格","学新","喜欢"]),
            ("time", ["时间","每天","每周","小时","节奏","花多少","多少时间"]),
            ("lang", ["严谨","生动","比喻","学术","表达","正式","通俗"]),
            ("weak", ["难","不懂","坑","薄弱","困惑","搞不"]),
        ]
        matches = [dim for dim, kws in rules if any(w in q for w in kws)]
        if remaining:
            for dim in matches:
                if dim in remaining:
                    return dim
        if matches:
            return matches[0]
        # fallback也归一化成短名
        return self._LONG2SHORT.get(fallback, fallback)

    def _mark_dim_asked(self, profile: dict, dim: str):
        asked = list(profile.get("_asked_dims", []))
        if dim not in asked:
            asked.append(dim)
        profile["_asked_dims"] = asked

    def generate_next_question(self, profile: dict, conversation: str) -> str | None:
        """LLM判断下一个该问什么，根据已有对话自然发问"""
        remaining = self._remaining_dims(profile)

        if not remaining:
            profile["_all_asked"] = True
            return None

        # 每个维度的简要说明（用短名key）
        dim_desc = {
            "ml": "学生对ML的了解程度，是否听说过算法",
            "prog": "Python编程水平，写代码经验",
            "math": "数学基础，线性代数/概率论水平",
            "goal": "学习目标：考研/找工作/应付考试/兴趣",
            "style": "学习风格：看视频/看书/写代码/听课",
            "time": "每周能花多少时间学习",
            "weak": "目前觉得难的知识点或薄弱环节",
            "lang": "偏好严谨学术还是生动比喻的表达方式",
        }

        fd = profile.get("knowledge_foundation", {}) or {}
        snapshot = {
            "ml": fd.get("ml_prerequisites", "未知"),
            "prog": fd.get("programming", "未知"),
            "math": fd.get("math", "未知"),
            "goal": profile.get("short_term_goal", "未知"),
            "style": profile.get("cognitive_style", "未知"),
            "time": profile.get("time_per_week", "未知"),
            "weak": profile.get("struggling_topics", []),
            "lang": profile.get("language_style", "待了解"),
        }

        conv_tail = "\n".join(conversation.split("\n")[-6:])

        prompt = f"""你是学习助手，正在了解学生的学习情况。

已收集的信息：
{json.dumps(snapshot, ensure_ascii=False, indent=2)}

还需要了解：{', '.join([dim_desc.get(d, d) for d in remaining])}

最近对话：
{conv_tail}

请用一句话（不超过30字）自然地询问学生下一个需要了解的信息。
规则：
- 像朋友聊天一样自然，不要像在填问卷
- 学生可能一句话回答了多个维度，识别出来就不要重复问
- 直接输出问题文字，不要JSON，不要引号包裹"""

        # LLM挂了或输出太短时的兜底问题——写成人话，别把维度描述直接塞句子里
        fallback_q = {
            "ml": "你对机器学习了解多少？听说过哪些算法吗？",
            "prog": "你的Python编程水平怎么样？",
            "math": "数学基础如何？线代、概率论学过吗？",
            "goal": "这次学习的目标是什么？考研、找工作还是兴趣？",
            "style": "平时喜欢怎么学习？看视频、看书还是动手写代码？",
            "time": "每周大概能拿出多少时间学习？",
            "weak": "目前有没有觉得特别难的知识点？",
            "lang": "讲解风格你喜欢严谨学术一点，还是生动比喻多一点？",
        }
        try:
            result = self._call_llm(prompt, temperature=0.8, max_tokens=80)
            result = result.strip().strip('"').strip("'")
            if len(result) < 3:
                result = fallback_q.get(remaining[0], f"能说说你的{dim_desc.get(remaining[0], remaining[0])}吗？")
            # 记住本轮在问什么维度——系统根据问题文字推断，优先落在还没问的维度上
            profile["_current_dim"] = self._infer_dim(result, remaining[0], remaining)
            return result
        except Exception:
            first = remaining[0]
            result = fallback_q.get(first, f"能说说你的{dim_desc.get(first, first)}吗？")
            profile["_current_dim"] = first
            return result

    @staticmethod
    def _kw_score(answer: str) -> float | None:
        """关键词快判——短回答先过一遍，命中的直接返回评分"""
        a = answer.strip().lower()
        for w in ["！","。","，","？","?","!","…","~","啊","吧","嘛","呢","哦","嗯"]:
            a = a.replace(w, "")
        a = a.strip()
        # ML术语里的"差""弱"不是在说水平差（误差/方差/偏差/弱分类器），先剥掉再匹配
        for term in ["误差", "方差", "偏差", "标准差", "弱分类器", "弱学习器"]:
            a = a.replace(term, "")
        neg = ["没有","不会","不行","不多","很差","零基础","完全没","没学过",
               "不了解","没接触","没怎么","不太会","不太行","不懂","不清楚",
               "没用过","没写过","几乎不","基本不","毫无","一点都没",
               "极少","很少","忘光了","全忘","都忘","没基础","薄弱","差","弱"]
        # 长词优先检查，避免"没问题"被单字"没"误判，避免"不差"被单字"差"误判
        if "差不多" in a: return 0.5  # "学得差不多"是中等，别掉进"不多"的负面词
        safe = ["没问题","不差","不弱","不太差","没压力","没困难"]
        for s in safe:
            if s in a: return 0.7
        for n in neg:
            if n in a: return 0.15
        mid = ["一般","还行","会一点","学过一点","了解一点","有点基础",
               "凑合","勉强","一点点","一些","不多不少","大概","及格",
               "了解过","知道一点","接触过","用过一点","写过一些"]
        for m in mid:
            if m in a: return 0.5
        good = ["不错","挺好","熟悉","挺熟","比较多","经常","还可以",
                "熟练","没问题","没问题吧","够用","足够","过关","扎实"]
        for g in good:
            if g in a: return 0.7
        great = ["很强","很熟","专业","专家","精通","非常好","厉害","高手",
                 "科班","专业学","都学过","没问题","很扎实"]
        for g in great:
            if g in a: return 0.9
        return None  # 关键词没命中，交给LLM

    @staticmethod
    def _mentions_multiple_dims(text: str) -> bool:
        """短回答里同时提到2个以上维度的关键词（"会Python，数学还行"），要走LLM分开提取"""
        low = text.lower()
        groups = [["机器学习", "ml", "算法"], ["python", "编程", "代码"],
                  ["数学", "线代", "概率"], ["考研", "找工作", "兴趣", "目标"],
                  ["视频", "看书", "动手"], ["小时", "每周", "每天"], ["严谨", "比喻"]]
        hits = sum(1 for g in groups if any(w in low for w in g))
        return hits >= 2

    def extract_profile_update(self, conversation: str, profile: dict) -> dict:
        """提取画像——关键词快判短回答，LLM处理复杂回答"""
        user_lines = []
        for line in conversation.split("\n"):
            line = line.strip()
            if line.startswith("学生:") or line.startswith("学生："):
                user_lines.append(line[3:].strip())
            elif line.startswith("用户:") or line.startswith("用户："):
                user_lines.append(line[3:].strip())
        last_answer = user_lines[-1] if user_lines else ""

        # 先从_current_dim拿兜底维度名（generate_next_question设的）
        dim_fallback = profile.pop("_current_dim", None)

        # 关键词快判——只允许"单一维度的短回答"走快速路径。
        # 长回答、或者短回答里同时提了多个维度（"会Python，数学还行"），都交给LLM分开提取
        kw_result = self._kw_score(last_answer)
        if dim_fallback and len(last_answer) < 20 and not self._mentions_multiple_dims(last_answer):
            short = {"ml_prerequisites":"ml","programming":"prog","math":"math",
                     "short_term_goal":"goal","cognitive_style":"style",
                     "time_per_week":"time","struggling":"weak",
                     "language_style":"lang"}.get(dim_fallback, dim_fallback)
            # 评分类维度必须关键词命中才能快判，其他维度短回答直接记
            if short in ("ml","prog","math") and kw_result is None:
                pass  # 交给下面的LLM提取
            else:
                if short in ("ml","prog","math"):
                    sub = {"ml":"ml_prerequisites","prog":"programming","math":"math"}[short]
                    profile.setdefault("knowledge_foundation",{})[sub] = kw_result
                elif short == "goal":
                    profile["short_term_goal"] = last_answer[:30]
                elif short == "style":
                    if "视频" in last_answer: profile["cognitive_style"] = "视觉型"
                    elif "代码" in last_answer or "写" in last_answer: profile["cognitive_style"] = "动手型"
                    elif "看书" in last_answer or "书" in last_answer: profile["cognitive_style"] = "文字型"
                    else: profile["cognitive_style"] = last_answer[:10]
                elif short == "time":
                    profile["time_per_week"] = last_answer[:50]
                elif short == "weak":
                    profile.setdefault("struggling_topics",[]).append(last_answer[:30])
                elif short == "lang":
                    profile["language_style"] = "严谨学术" if "严谨" in last_answer else ("生动比喻" if "生动" in last_answer else last_answer[:10])
                self._mark_dim_asked(profile, short)
                self._record_evidence(profile, short, last_answer)
                profile["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
                return {"dims_covered": [short]}
        # 关键词+_current_dim都没命中 → LLM兜底提取
        fd = profile.get("knowledge_foundation", {}) or {}
        current = {
            "ml": fd.get("ml_prerequisites", 0.4),
            "prog": fd.get("programming", 0.4),
            "math": fd.get("math", 0.4),
            "goal": profile.get("short_term_goal", "待了解"),
            "style": profile.get("cognitive_style", "待了解"),
            "time": profile.get("time_per_week", "待了解"),
            "lang": profile.get("language_style", "待了解"),
            "weak": profile.get("struggling_topics", []),
            "mastered": profile.get("mastered_topics", []),
        }
        conv_tail = "\n".join(conversation.split("\n")[-8:])
        asking_hint = ""
        if dim_fallback:
            asking_hint = f"\n本轮系统在问的维度是「{dim_fallback}」，但学生一句话可能顺带回答了其他维度，全部都要提取，一个不能漏。"

        # 还没收集的维度说明，让LLM顺便把下一个问题也生成了（省一次调用）
        remaining_now = self._remaining_dims(profile)
        dim_desc = {"ml": "对机器学习的了解程度", "prog": "Python编程水平", "math": "数学基础",
                    "goal": "学习目标(考研/工作/兴趣)", "style": "学习风格(视频/看书/动手)",
                    "time": "每周学习时间", "weak": "薄弱知识点", "lang": "讲解偏好(严谨/生动)"}
        remaining_desc = "、".join(f"{d}({dim_desc.get(d,d)})" for d in remaining_now)

        prompt = f"""从对话提取学生画像。注意：学生一句话经常包含多个维度的信息（比如"我会Python但没学过机器学习，想考研"同时说了prog/ml/goal），必须全部提取！{asking_hint}

最近对话：
{conv_tail}

当前画像：{json.dumps(current, ensure_ascii=False)}
还没收集的维度：{remaining_desc or '已全部收集'}

评分规则（严格遵守）：
- "没有/不会/不行/不多/零基础/完全没/没学过/不了解" → 0.15
- "薄弱/比较弱/很差/基础差" → 0.2
- "一般/还行/会一点/学过一点/了解一点" → 0.5
- "不错/挺好/熟悉/经常" → 0.7
- "很强/精通/专业/科班" → 0.9
- 评分必须对准维度：说"数学还行但编程没学过"→math填0.5、prog填0.15，别搞混
- 只填学生这轮真正提到的字段，没提到的填null

返回JSON：
{{
    "ml": 数字或null,
    "prog": 数字或null,
    "math": 数字或null,
    "goal": "字符串或null",
    "style": "字符串或null",
    "time": "字符串或null",
    "lang": "严谨学术/生动比喻或null",
    "weak": ["知识点列表或空数组"],
    "mastered": ["知识点列表或空数组"],
    "dims_covered": ["本轮被回答的维度:ml/prog/math/goal/style/time/weak/lang"],
    "next_question": "针对提取后仍缺的第一个维度，像朋友聊天一样自然地问学生一句话(30字内)。提取后维度都齐了就填null"
}}

只输出纯JSON。"""

        try:
            result = self._call_llm_json(prompt, temperature=0.2, max_tokens=800,
                                         fallback={"dims_covered": []})
        except Exception:
            return {"dims_covered": []}

        if not result:
            return {"dims_covered": []}

        # 应用提取结果到 profile
        updated = False
        if result.get("ml") is not None:
            profile.setdefault("knowledge_foundation", {})["ml_prerequisites"] = result["ml"]
            updated = True
        if result.get("prog") is not None:
            profile.setdefault("knowledge_foundation", {})["programming"] = result["prog"]
            updated = True
        if result.get("math") is not None:
            profile.setdefault("knowledge_foundation", {})["math"] = result["math"]
            updated = True
        if result.get("goal") is not None and result["goal"] not in ("待了解", ""):
            profile["short_term_goal"] = result["goal"]
            updated = True
        if result.get("style") is not None and result["style"] not in ("待了解", ""):
            profile["cognitive_style"] = result["style"]
            updated = True
        if result.get("time") is not None and result["time"] not in ("待了解", ""):
            profile["time_per_week"] = result["time"]
            updated = True
        if result.get("lang") is not None and result["lang"] not in ("待了解", ""):
            profile["language_style"] = result["lang"]
            updated = True

        # 自动推导 difficulty_level（基于知识基础三要素）
        fd = profile.get("knowledge_foundation", {})
        avg = (fd.get("ml_prerequisites",0.4) + fd.get("programming",0.4) + fd.get("math",0.4)) / 3
        if avg < 0.35: profile["difficulty_level"] = "入门"
        elif avg < 0.65: profile["difficulty_level"] = "中级"
        else: profile["difficulty_level"] = "进阶"

        # 推导每周学习频率和时长
        time_str = profile.get("time_per_week", "")
        hours = re.findall(r'(\d+)', str(time_str))
        if hours:
            h = int(hours[0])
            profile["weekly_frequency"] = min(h, 7)
            profile["avg_session_minutes"] = 45 if h < 5 else (60 if h < 10 else 90)
        else:
            profile["weekly_frequency"] = 3
            profile["avg_session_minutes"] = 45

        if result.get("weak"):
            existing = list(profile.get("struggling_topics", []))
            for w in result["weak"]:
                if w not in existing:
                    existing.append(w)
            profile["struggling_topics"] = existing
            updated = True
        if result.get("mastered"):
            existing = list(profile.get("mastered_topics", []))
            for m in result["mastered"]:
                if m not in existing:
                    existing.append(m)
            profile["mastered_topics"] = existing
            updated = True

        # 标记已覆盖的维度 + 记录判断依据（画像页展示用）
        for d in (result.get("dims_covered") or []):
            self._mark_dim_asked(profile, d)
            self._record_evidence(profile, d, last_answer)

        if updated:
            profile["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")

        return result

    @staticmethod
    def _record_evidence(profile: dict, dim: str, answer: str):
        """记下每个维度是根据学生哪句话判断的。长句只截取和该维度相关的片段，
        不然快速开始一句话答8个维度，每个维度的依据都是同一大段话"""
        if not answer:
            return
        dim_kws = {
            "ml": ["机器学习", "ml", "算法", "没学过", "零基础"],
            "prog": ["python", "编程", "代码", "程序"],
            "math": ["数学", "线代", "概率", "微积分", "高数"],
            "goal": ["目标", "考研", "工作", "入门", "考试", "兴趣", "就业"],
            "style": ["视频", "看书", "动手", "实践", "喜欢"],
            "time": ["小时", "每周", "每天", "时间"],
            "weak": ["薄弱", "难", "不懂", "说不上来", "不知道哪里"],
            "lang": ["比喻", "严谨", "通俗", "学术", "生动", "讲解"],
        }
        snippet = answer
        if len(answer) > 30:
            # 按逗号句号切片，挑出含该维度关键词的片段
            import re as _re
            parts = [p.strip() for p in _re.split(r'[，。；,;]', answer) if p.strip()]
            kws = dim_kws.get(dim, [])
            hits = [p for p in parts if any(k in p.lower() for k in kws)]
            if hits:
                snippet = "，".join(hits[:2])
        ev = profile.get("_evidence") or {}
        ev[dim] = snippet[:80]
        profile["_evidence"] = ev

    def generate_guide_question(self, profile: dict, round_num: int) -> str | None:
        """兼容旧接口 —— 只是占位，实际调generate_next_question"""
        asked = self._get_asked_dims(profile)
        if len(asked) >= 6:
            profile["_all_asked"] = True
            return None
        # 旧接口不需要返回问题，handler会自己调generate_next_question
        return None

    def is_sufficient(self, profile: dict) -> bool:
        """画像是否足够——8维满7个放行"""
        if not profile:
            return False
        if profile.get("_all_asked"):
            return True
        if not profile.get("target_course") or profile["target_course"] in ("待了解", ""):
            profile["target_course"] = "机器学习"
        remaining = self._remaining_dims(profile)
        asked = len(self._REQUIRED_DIMS) - len(remaining)
        return asked >= 7

    def get_ack_for_dim(self, dim_key: str) -> str:
        acks = {"ml": "", "prog": "收到", "math": "了解", "goal": "明白",
                "style": "好的", "time": "了解", "weak": "明白", "lang": "好嘞"}
        return acks.get(dim_key, "")

    def _fallback_profile(self) -> dict:
        return {
            "knowledge_foundation": {},
            "mastered_topics": [],
            "struggling_topics": [],
            "cognitive_style": "待了解",
            "difficulty_level": "待了解",
            "short_term_goal": "待了解",
            "preferred_formats": [],
            "knowledge_gaps": [],
            "error_patterns": [],
            "target_course": "机器学习",
            "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "_asked_dims": [],
        }

    def process(self, **kwargs) -> Dict[str, Any]:
        conversation = kwargs.get("conversation", "")
        current_profile = kwargs.get("current_profile")
        round_num = kwargs.get("round_num", 1)

        profile = dict(current_profile) if current_profile else self._fallback_profile()
        profile.setdefault("knowledge_foundation", {})
        profile.setdefault("_asked_dims", [])
        profile.setdefault("target_course", "机器学习")

        # 提取画像（LLM路径会顺便把下一个问题也带回来）
        extract_result = {}
        if conversation:
            extract_result = self.extract_profile_update(conversation, profile) or {}

        # 判断是否够了
        if self.is_sufficient(profile):
            profile["_all_asked"] = True
            return {"agent": self.name, "profile": profile,
                    "is_new": False, "guide_question": None}

        # 优先用提取时顺便生成的问题，没有再单独调一次LLM
        guide_q = extract_result.get("next_question")
        if isinstance(guide_q, str) and len(guide_q.strip()) >= 4:
            guide_q = guide_q.strip()
            remaining = self._remaining_dims(profile)
            if remaining:
                profile["_current_dim"] = self._infer_dim(guide_q, remaining[0], remaining)
        else:
            guide_q = self.generate_next_question(profile, conversation)
        return {"agent": self.name, "profile": profile,
                "is_new": not bool(current_profile),
                "guide_question": guide_q}
