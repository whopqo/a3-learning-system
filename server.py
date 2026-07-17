"""
FastAPI 服务端 —— SSE流式 + 多智能体系统API
启动: python server.py  或  uvicorn server:app --host 0.0.0.0 --port 8000
"""
import os, sys, time, json, asyncio
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, Request, Query
from fastapi.responses import StreamingResponse, FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
import uvicorn

from handler import get_learning_system
from config import LLM_PROVIDER, PROJ_ROOT
from rag.engine import is_kb_ready, get_available_topics
from utils.logger import info, warn, error, get_recent, get_stats, get_sources
from utils import llm_manager, project_settings, skill_manager
from utils.daemon import daemon

app = FastAPI(title="AI个性化学习助手", version="3.1")
app.mount("/static", StaticFiles(directory=os.path.join(PROJ_ROOT, "static")), name="static")

# 全局系统实例
system = get_learning_system()

@app.on_event("startup")
async def startup():
    project_settings.load_and_apply()   # 应用项目设置
    daemon.start(system)                # 守护进程随服务自动启动
    topics = get_available_topics() if is_kb_ready() else []
    print(f"Server ready | Provider: {LLM_PROVIDER} | KB: {is_kb_ready()} | Topics: {topics}")

@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "provider": LLM_PROVIDER,
        "kb_ready": is_kb_ready(),
        "topics": get_available_topics() if is_kb_ready() else [],
    }

@app.post("/api/chat")
async def chat(request: Request):
    """SSE流式聊天端点"""
    body = await request.json()
    message = body.get("message", "").strip()
    session_id = body.get("session_id", f"u{int(time.time())}")
    # 对话框里选的模型，只对本次消息生效
    sel_service = body.get("service", "")
    sel_model = body.get("model", "")
    # 勾选的教学模式 + 关键词自动触发
    req_skills = body.get("skills", []) or []

    if not message:
        return StreamingResponse(
            _sse_event("error", "消息为空"),
            media_type="text/event-stream"
        )

    async def generate():
        try:
            if sel_service:
                llm_manager.set_session_override(sel_service, sel_model)
            used = skill_manager.resolve(req_skills, message)
            skill_manager.set_active(used)
            if used:
                yield _sse_event("skills", json.dumps([s["name"] for s in used], ensure_ascii=False))
            for event in system.process_message_stream(message, session_id):
                if event["type"] == "text":
                    yield _sse_event("text", event["content"])
                elif event["type"] == "progress":
                    yield _sse_event("progress", json.dumps({
                        "step": event["step"],
                        "total": event["total"],
                        "label": event.get("label", ""),
                    }, ensure_ascii=False))
                elif event["type"] == "done":
                    result = event["result"]
                    meta = event.get("metadata", {})
                    # 提取session状态
                    sess = system.sessions.get(session_id, {})
                    payload = {
                        "content": result["content"],
                        "type": result.get("type", "chat"),
                        "profile": sess.get("profile"),
                        "resources": sess.get("resources"),
                        "learning_path": sess.get("learning_path"),
                        "phase": sess.get("phase"),
                    }
                    yield _sse_event("done", json.dumps(payload, ensure_ascii=False, default=str))
        except Exception as e:
            yield _sse_event("error", str(e)[:200])
        finally:
            llm_manager.clear_session_override()
            skill_manager.clear_active()

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.post("/api/export-pptx")
async def export_pptx(request: Request):
    """导出PPTX文件"""
    body = await request.json()
    ppt_outline = body.get("ppt_outline", "")
    topic = body.get("topic", "课件")

    if not ppt_outline:
        return {"error": "无PPT大纲"}

    try:
        from utils.ppt_exporter import export_pptx
    except ImportError:
        return {"error": "PPT功能未安装，请运行: pip install python-pptx"}
    fp = export_pptx(ppt_outline, topic)
    return FileResponse(fp, filename=os.path.basename(fp),
                        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation")

@app.post("/api/evaluate")
async def evaluate_exercises(request: Request):
    """提交练习答案 → 关键词快判 + EvaluateAgent LLM深度分析 + 掌握度+画像更新"""
    try:
        body = await request.json()
    except Exception:
        return {"total": 0, "correct": 0, "score": 0, "results": [], "ai_analysis": "请求格式无效"}

    exercises = body.get("exercises", [])
    answers = body.get("answers", {}) or {}
    profile = body.get("profile", {}) or {}

    try:
        # ── 第一步：关键词快速判对错（毫秒级，准确度足够） ──
        results, correct_count = [], 0
        for i, ex in enumerate(exercises):
            q = str(ex.get("question", "") or "")
            correct_ans = str(ex.get("answer", "") or "")
            explanation = str(ex.get("explanation", "") or "")
            question_type = str(ex.get("type", "") or "")
            student_ans = str(answers.get(str(i), "") or "").strip()

            if "," in correct_ans or "，" in correct_ans:
                correct_parts = set(p.strip().lower() for p in correct_ans.replace("，",",").split(",") if p.strip())
                student_parts = set(p.strip().lower() for p in student_ans.replace("，",",").split(",") if p.strip())
                is_correct = bool(student_parts and correct_parts and student_parts == correct_parts)
            elif question_type and "判断" in question_type:
                s = student_ans.strip().lower()
                c = correct_ans.strip().lower()
                is_correct = bool(s and c and (s == c or s[0] == c[0]))
            elif student_ans and correct_ans:
                s = student_ans.strip().lower()
                c = correct_ans.strip().lower()
                is_correct = (s == c) or (c in s) or (s in c)
            else:
                is_correct = False

            if is_correct: correct_count += 1
            results.append({"index":i, "question":q[:200], "student_answer":student_ans[:200],
                "correct_answer":correct_ans[:200], "is_correct":is_correct, "explanation":explanation[:500]})

        score = round(correct_count/len(exercises)*100) if exercises else 0

        # ── 从判对错结果中提取知识点 ──
        wrong_kps = []
        right_kps = []
        ML_KW = ["决策树","SVM","支持向量机","线性回归","逻辑回归","随机森林",
                 "神经网络","聚类","KNN","K-means","朴素贝叶斯","集成学习",
                 "梯度下降","过拟合","正则化","特征工程","降维","交叉验证",
                 "信息增益","基尼系数","贝叶斯","XGBoost","PCA","损失函数",
                 "感知机","强化学习","半监督","降维","度量学习","概率图",
                 "深度学习","CNN","RNN","LSTM","激活函数","归一化","标准化"]
        for r in results:
            idx = r["index"]
            if idx < len(exercises):
                kp = exercises[idx].get("knowledge_point", "")
            else:
                kp = ""
            if not kp:
                for kw in ML_KW:
                    if kw in r.get("question", ""):
                        kp = kw
                        break
            if r["is_correct"]:
                if kp and kp not in right_kps: right_kps.append(kp)
            else:
                if kp and kp not in wrong_kps: wrong_kps.append(kp)

        # ── 第二步：EvaluateAgent LLM深度分析（异步执行避免阻塞） ──
        topic_key = body.get("topic", "")
        session_id = body.get("session_id", "")
        mastery_updates = {}
        ai_analysis = ""
        updated_path_steps = []
        updated_weaknesses = []
        error_pattern_counts = {}

        # 错题落盘进错题本（复习卷靠它）
        try:
            from utils import mistake_book
            wrongs = [r for r in results if not r["is_correct"]]
            if wrongs:
                mistake_book.add_mistakes(session_id, topic_key, wrongs, exercises)
        except Exception:
            pass

        # 错因归类：把错题归成四种模式，累计进画像
        if any(not r["is_correct"] for r in results):
            try:
                import asyncio as _aio
                wrong_desc = "\n".join(
                    f"- {r['question'][:60]} | 学生答:{r['student_answer'][:30]} | 正确:{r['correct_answer'][:30]}"
                    for r in results if not r["is_correct"])[:1200]
                cls_prompt = ("把下面的错题逐题归类为四种错因之一：概念混淆/计算失误/审题不清/知识空白。\n"
                              + wrong_desc +
                              '\n返回JSON：{"概念混淆":数量,"计算失误":数量,"审题不清":数量,"知识空白":数量}，数量为0的也要填。只输出JSON。')
                error_pattern_counts = await _aio.to_thread(
                    lambda: system.supervisor._call_llm_json(cls_prompt, temperature=0.1, max_tokens=150, fallback={}))
                if not isinstance(error_pattern_counts, dict):
                    error_pattern_counts = {}
            except Exception:
                error_pattern_counts = {}

        def _llm_deep_analysis():
            """用EvaluateAgent做LLM深度批改"""
            from agents.evaluate_agent import EvaluateAgent
            evaluator = EvaluateAgent()

            answer_text_parts = []
            for r in results:
                status = "对" if r["is_correct"] else "错"
                answer_text_parts.append(
                    f"第{r['index']+1}题({status}): 学生答案={r['student_answer'][:80]}, 正确答案={r['correct_answer'][:80]}")
            answer_text = "\n".join(answer_text_parts)

            return evaluator.process(
                exercises=exercises, student_answers=answer_text,
                profile=profile, error_records=[])

        try:
            import asyncio as aio
            eval_result = await aio.to_thread(_llm_deep_analysis)

            evaluation = eval_result.get("evaluation", {})
            mastery_updates = eval_result.get("mastery_updates", {})

            if evaluation.get("suggestion"):
                ai_analysis = evaluation["suggestion"]
            else:
                ai_analysis = f"共{len(exercises)}题，答对{correct_count}题，得分{score}分。"

            eval_weaknesses = evaluation.get("weaknesses", [])
            updated_weaknesses = [w for w in eval_weaknesses if w and w != "无"]

        except Exception:
            # 兜底——用 supervisor LLM 生成个性化分析
            try:
                fd = profile.get("knowledge_foundation", {})
                style = profile.get("cognitive_style", "")
                goal = profile.get("short_term_goal", "")
                wrong_info = "\n".join([
                    f"- 第{r['index']+1}题: {r['question'][:60]} (你的答案: {r['student_answer'][:40]}, 正确: {r['correct_answer'][:40]})"
                    for r in results if not r["is_correct"]
                ]) if any(not r["is_correct"] for r in results) else "全部正确"
                right_info = "\n".join([
                    f"- 第{r['index']+1}题: {r['question'][:40]}"
                    for r in results if r["is_correct"]
                ])

                anal_prompt = f"""你是学习评估专家。请根据学生答题情况做一个个性化分析。要求丰富但不啰嗦，150-300字。

得分: {score}/100 ({correct_count}/{len(exercises)}正确)

错题详情:
{wrong_info}

对题:
{right_info}

学生画像: ML基础={fd.get('ml_prerequisites',0.4):.0%} 编程={fd.get('programming',0.4):.0%} 数学={fd.get('math',0.4):.0%} 目标={goal} 风格={style}
薄弱知识点: {', '.join(wrong_kps) if wrong_kps else '无'}

请分析：
1. 整体表现评价（根据画像水平判断）
2. 错题暴露的知识漏洞
3. 针对这个学生的具体学习建议（结合目标和风格）
4. 下一步做什么

直接输出分析文字，不要JSON，不要标题编号。"""

                result = system.supervisor._call_llm(anal_prompt, temperature=0.5, max_tokens=500)
                ai_analysis = result.strip() if result else f"共{len(exercises)}题，答对{correct_count}题，得分{score}分。"
            except Exception:
                parts = [f"本次共 {len(exercises)} 题，答对 {correct_count} 题，得分 {score} 分。"]
                if wrong_kps:
                    parts.append(f"薄弱环节：{'、'.join(wrong_kps[:5])}，建议重点复习。")
                if score < 60:
                    parts.append("建议先从讲义的概念讲解开始，打好基础再做题。")
                elif score < 80:
                    parts.append("基础不错，针对薄弱点加强练习就能提升。")
                else:
                    parts.append("掌握得很好，可以继续下一阶段了。")
                ai_analysis = "\n\n".join(parts)

        # ── 第三步：更新 session 画像和路径 ──
        if session_id and session_id in system.sessions:
            sess = system.sessions[session_id]
            sess_profile = sess.get("profile") or {}
            changed = False

            # 滚动正确率（最近15题），出题难度自适应靠这个
            rr = list(sess.get("recent_results", []))
            rr.extend(bool(r["is_correct"]) for r in results)
            sess["recent_results"] = rr[-15:]
            if sess["recent_results"]:
                sess_profile["_recent_accuracy"] = round(
                    sum(sess["recent_results"]) / len(sess["recent_results"]), 2)
                changed = True

            # 动态画像：考得好基础评分小步上调，考得差下调（有依据地演化，不是一锤定音）
            fd0 = sess_profile.setdefault("knowledge_foundation", {})
            old_ml = fd0.get("ml_prerequisites", 0.4)
            if score >= 80:
                fd0["ml_prerequisites"] = round(min(old_ml + 0.05, 0.9), 2)
            elif score < 40:
                fd0["ml_prerequisites"] = round(max(old_ml - 0.05, 0.15), 2)
            if fd0.get("ml_prerequisites") != old_ml:
                avg0 = (fd0.get("ml_prerequisites", 0.4) + fd0.get("programming", 0.4) + fd0.get("math", 0.4)) / 3
                sess_profile["difficulty_level"] = "入门" if avg0 < 0.35 else ("中级" if avg0 < 0.65 else "进阶")
                changed = True

            # 薄弱点写入画像（知识点概念名，不存题目文本）
            if wrong_kps:
                existing = list(sess_profile.get("struggling_topics", []))
                for w in wrong_kps:
                    if w not in existing:
                        existing.append(w)
                sess_profile["struggling_topics"] = existing
                changed = True

            # 答对的知识点加入已掌握
            if right_kps:
                mastered = list(sess_profile.get("mastered_topics", []))
                for rk in right_kps:
                    if rk not in mastered:
                        mastered.append(rk)
                sess_profile["mastered_topics"] = mastered
                changed = True

            # 掌握度更新
            if mastery_updates:
                mastered = list(sess_profile.get("mastered_topics", []))
                for kp, val in mastery_updates.items():
                    if val >= 0.7 and kp not in mastered:
                        mastered.append(kp)
                sess_profile["mastered_topics"] = mastered
                changed = True

            # 知识点级掌握度地图：每题都更新分数，名单从地图派生（带遗忘衰减）
            from utils import mastery as mastery_mod
            for r in results:
                idx = r["index"]
                kp = exercises[idx].get("knowledge_point", "") if 0 <= idx < len(exercises) else ""
                if kp and len(kp) <= 12 and "?" not in kp and "？" not in kp:
                    mastery_mod.update_kp(sess_profile, kp, 1.0 if r["is_correct"] else 0.2)
            # 评估agent返回的键有时是题干文本，只认这套题里声明过的知识点
            valid_kps = {ex.get("knowledge_point", "") for ex in exercises if ex.get("knowledge_point")}
            for kp, val in (mastery_updates or {}).items():
                if kp not in valid_kps:
                    continue
                try:
                    mastery_mod.update_kp(sess_profile, kp, float(val))
                except (ValueError, TypeError):
                    pass
            if sess_profile.get("mastery_map"):
                mastery_mod.sync_lists(sess_profile)
                changed = True

            # 错因模式累计（出题和辅导会参考）
            if error_pattern_counts:
                ep = sess_profile.get("error_patterns") or {}
                if isinstance(ep, list):  # 老字段是列表，换成计数字典
                    ep = {}
                for k, v in error_pattern_counts.items():
                    try:
                        if int(v) > 0:
                            ep[k] = int(ep.get(k, 0)) + int(v)
                    except (ValueError, TypeError):
                        pass
                sess_profile["error_patterns"] = ep
                changed = True

            if changed:
                sess_profile["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
                sess["profile"] = sess_profile

            # 得分≥60时标记对应路径步
            if score >= 60 and topic_key:
                flat_steps = system._flat_steps(sess.get("learning_path", {}))
                for s in flat_steps:
                    sn = s.get("name", "")
                    if topic_key in sn or sn in topic_key:
                        if sn not in (sess_profile.get("mastered_topics") or []):
                            sess_profile.setdefault("mastered_topics", []).append(sn)
                        updated_path_steps.append(sn)

        return {
            "total": len(exercises),
            "correct": correct_count,
            "score": score,
            "results": results,
            "ai_analysis": ai_analysis,
            "updated_path_steps": updated_path_steps,
            "updated_weaknesses": updated_weaknesses,
            "mastery_updates": mastery_updates,
            "updated_profile": system.sessions.get(session_id, {}).get("profile") if session_id else None,
        }
    except Exception as e:
        return {"total": 0, "correct": 0, "score": 0, "results": [],
                "ai_analysis": f"批改出错：{str(e)[:200]}"}

@app.post("/api/render-video")
async def render_video(request: Request):
    """渲染 Manim 代码为 MP4 视频"""
    body = await request.json()
    code = body.get("code", "")
    topic = body.get("topic", "animation")
    if not code or not ("from manim" in code or "import manim" in code):
        return {"error": "Manim 代码格式无效，需要包含 'from manim import ...'"}

    import subprocess, tempfile, shutil, glob as glob_m, re as re_m
    proj_root = os.path.dirname(os.path.abspath(__file__))

    # 找 FFmpeg
    ffmpeg_exe = None
    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        if not os.path.exists(ffmpeg_exe):
            ffmpeg_exe = None
    except Exception:
        pass

    if not ffmpeg_exe:
        # 最后尝试从 PATH 找
        ffmpeg_exe = shutil.which("ffmpeg")
    if not ffmpeg_exe:
        return {"error": "未找到 FFmpeg。请运行: pip install imageio-ffmpeg"}

    ffmpeg_dir = os.path.dirname(ffmpeg_exe)

    tmp_dir = tempfile.mkdtemp()
    try:
        scene_name = "TopicScene"
        match = re_m.search(r'class\s+(\w+)\s*\(\s*Scene\s*\)', code)
        if match:
            scene_name = match.group(1)

        py_file = os.path.join(tmp_dir, f"{scene_name}.py")
        with open(py_file, "w", encoding="utf-8") as f:
            f.write(code)

        try:
            compile(code, py_file, 'exec')
        except SyntaxError as e:
            return {"error": f"Manim 代码语法错误: {str(e)}"}

        # 环境变量：把 FFmpeg 目录加到 PATH 最前面
        env = os.environ.copy()
        env["PATH"] = ffmpeg_dir + os.pathsep + env.get("PATH", "")

        # 写 manim.cfg 指定 ffmpeg 路径
        cfg_path = os.path.join(tmp_dir, "manim.cfg")
        with open(cfg_path, "w") as f:
            f.write(f"[CLI]\nffmpeg_executable = {ffmpeg_exe}\n")

        try:
            result = subprocess.run(
                [sys.executable, "-m", "manim", "--config_file", cfg_path,
                 "-ql", "--format=mp4", py_file, scene_name],
                cwd=tmp_dir, capture_output=True, text=True, timeout=300, env=env
            )
        except subprocess.TimeoutExpired:
            return {"error": "渲染超时（超过5分钟），脚本可能过于复杂，请简化后重试"}

        if result.returncode != 0:
            err = (result.stderr or result.stdout or "")[-500:]
            return {"error": f"渲染失败: {err}"}

        mp4s = glob_m.glob(os.path.join(tmp_dir, "media", "videos", "**", "*.mp4"), recursive=True)
        if not mp4s:
            return {"error": "未生成视频文件。Manim 可能因缺少系统依赖而失败，请检查环境"}

        src = mp4s[0]
        size = os.path.getsize(src)
        if size < 5000:
            return {"error": f"视频文件过小({size}B)。可能是FFmpeg未正确配置，请运行: pip install imageio-ffmpeg"}

        outd = os.path.join(proj_root, "output")
        os.makedirs(outd, exist_ok=True)
        safe_name = re_m.sub(r'[^\w一-鿿]', '_', topic)[:30]
        dest = os.path.join(outd, f"{safe_name}.mp4")
        with open(src, 'rb') as fin:
            mp4_data = fin.read()
        with open(dest, 'wb') as fout:
            fout.write(mp4_data)

        return FileResponse(dest, filename=f"{safe_name}.mp4", media_type="video/mp4")

    except Exception as e:
        return {"error": f"渲染异常: {str(e)[:300]}"}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

@app.get("/api/reset")
async def reset(session_id: str = Query("")):
    """重置会话"""
    if session_id and session_id in system.sessions:
        del system.sessions[session_id]
    return {"status": "ok"}

@app.get("/api/kb/docs")
async def list_kb_docs():
    """列出知识库中的课程文档（不含正文，正文按需加载）"""
    from config import KB_SOURCE_DIR
    import re as _re
    docs = []
    if os.path.isdir(KB_SOURCE_DIR):
        raw_files = [f for f in os.listdir(KB_SOURCE_DIR) if f.endswith(('.txt', '.md'))]
        # 按章节号排序：提取文件名中的数字，1,2,3...10,11,12...
        def _sort_key(fname: str):
            m = _re.search(r'(\d+)', fname)
            if m:
                return int(m.group(1))
            return 999  # 附录排最后
        raw_files.sort(key=_sort_key)
        for fname in raw_files:
            if fname.endswith(('.txt', '.md')):
                fpath = os.path.join(KB_SOURCE_DIR, fname)
                with open(fpath, 'r', encoding='utf-8') as f:
                    content = f.read()
                display = fname.replace('.txt', '').replace('.md', '').replace('_', ' ')
                # 预览去掉反斜杠（LaTeX公式）避免JSON编码问题
                preview = content[:300].replace('\\', '/')
                docs.append({
                    "title": display,
                    "filename": fname,
                    "size_chars": len(content),
                    "line_count": content.count('\n') + 1,
                    "preview": preview,
                    "source": "课程数据文件",
                })
    return {"docs": docs, "total": len(docs)}

@app.get("/api/kb/doc/{filename}")
async def get_kb_doc(filename: str):
    """按文件名获取单篇文档完整内容（纯文本）"""
    from config import KB_SOURCE_DIR
    if ".." in filename or "/" in filename or "\\" in filename:
        return Response(content="非法路径", media_type="text/plain; charset=utf-8", status_code=403)
    fpath = os.path.join(KB_SOURCE_DIR, filename)
    if not os.path.exists(fpath) or not fpath.endswith(('.txt', '.md')):
        return Response(content="文件不存在", media_type="text/plain; charset=utf-8", status_code=404)
    with open(fpath, 'r', encoding='utf-8') as f:
        content = f.read()
    return Response(content=content, media_type="text/plain; charset=utf-8")

@app.post("/api/kb/import")
async def import_kb_docs():
    """从 course_data 文件真正导入到向量库"""
    try:
        from rag.engine import build_knowledge_base
        col = build_knowledge_base()
        count = col.count() if col else 0
        return {"status": "ok", "message": f"知识库已重建，共 {count} 个向量片段"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/")
async def index():
    """前端入口"""
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "index.html")
    if os.path.exists(html_path):
        return HTMLResponse(open(html_path, encoding="utf-8").read())
    return HTMLResponse("<h1>static/index.html not found</h1>")

# 模型配置 API

@app.get("/api/models")
async def list_models():
    """模型配置状态：预设服务商 + 已配置的 + 当前激活的"""
    return llm_manager.get_state()

@app.post("/api/models/test")
async def test_model(request: Request):
    """测试连接：真实调一次上游接口，成功顺便返回模型列表"""
    body = await request.json()
    result = await asyncio.to_thread(
        llm_manager.test_connection,
        body.get("service", ""), body.get("api_key", ""), body.get("base_url", ""),
        body.get("api_format", ""))
    info(f"测试连接 {body.get('service')}: {'成功' if result.get('ok') else result.get('error', '')[:60]}", "models")
    return result

@app.post("/api/models/save")
async def save_model(request: Request):
    """保存服务商配置（密钥单独存 secrets.json）"""
    body = await request.json()
    r = llm_manager.save_service(
        body.get("service", ""), body.get("api_key", ""),
        body.get("base_url", ""), body.get("model", ""), body.get("api_format", ""))
    if r.get("ok"):
        info(f"保存模型配置: {body.get('service')} / {body.get('model')}", "models")
    return r

@app.post("/api/models/activate")
async def activate_model(request: Request):
    """切换当前使用的模型，立即生效不用重启"""
    body = await request.json()
    r = llm_manager.set_active(body.get("service", ""), body.get("model", ""))
    if r.get("ok"):
        info(f"切换模型: {body.get('service')} / {body.get('model')}", "models")
    return r

@app.delete("/api/models/{service}")
async def delete_model(service: str):
    info(f"删除模型配置: {service}", "models")
    return llm_manager.delete_service(service)

# 教学模式（Skill）API

@app.get("/api/skills")
async def list_skills():
    return {"skills": skill_manager.list_skills()}

@app.post("/api/skills")
async def save_skill(request: Request):
    body = await request.json()
    triggers = body.get("triggers", [])
    if isinstance(triggers, str):
        triggers = [t.strip() for t in triggers.replace("，", ",").split(",") if t.strip()]
    return skill_manager.save_skill(
        body.get("id", ""), body.get("name", ""), body.get("description", ""),
        triggers, body.get("body", ""))

@app.delete("/api/skills/{sid}")
async def delete_skill(sid: str):
    return skill_manager.delete_skill(sid)

# 画像 API

@app.get("/api/session/{sid}/history")
async def session_history(sid: str):
    """聊天记录：刷新/重开页面后前端用它恢复对话显示"""
    sess = system.sessions.get(sid) or {}
    return {"history": sess.get("conversation_history") or []}

@app.get("/api/profile")
async def get_profile(session_id: str = ""):
    """刷新页面后恢复画像/路径/资源"""
    sess = system.sessions.get(session_id) or {}
    return {
        "profile": sess.get("profile"),
        "learning_path": sess.get("learning_path"),
        "resources": sess.get("resources"),
        "resources_history": sess.get("resources_history") or [],
        "phase": sess.get("phase"),
    }

@app.post("/api/profile")
async def update_profile(request: Request):
    """手动修正画像（AI判断错了用户自己改）"""
    body = await request.json()
    session_id = body.get("session_id", "")
    if session_id not in system.sessions:
        return {"ok": False, "error": "会话不存在，先去聊两句"}
    sess = system.sessions[session_id]
    profile = sess.get("profile") or {}
    fd = profile.setdefault("knowledge_foundation", {})

    # 三项评分（0.15-0.9）
    for key, sub in (("ml", "ml_prerequisites"), ("prog", "programming"), ("math", "math")):
        v = body.get(key)
        if v is not None:
            try:
                fd[sub] = round(min(max(float(v), 0.15), 0.9), 2)
            except (ValueError, TypeError):
                pass
    # 文本项
    for key, field in (("goal", "short_term_goal"), ("style", "cognitive_style"),
                       ("time", "time_per_week"), ("lang", "language_style")):
        v = (body.get(key) or "").strip()
        if v:
            profile[field] = v[:50]

    avg = (fd.get("ml_prerequisites", 0.4) + fd.get("programming", 0.4) + fd.get("math", 0.4)) / 3
    profile["difficulty_level"] = "入门" if avg < 0.35 else ("中级" if avg < 0.65 else "进阶")
    profile["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    sess["profile"] = profile
    try:
        system._save_sessions()
    except Exception:
        pass
    info(f"画像手动修正 (会话{session_id[:12]})", "profile")
    return {"ok": True, "profile": profile}

# 错题本 API

@app.get("/api/mistakes")
async def get_mistakes(session_id: str = ""):
    from utils import mistake_book
    return {"mistakes": mistake_book.list_mistakes(session_id)}

@app.post("/api/mistakes/review-quiz")
async def review_quiz(request: Request):
    """根据错题生成一份复习卷（变式题，不出原题）"""
    from utils import mistake_book
    body = await request.json()
    session_id = body.get("session_id", "")
    mistakes = mistake_book.list_mistakes(session_id)
    if not mistakes:
        return {"ok": False, "error": "错题本是空的，先去做几道练习题吧"}

    def _gen():
        from rag.engine import retrieve_knowledge
        # 拿最常错的知识点做检索
        kps = [m.get("knowledge_point") or m.get("topic", "") for m in mistakes[-10:]]
        kps = [k for k in kps if k]
        query = "、".join(dict.fromkeys(kps))[:100] or "机器学习"
        rag = retrieve_knowledge(query, k=4)
        prompt = mistake_book.build_review_prompt(mistakes, rag)
        raw = system.resource_agent._call_llm(prompt, temperature=0.4, max_tokens=2500)
        from utils.parser import extract_json
        import json as _json
        try:
            return _json.loads(extract_json(raw))
        except Exception as e:
            error(f"复习卷解析失败: {str(e)[:80]} | 返回开头: {(raw or 'None')[:100]}", "mistakes")
            return []

    exercises = await asyncio.to_thread(_gen)
    if not exercises:
        return {"ok": False, "error": "复习卷生成失败，请稍后再试"}
    info(f"复习卷生成: {len(exercises)}题 (会话{session_id[:12]})", "mistakes")
    return {"ok": True, "exercises": exercises}

# 知识图谱 API

@app.get("/api/kb/graph")
async def kb_graph():
    """章节依赖图数据，前端用 Mermaid 渲染"""
    from utils.knowledge_graph import get_knowledge_graph
    return get_knowledge_graph().export_graph_data()

@app.post("/api/kb/upload")
async def kb_upload(request: Request):
    """上传自定义资料进知识库：落盘 course_data + 重建向量库"""
    from config import KB_SOURCE_DIR
    body = await request.json()
    title = (body.get("title") or "").strip()
    content = (body.get("content") or "").strip()
    if not title or len(content) < 30:
        return {"ok": False, "error": "标题不能为空，正文至少30个字"}
    # 文件名只留安全字符（isalnum 对中文也是 True）
    safe = "".join(c for c in title if c.isalnum() or c in "-_ ")[:40].strip()
    if not safe:
        return {"ok": False, "error": "标题不合法"}
    fpath = os.path.join(KB_SOURCE_DIR, f"{safe}.txt")
    if os.path.exists(fpath):
        return {"ok": False, "error": f"已存在同名文档「{safe}」，换个标题"}
    os.makedirs(KB_SOURCE_DIR, exist_ok=True)
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(content)
    info(f"知识库新增文档: {safe} ({len(content)}字)，开始重建向量库", "kb")

    def _rebuild():
        from rag.engine import build_knowledge_base
        col = build_knowledge_base()
        return col.count() if col else 0

    try:
        count = await asyncio.to_thread(_rebuild)
        return {"ok": True, "message": f"已入库，向量库共 {count} 个片段"}
    except Exception as e:
        return {"ok": False, "error": f"落盘成功但向量化失败: {str(e)[:150]}"}

# 每日一练 API

@app.get("/api/daily-quiz")
async def daily_quiz():
    import json as _json
    fp = os.path.join(PROJ_ROOT, "db", "daily_quiz.json")
    try:
        with open(fp, "r", encoding="utf-8") as f:
            return _json.load(f)
    except Exception:
        return {}

# 守护进程 API

@app.get("/api/daemon")
async def daemon_status():
    return daemon.status()

@app.post("/api/daemon/start")
async def daemon_start():
    return daemon.start(system)

@app.post("/api/daemon/stop")
async def daemon_stop():
    return daemon.stop()

# 项目设置 API

@app.get("/api/project-settings")
async def get_project_settings():
    return project_settings.get_settings()

@app.post("/api/project-settings")
async def save_project_settings(request: Request):
    body = await request.json()
    return project_settings.save_settings(body)

@app.get("/api/logs")
async def get_logs(level: str = None, source: str = None, n: int = 100):
    """获取系统日志，支持级别和来源过滤"""
    return {
        "stats": get_stats(),
        "sources": get_sources(),
        "logs": get_recent(n, level, source),
    }

@app.get("/api/env-check")
async def env_check(deep: bool = False):
    """环境体检清单，deep=true 时额外做 LLM 连通性真实测试"""
    import sys, platform, shutil
    checks = []

    def add(key, label, ok, detail):
        checks.append({"key": key, "label": label, "ok": bool(ok), "detail": str(detail)})

    # Python 版本和解释器路径
    v = sys.version_info
    add("python", "Python 版本", v >= (3, 10), f"Python {v.major}.{v.minor}.{v.micro}")

    # conda 环境识别：环境变量可能是继承来的不准，优先对比 CONDA_PREFIX 和实际解释器路径
    in_conda = os.path.exists(os.path.join(sys.prefix, "conda-meta"))
    if in_conda:
        if os.path.normcase(os.environ.get("CONDA_PREFIX", "")) == os.path.normcase(sys.prefix):
            env_name = os.environ.get("CONDA_DEFAULT_ENV", "") or os.path.basename(sys.prefix)
        else:
            env_name = os.path.basename(sys.prefix)
        env_desc = f"conda 环境「{env_name}」({sys.prefix})"
    else:
        env_desc = f"非 conda ({sys.prefix})"
    add("conda", "运行环境", True, env_desc)

    # 核心依赖
    dep_names = {"fastapi": "fastapi", "openai": "openai", "chromadb": "chromadb",
                 "sentence_transformers": "sentence-transformers", "networkx": "networkx", "pptx": "python-pptx"}
    missing = []
    for mod, pip_name in dep_names.items():
        try:
            __import__(mod)
        except ImportError:
            missing.append(pip_name)
    add("deps", "核心依赖", not missing, "全部已安装" if not missing else f"缺少: {', '.join(missing)}")

    # Embedding 模型缓存
    hf_cache = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")
    emb_cached = os.path.isdir(hf_cache) and any(
        f.startswith("models--BAAI--bge-small-zh") for f in os.listdir(hf_cache))
    add("embedding", "Embedding 模型", emb_cached, "已下载缓存" if emb_cached else "未下载（首次运行会自动下载）")

    # 知识库
    kb_ok = is_kb_ready()
    add("kb", "知识库", kb_ok, f"共 {len(get_available_topics())} 章" if kb_ok else "未构建，请运行 install.py")

    # 模型配置
    state = llm_manager.get_state()
    active = state["active"]
    svc_cfg = next((s for s in state["services"] if s["id"] == active["service"]), None)
    key_ok = bool(svc_cfg and (svc_cfg["has_key"] or svc_cfg["no_key"]))
    add("model_cfg", "模型配置", key_ok,
        f"{active['service']} / {active.get('model', '')}" + ("" if key_ok else "（未配置密钥）"))

    # LLM 真实连通（比较慢，前端点"深度检测"才做）
    if deep:
        r = await asyncio.to_thread(llm_manager.test_connection, active["service"])
        add("llm_conn", "模型接口连通", r.get("ok"), "连接成功" if r.get("ok") else r.get("error", "失败"))

    # 磁盘空间
    try:
        free_gb = shutil.disk_usage(PROJ_ROOT).free / (1024**3)
        add("disk", "磁盘空间", free_gb >= 1, f"剩余 {free_gb:.1f} GB")
    except Exception:
        pass

    # 系统信息
    add("system", "操作系统", True, f"{platform.system()} {platform.release()}")

    return {
        "status": "ok",
        "all_ok": all(c["ok"] for c in checks),
        "checks": checks,
    }

def _sse_event(event_type: str, data: str) -> str:
    """构建SSE事件 —— JSON的话直接放在一行"""
    return f"event: {event_type}\ndata: {data}\n\n"

if __name__ == "__main__":
    from utils.logger import info as log_info
    print(f"Starting AI Learning Assistant Server...")
    print(f"Provider: {LLM_PROVIDER} | KB: {is_kb_ready()}")
    print(f"Open http://localhost:8000")
    log_info("服务启动", "server")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
