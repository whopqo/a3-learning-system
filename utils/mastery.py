"""
知识点掌握度模型 —— 每个知识点一个 0-1 分数持续演化（参考 DKVMN/DeepTutor 思路）
带遗忘衰减：掌握度随时间下降，复习次数越多越"稳"（简化版 SM-2/艾宾浩斯）
数据存 profile["mastery_map"] = {知识点: {"score":0-1, "updated":时间, "attempts":次数}}
"""
import math
import time

# 稳定性基数：刚学会的知识约两周衰减到 e 分之一，每多练一次稳定期 +7 天
_BASE_STABILITY = 14.0
_STABILITY_PER_ATTEMPT = 7.0
_MASTERED_LINE = 0.7   # 有效分 ≥ 0.7 算掌握
_WEAK_LINE = 0.4       # 有效分 < 0.4 算薄弱
_REVIEW_LINE = 0.55    # 学过但衰减到这条线以下 → 该复习了


def update_kp(profile: dict, kp: str, new_score: float):
    """评估后更新一个知识点的掌握度：新成绩占 70%，历史占 30%"""
    if not kp:
        return
    mm = profile.setdefault("mastery_map", {})
    entry = mm.get(kp) or {"score": 0.4, "attempts": 0}
    old = float(entry.get("score", 0.4))
    entry["score"] = round(0.7 * min(max(new_score, 0.0), 1.0) + 0.3 * old, 3)
    entry["attempts"] = int(entry.get("attempts", 0)) + 1
    entry["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    mm[kp] = entry


def effective_score(entry: dict) -> float:
    """带遗忘衰减的有效掌握度：score * e^(-经过天数/稳定期)"""
    score = float(entry.get("score", 0.4))
    try:
        t0 = time.mktime(time.strptime(entry.get("updated", ""), "%Y-%m-%d %H:%M:%S"))
        days = max(0.0, (time.time() - t0) / 86400)
    except Exception:
        days = 0.0
    stability = _BASE_STABILITY + _STABILITY_PER_ATTEMPT * int(entry.get("attempts", 0))
    return round(score * math.exp(-days / stability), 3)


def get_effective_map(profile: dict) -> dict:
    """{知识点: 衰减后的有效分}"""
    return {kp: effective_score(e) for kp, e in (profile.get("mastery_map") or {}).items()}


def sync_lists(profile: dict):
    """从掌握度地图派生 mastered/struggling 名单（保留没进过地图的手动条目）"""
    eff = get_effective_map(profile)
    mastered = [m for m in profile.get("mastered_topics", []) if m not in eff]
    struggling = [s for s in profile.get("struggling_topics", []) if s not in eff]
    for kp, score in eff.items():
        if score >= _MASTERED_LINE:
            mastered.append(kp)
        elif score < _WEAK_LINE:
            struggling.append(kp)
    profile["mastered_topics"] = mastered
    profile["struggling_topics"] = struggling


def due_for_review(profile: dict, limit: int = 5) -> list:
    """学过（原始分≥0.6）但衰减到临界线以下的知识点，按有效分从低到高——最该复习的排前面"""
    due = []
    for kp, entry in (profile.get("mastery_map") or {}).items():
        if float(entry.get("score", 0)) >= 0.6:
            eff = effective_score(entry)
            if eff < _REVIEW_LINE:
                due.append((eff, kp))
    due.sort()
    return [kp for _, kp in due[:limit]]
