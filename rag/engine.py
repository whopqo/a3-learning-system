"""
RAG 检索引擎 —— ChromaDB + SentenceTransformer
五步管道：文档摄取→分段→向量化→检索→重排序
支持离线模式（模型已缓存时无需联网）
"""
import os
import chromadb
from chromadb.api.types import EmbeddingFunction, Embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from config import EMBEDDING_MODEL, CHROMA_PERSIST_DIR, KB_SOURCE_DIR, RAG_CONFIG

COLLECTION_NAME = "course_knowledge"

_client = None
_collection = None
_ef = None

class LocalEmbeddingFunction(EmbeddingFunction):
    """自定义Embedding函数 —— 支持离线加载 + 强制CPU"""

    def __init__(self, model_name: str, device: str = "cpu"):
        self.model_name = model_name
        self.device = device
        self._model = None

    def _load_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            # 优先用本地文件，避免联网
            self._model = SentenceTransformer(
                self.model_name,
                device=self.device,
                local_files_only=True,
            )
        return self._model

    def __call__(self, input: list[str]) -> Embeddings:
        model = self._load_model()
        embeddings = model.encode(
            input,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return embeddings.tolist()

def _get_ef():
    """获取或创建 EmbeddingFunction 单例"""
    global _ef
    if _ef is None:
        _ef = LocalEmbeddingFunction(EMBEDDING_MODEL, device="cpu")
    return _ef

def _get_collection():
    """懒加载 chromadb collection，自动处理重建后的 UUID 变化"""
    global _client, _collection
    if _collection is not None:
        try:
            # 验证 collection 是否仍然有效（重建后 UUID 会变）
            _collection.count()
            return _collection
        except Exception:
            _collection = None
            _client = None

    os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)
    _client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
    ef = _get_ef()
    try:
        _collection = _client.get_collection(COLLECTION_NAME, embedding_function=ef)
    except Exception:
        _collection = None
    return _collection

def build_knowledge_base(source_dir: str = None):
    """构建知识库：读取 txt/md → 切块 → 向量化 → 存 ChromaDB"""
    global _client, _collection, _ef

    if source_dir is None:
        source_dir = KB_SOURCE_DIR

    if not os.path.isdir(source_dir):
        raise FileNotFoundError(f"知识库源目录不存在：{source_dir}")

    files = sorted([
        f for f in os.listdir(source_dir)
        if f.endswith(".txt") or f.endswith(".md")
    ])
    if not files:
        raise FileNotFoundError(f"{source_dir} 中没有 .txt / .md 文件")

    os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)
    _client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
    _ef = _get_ef()

    # 删旧建新
    try:
        _client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass

    _collection = _client.create_collection(COLLECTION_NAME, embedding_function=_ef,
                                            metadata={"hnsw:space": "cosine"})

    chunk_size = RAG_CONFIG.get("chunk_size", 500)
    chunk_overlap = RAG_CONFIG.get("chunk_overlap", 50)
    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    for fname in files:
        fpath = os.path.join(source_dir, fname)
        with open(fpath, "r", encoding="utf-8") as f:
            text = f.read()

        source_label = fname.replace(".txt", "").replace(".md", "")
        chunks = splitter.split_text(text)

        if not chunks:
            continue

        ids = [f"{source_label}_chunk{i}" for i in range(len(chunks))]
        metadatas = [{"source": source_label, "chunk_index": i, "file": fname} for i in range(len(chunks))]

        _collection.add(documents=chunks, metadatas=metadatas, ids=ids)
        print(f"  已入库: {source_label} ({len(chunks)}个片段)")

    print(f"知识库构建完成，共 {_collection.count()} 个片段")
    return _collection

def get_vectordb():
    """获取向量数据库实例"""
    col = _get_collection()
    if col is None or col.count() == 0:
        raise RuntimeError("知识库未构建，请先运行 knowledge_base/build_kb.py")
    return col

def retrieve_knowledge(query: str, k: int = None) -> str:
    """检索知识库，返回带出处标注的结果"""
    if k is None:
        k = RAG_CONFIG.get("top_k", 5)

    col = get_vectordb()
    results = col.query(query_texts=[query], n_results=k)

    if not results or not results["documents"] or not results["documents"][0]:
        return "（未在知识库中找到相关内容）"

    lines = []
    docs = results["documents"][0]
    metas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(docs)
    distances = results.get("distances", [[0] * len(docs)])[0] if results.get("distances") else [0] * len(docs)

    for i, (doc, meta, dist) in enumerate(zip(docs, metas, distances), 1):
        source = meta.get("source", "未知来源") if meta else "未知来源"
        relevance = max(0, 1 - dist) if dist else 1.0
        lines.append(f"[片段{i}] (相关度: {relevance:.2f})\n{doc}\n  —— 来源：{source}")

    return "\n\n".join(lines)

def retrieve_context(query: str, k: int = None) -> list[dict]:
    """检索并返回结构化结果，供Agent使用"""
    if k is None:
        k = RAG_CONFIG.get("top_k", 5)

    col = get_vectordb()
    results = col.query(query_texts=[query], n_results=k)

    if not results or not results["documents"] or not results["documents"][0]:
        return []

    contexts = []
    docs = results["documents"][0]
    metas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(docs)
    distances = results.get("distances", [[0] * len(docs)])[0] if results.get("distances") else [0] * len(docs)

    for doc, meta, dist in zip(docs, metas, distances):
        contexts.append({
            "content": doc,
            "source": meta.get("source", "未知来源") if meta else "未知来源",
            "file": meta.get("file", ""),
            "relevance": round(max(0, 1 - dist), 3) if dist else 1.0,
        })

    return contexts

def is_kb_ready() -> bool:
    """检查知识库是否已构建"""
    try:
        col = _get_collection()
        return col is not None and col.count() > 0
    except Exception:
        return False

def check_topic_relevance(topic: str, threshold: float = 0.55) -> dict:
    """检查某个主题是否在知识库中有相关内容"""
    try:
        col = _get_collection()
        if not col or col.count() == 0:
            return {"relevant": False, "reason": "知识库未构建", "best_match": "", "score": 0}
        results = col.query(query_texts=[topic], n_results=3)
        if not results or not results["documents"] or not results["documents"][0]:
            return {"relevant": False, "reason": "未找到匹配内容", "best_match": "", "score": 0}
        distances = results.get("distances", [[99]])[0]
        # ChromaDB的distance越小越相关（cosine distance）
        best_score = 1 - min(distances) if distances else 0
        best_doc = results["documents"][0][0][:100] if results["documents"][0] else ""
        if best_score >= threshold:
            return {"relevant": True, "reason": "", "best_match": best_doc[:60], "score": round(best_score, 2)}
        else:
            return {"relevant": False, "reason": f"相关知识匹配度仅{best_score:.0%}", "best_match": best_doc[:60], "score": round(best_score, 2)}
    except Exception:
        return {"relevant": False, "reason": "检索异常", "best_match": "", "score": 0}

def get_available_topics() -> list[str]:
    """获取知识库中已有的课程主题（美化的名称）"""
    try:
        col = _get_collection()
        if not col: return []
        results = col.get()
        sources = set()
        for meta in (results.get("metadatas", []) or []):
            if meta and meta.get("source"):
                src = meta["source"]
                src = src.replace("_", " ").replace(".txt", "").replace(".md", "")
                sources.add(src)
        return sorted(sources)
    except:
        return ["机器学习课程"]

def topic_in_kb(topic: str, threshold: float = 0.45) -> bool:
    """简单判断：topic 在知识库中是否存在相关内容"""
    result = check_topic_relevance(topic, threshold)
    return result.get("relevant", False)

def message_in_kb_scope(message: str, threshold: float = 0.28) -> bool:
    """用向量语义判断一条消息是否在知识库领域内。

    跟关键词匹配不同，这里用真正的语义相似度：
    - "量子力学" → KB里没有量子力学内容 → 相似度低 → False
    - "决策树" → KB里有决策树章节 → 相似度高 → True
    - "今天天气怎么样" → KB里没有任何天气内容 → 相似度低 → False
    - "SVM的原理" → KB里有SVM章节 → 相似度高 → True

    threshold 设得比较宽松(0.28)，因为用户可能用各种表述方式。
    完全无关的消息相似度通常在 0.05-0.15 之间。
    """
    result = check_topic_relevance(message, threshold)
    return result.get("relevant", False)

def quick_kb_score(message: str) -> float:
    """快速获取消息与KB的最高相似度，不做阈值判断"""
    result = check_topic_relevance(message, threshold=-1.0)  # 永远返回
    return result.get("score", 0.0)

def extract_reading_materials(topic: str) -> str:
    """从知识库提取与topic相关的阅读材料——只取当前章节"""
    results = retrieve_context(topic, k=8)
    if not results:
        return ""
    import re
    chunks = []
    for r in results:
        content = r.get("content", "")
        source = r.get("source", "")
        if any(s in source for s in ["附录","后记","索引","致谢","前言"]):
            continue
        # 只看当前topic对应的章节（模糊匹配）
        t = topic.strip()
        s = source.strip()
        if not (t in s or s in t or any(w in s for w in t if len(w)>=2)):
            continue
        if not any(kw in content for kw in ["阅读材料","参考文献","经典教材",
                "Mitchell","Bishop","Hastie","周志华","李航","ICML","NeurIPS","Further Reading"]):
            continue
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if "阅读材料" in line and line.strip().startswith("###"):
                body_lines = []
                for j in range(i+1, min(i+15, len(lines))):
                    lj = lines[j].strip()
                    if lj.startswith("###"): break
                    if "课后习题" in lj or "休息一会儿" in lj: break
                    if lj: body_lines.append(lj)
                body = "\n".join(body_lines)
                if len(body) > 20:
                    chunks.append(body)
                break
    return "\n\n".join(chunks[:2]) if chunks else ""

def extract_stories() -> str:
    """从知识库提取休息一会儿小故事,清理章节标题和尾部序号"""
    try:
        col = _get_collection()
        if not col: return ""
        results = col.query(query_texts=["休息一会儿 小故事"], n_results=8)
        if not results or not results["documents"] or not results["documents"][0]:
            return ""
        import re
        stories = []
        for doc in results["documents"][0]:
            # 截断到正文结束(遇到课后习题/参考文献/全部课后)
            for sep in ["课后习题","全部课后","参考文献"]:
                idx = doc.find(sep)
                if idx > 0:
                    doc = doc[:idx]
            # 清理所有 ### X.Y 开头的标题行
            doc = re.sub(r'^###\s+\d+\.\d+\s+(休息一会儿\s+)?小故事[：:]*\s*', '', doc.strip(), flags=re.MULTILINE)
            # 清理所有残留的 ### X.Y 尾标
            doc = re.sub(r'\s*###\s+\d+\.\d+\s*', ' ', doc)
            doc = doc.strip()
            if len(doc) > 30:
                stories.append(doc)
        # 去重（用内容hash，不是前30字）
        import hashlib
        seen = set()
        unique = []
        for s in stories:
            key = hashlib.md5(s.encode()).hexdigest()
            if key not in seen:
                seen.add(key)
                unique.append(s)
        return "\n\n---\n\n".join(unique[:3]) if unique else ""
    except Exception:
        return ""

KB_ONLY_RULE = (
    "【重要约束】你必须严格基于上方「知识库参考」的内容来生成，不得凭空编造。\n"
    "如果知识库里没有相关内容，请如实说「知识库暂无此内容」，"
    "不要用你自己的知识去补充。\n"
    "所有关键概念和定义必须能在知识库原文中找到对应。"
)

