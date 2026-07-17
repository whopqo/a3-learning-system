"""
教学模式（Skill）管理 —— 参考 inkos 的 skill 设计
一个模式 = skills/<id>/SKILL.md 文件：头部是元数据（--- 包起来），正文是给 AI 的教学规则
生效方式：聊天时勾选，或者用户的话命中触发关键词自动启用，规则拼进系统提示词
"""
import os
import threading
from contextvars import ContextVar

from config import PROJ_ROOT
from utils import logger

SKILLS_DIR = os.path.join(PROJ_ROOT, "skills")

_lock = threading.Lock()
# 当前这次请求生效的规则文本，聊天处理开始时设置、结束时清掉
_active_rules: ContextVar = ContextVar("skill_rules", default="")


def _parse_skill_md(text: str, fallback_id: str) -> dict:
    """解析 SKILL.md：--- 之间是元数据(key: value)，之后是正文规则"""
    meta = {"id": fallback_id, "name": fallback_id, "description": "", "triggers": []}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            head, body = parts[1], parts[2]
            for line in head.splitlines():
                line = line.strip()
                if ":" not in line:
                    continue
                k, _, v = line.partition(":")
                k, v = k.strip(), v.strip()
                if k == "triggers":
                    v = v.strip("[]")
                    meta["triggers"] = [t.strip() for t in v.replace("，", ",").split(",") if t.strip()]
                elif k in ("id", "name", "description"):
                    meta[k] = v
    meta["body"] = body.strip()
    return meta


def list_skills() -> list:
    """扫描 skills/ 目录，坏文件跳过不崩溃"""
    skills = []
    if not os.path.isdir(SKILLS_DIR):
        return skills
    for d in sorted(os.listdir(SKILLS_DIR)):
        fp = os.path.join(SKILLS_DIR, d, "SKILL.md")
        if not os.path.isfile(fp):
            continue
        try:
            with open(fp, "r", encoding="utf-8") as f:
                sk = _parse_skill_md(f.read(), d)
            sk["id"] = d  # id 以目录名为准，别让文件里的骗了
            skills.append(sk)
        except Exception as e:
            logger.warn(f"教学模式 {d} 解析失败: {str(e)[:80]}", "skills")
    return skills


def save_skill(sid: str, name: str, description: str, triggers: list, body: str) -> dict:
    sid = "".join(c for c in sid.strip() if c.isalnum() or c in "-_")
    if not sid:
        return {"ok": False, "error": "模式 ID 只能用字母数字和中划线"}
    if not body.strip():
        return {"ok": False, "error": "规则内容不能为空"}
    text = "---\n"
    text += f"id: {sid}\nname: {name.strip() or sid}\ndescription: {description.strip()}\n"
    text += f"triggers: [{', '.join(t.strip() for t in triggers if t.strip())}]\n"
    text += "---\n\n" + body.strip() + "\n"
    with _lock:
        os.makedirs(os.path.join(SKILLS_DIR, sid), exist_ok=True)
        with open(os.path.join(SKILLS_DIR, sid, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(text)
    logger.info(f"教学模式已保存: {sid}", "skills")
    return {"ok": True}


def delete_skill(sid: str) -> dict:
    import shutil
    fp = os.path.join(SKILLS_DIR, sid)
    # 防止路径穿越删到别的目录
    if ".." in sid or "/" in sid or "\\" in sid or not os.path.isfile(os.path.join(fp, "SKILL.md")):
        return {"ok": False, "error": "模式不存在"}
    with _lock:
        shutil.rmtree(fp, ignore_errors=True)
    logger.info(f"教学模式已删除: {sid}", "skills")
    return {"ok": True}


def resolve(requested_ids: list, message: str) -> list:
    """决定这条消息用哪些模式：手动勾选的 > 关键词自动触发的（参考 inkos resolveSkills）"""
    all_skills = list_skills()
    by_id = {s["id"]: s for s in all_skills}
    used, used_ids = [], set()
    for rid in (requested_ids or []):
        if rid in by_id and rid not in used_ids:
            used.append(by_id[rid])
            used_ids.add(rid)
    low = (message or "").lower()
    for s in all_skills:
        if s["id"] in used_ids:
            continue
        if any(t.lower() in low for t in s.get("triggers", [])):
            used.append(s)
            used_ids.add(s["id"])
    return used


def set_active(skills: list):
    """把选中模式的规则合成一段文本，供 base_agent 拼系统提示词"""
    if not skills:
        _active_rules.set("")
        return
    parts = []
    for s in skills:
        parts.append(f"【教学模式：{s['name']}】\n{s['body']}")
    _active_rules.set("\n\n".join(parts))


def clear_active():
    _active_rules.set("")


def get_active_rules() -> str:
    return _active_rules.get()
