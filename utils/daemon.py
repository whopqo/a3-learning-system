"""
守护进程模块 —— 后台巡检线程（参考 inkos 的 Scheduler 自我保护设计）
守护的内容：LLM 接口连通性、知识库状态、磁盘空间、会话自动落盘
带防重入和连续失败告警，出问题记日志，界面上能看到状态
"""
import os
import time
import threading

from utils import logger

_CHECK_INTERVAL = 300  # 5分钟巡检一次

class Daemon:
    def __init__(self):
        self._thread = None
        self._stop_flag = threading.Event()
        self._running_check = False  # 防重入标记
        self.started_at = None
        self.last_check = None
        self.consecutive_fails = 0
        self.events = []  # 最近事件，给界面看
        self._lock = threading.Lock()
        self._system = None  # LearningSystem 实例，start 时注入

    def start(self, system=None):
        if self._thread and self._thread.is_alive():
            return {"ok": False, "error": "守护进程已在运行"}
        if system is not None:
            self._system = system
        self._stop_flag.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="a3-daemon")
        self._thread.start()
        self.started_at = time.time()
        logger.info("守护进程启动", "daemon")
        self._push_event("start", "守护进程启动")
        return {"ok": True}

    def stop(self):
        if not (self._thread and self._thread.is_alive()):
            return {"ok": False, "error": "守护进程未在运行"}
        self._stop_flag.set()
        logger.info("守护进程停止", "daemon")
        self._push_event("stop", "守护进程停止")
        return {"ok": True}

    def status(self) -> dict:
        running = bool(self._thread and self._thread.is_alive() and not self._stop_flag.is_set())
        with self._lock:
            events = list(self.events[-20:])
        return {
            "running": running,
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.started_at)) if self.started_at else None,
            "uptime_seconds": int(time.time() - self.started_at) if (running and self.started_at) else 0,
            "last_check": self.last_check,
            "consecutive_fails": self.consecutive_fails,
            "check_interval": _CHECK_INTERVAL,
            "events": events,
        }

    def _push_event(self, kind: str, msg: str, ok: bool = True):
        with self._lock:
            self.events.append({
                "time": time.strftime("%H:%M:%S"),
                "kind": kind, "message": msg, "ok": ok,
            })
            if len(self.events) > 100:
                self.events = self.events[-100:]

    def _loop(self):
        # 启动后先立刻跑一轮，之后按间隔巡检
        while not self._stop_flag.is_set():
            self._tick()
            self._stop_flag.wait(_CHECK_INTERVAL)

    def _tick(self):
        if self._running_check:
            self._push_event("skip", "上一轮巡检未结束，本轮跳过", ok=False)
            return
        self._running_check = True
        try:
            problems = []

            # 1. LLM 连通性（轻量探测，不真正对话）
            try:
                from utils import llm_manager
                state = llm_manager.get_state()
                svc = state["active"]["service"]
                r = llm_manager.test_connection(svc)
                if r.get("ok"):
                    self._push_event("llm", f"模型接口正常 ({svc})")
                else:
                    problems.append(f"模型接口异常: {r.get('error', '')[:80]}")
            except Exception as e:
                problems.append(f"模型检查出错: {str(e)[:80]}")

            # 2. 知识库状态
            try:
                from rag.engine import is_kb_ready
                if is_kb_ready():
                    self._push_event("kb", "知识库正常")
                else:
                    problems.append("知识库未就绪")
            except Exception as e:
                problems.append(f"知识库检查出错: {str(e)[:80]}")

            # 3. 磁盘空间
            try:
                import shutil
                free_gb = shutil.disk_usage(os.path.dirname(os.path.abspath(__file__))).free / (1024**3)
                if free_gb < 1:
                    problems.append(f"磁盘空间不足: 剩余 {free_gb:.1f}GB")
                else:
                    self._push_event("disk", f"磁盘剩余 {free_gb:.0f}GB")
            except Exception:
                pass

            # 4. 会话自动落盘
            try:
                if self._system is not None:
                    self._system._save_sessions()
                    self._push_event("session", f"会话已保存 ({len(self._system.sessions)}个)")
            except Exception as e:
                problems.append(f"会话保存失败: {str(e)[:80]}")

            # 5. 每日一练：每天第一轮巡检时按薄弱点自动出题
            try:
                self._daily_quiz()
            except Exception as e:
                logger.warn(f"每日一练生成失败: {str(e)[:80]}", "daemon")

            self.last_check = time.strftime("%Y-%m-%d %H:%M:%S")
            if problems:
                self.consecutive_fails += 1
                for p in problems:
                    logger.warn(p, "daemon")
                    self._push_event("problem", p, ok=False)
                # 连续3轮出问题就升级成 ERROR 日志提醒用户
                if self.consecutive_fails >= 3:
                    logger.error(f"连续{self.consecutive_fails}轮巡检发现问题，请检查系统状态", "daemon")
            else:
                self.consecutive_fails = 0
        finally:
            self._running_check = False


    def _daily_quiz(self):
        """每天自动生成一份针对薄弱点的小练习，存 db/daily_quiz.json"""
        import json
        fp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db", "daily_quiz.json")
        today = time.strftime("%Y-%m-%d")
        try:
            with open(fp, "r", encoding="utf-8") as f:
                if json.load(f).get("date") == today:
                    return  # 今天已经出过了
        except Exception:
            pass
        if self._system is None:
            return
        # 找最近一个有学习数据的会话画像：优先"快忘了该复习"的知识点，其次薄弱点
        weak, profile = [], {}
        for sess in reversed(list(self._system.sessions.values())):
            p = sess.get("profile") or {}
            if p.get("struggling_topics") or p.get("mastery_map"):
                from utils import mastery as mastery_mod
                due = mastery_mod.due_for_review(p)
                weak = due + [w for w in p.get("struggling_topics", []) if w not in due]
                profile = p
                break
        if not weak:
            return  # 没有薄弱点数据就不打扰
        topic = weak[0]
        from rag.engine import retrieve_knowledge, is_kb_ready
        if not is_kb_ready():
            return
        rag = retrieve_knowledge(topic, k=3)
        prompt = f"""学生的薄弱知识点是「{'、'.join(weak[:3])}」。请基于知识库内容出3道针对性练习题帮他巩固。

【知识库内容】
{rag[:2000]}

返回JSON数组，每题格式：
{{"type": "单选题/判断题", "question": "题目", "options": ["具体选项A","B","C","D"], "answer": "正确答案", "explanation": "解析", "knowledge_point": "知识点"}}
判断题options填["对","错"]。题干直接问知识本身，不要出现"根据知识库/教材"字样。只输出纯JSON数组。"""
        exercises = self._system.resource_agent._call_llm_json(prompt, temperature=0.4, max_tokens=1500, fallback=[])
        if not exercises:
            return
        with open(fp, "w", encoding="utf-8") as f:
            json.dump({"date": today, "topic": topic, "weak_points": weak[:3],
                       "exercises": exercises}, f, ensure_ascii=False, indent=2)
        logger.info(f"每日一练已生成: {len(exercises)}题，针对「{topic}」", "daemon")
        self._push_event("daily", f"每日一练已生成（针对 {topic}）")


# 全局单例
daemon = Daemon()
