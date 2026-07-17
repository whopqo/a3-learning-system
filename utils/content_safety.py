"""
内容安全检查 —— 三层防御体系中的输入层和输出层过滤
"""
import re
from config import SENSITIVE_KEYWORDS


def check_content_safety(text: str) -> tuple[bool, str]:
    """
    检查内容是否安全
    返回 (是否安全, 原因)
    """
    if not text or not isinstance(text, str):
        return False, "输入为空"

    # 课程术语白名单：强化学习的"K-摇臂赌博机"是正经概念，先剥掉再查敏感词
    check_text = text
    for term in ["赌博机", "老虎机"]:
        check_text = check_text.replace(term, "")

    text_lower = text.lower()

    # 1. 敏感词检测
    for kw in SENSITIVE_KEYWORDS:
        if kw in check_text:
            return False, f"包含敏感词：{kw}"

    # 2. 注入攻击检测（简单版）
    injection_patterns = [
        r"ignore\s+(all\s+)?(previous|above)\s+(instructions?|prompts?)",
        r"system\s*:\s*you\s+are\s+now",
        r"<\|im_start\|>",
        r"<\|im_end\|>",
        r"\[INST\].*\[/INST\]",
    ]
    for pattern in injection_patterns:
        if re.search(pattern, text_lower):
            return False, "检测到潜在的注入攻击"

    return True, "ok"


def filter_sensitive(text: str) -> str:
    """过滤敏感内容，替换为***"""
    result = text
    for kw in SENSITIVE_KEYWORDS:
        result = result.replace(kw, "***")
    return result


def is_learning_related(text: str) -> bool:
    """判断是否与学习相关（简单的范围校验）"""
    learning_keywords = [
        "学习", "课程", "知识", "题", "练习", "考试", "作业",
        "编程", "代码", "算法", "数学", "计算", "数据", "模型",
        "训练", "分类", "回归", "聚类", "神经网络", "深度",
        "learn", "study", "course", "python", "code",
        "什么是", "如何", "怎么", "为什么", "解释", "讲解",
        "帮我", "生成", "推荐", "规划", "评估", "分析",
        "决策树", "SVM", "CNN", "RNN", "NLP", "CV",
    ]
    text_lower = text.lower()
    for kw in learning_keywords:
        if kw.lower() in text_lower:
            return True
    return False


def check_citation_integrity(generated_text: str, source_texts: list[str]) -> dict:
    """
    检查生成内容与知识库原文的一致性（简单的NLI模拟）
    返回 {'consistent': bool, 'hallucination_risk': float, 'unverified_claims': list}
    """
    # 提取生成文本中的关键论断
    claims = re.findall(r'[^。！？\n]+(?:。|！|？)', generated_text)

    unverified = []
    for claim in claims[:10]:  # 最多检查10条
        claim = claim.strip()
        if len(claim) < 10:
            continue

        # 检查是否有引用标记
        has_citation = bool(re.search(r'\[来源[：:]\s*\d+\]|\[引用\]|\[参考\]', claim))

        # 检查是否能在原文中找到相似内容
        found = False
        for source in source_texts:
            # 简单的关键词重叠检测
            claim_words = set(claim)
            source_words = set(source)
            if len(claim_words) < 5:
                continue
            overlap = len(claim_words & source_words) / len(claim_words)
            if overlap > 0.3:
                found = True
                break

        if not found and not has_citation:
            unverified.append(claim)

    risk = len(unverified) / max(len(claims), 1)
    return {
        "consistent": risk < 0.3,
        "hallucination_risk": round(risk, 2),
        "unverified_claims": unverified[:5],
    }
