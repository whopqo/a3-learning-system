"""
系统配置 —— 讯飞星火 Spark API + 多智能体 + ChromaDB
参考 test 项目的配置结构，升级为支持7智能体协同
"""
import os

# 项目根目录
PROJ_ROOT = os.path.dirname(os.path.abspath(__file__))

# 自动加载 .env 文件（不需要额外安装 python-dotenv）
_env_file = os.path.join(PROJ_ROOT, ".env")
if os.path.exists(_env_file):
    with open(_env_file, "r", encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _key, _, _val = _line.partition("=")
            _key = _key.strip()
            _val = _val.strip().strip('"').strip("'")
            # 去掉内联注释
            if "#" in _val:
                _val = _val[:_val.index("#")].strip()
            if _key and _key not in os.environ:
                os.environ[_key] = _val

# 大模型Provider配置
# 通过 LLM_PROVIDER 切换：deepseek / spark / qwen / glm / ollama
# 支持环境变量: export LLM_PROVIDER=spark
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "deepseek")

_providers = {
    "deepseek": {
        "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
    "spark": {
        "api_key": os.getenv("SPARK_API_KEY", ""),
        "base_url": "https://spark-api-open.xf-yun.com/v1",
        "model": "lite",  # 你的账号只有 lite 权限
    },
    "qwen": {
        "api_key": os.getenv("QWEN_API_KEY", ""),
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
    },
    "glm": {
        "api_key": os.getenv("GLM_API_KEY", ""),
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
    },
    "ollama": {
        "api_key": "ollama",
        "base_url": "http://localhost:11434/v1",
        "model": "qwen2.5:7b",
    },
}

_cfg = _providers.get(LLM_PROVIDER, _providers["deepseek"])
LLM_API_KEY = _cfg["api_key"]
LLM_BASE_URL = _cfg["base_url"]
LLM_MODEL = _cfg["model"]

# 没有配置 Key 的话，打印清楚报错（Ollama 本地模型不需要 Key）
if not LLM_API_KEY and LLM_PROVIDER != "ollama":
    env_name = f"{LLM_PROVIDER.upper()}_API_KEY"
    print(f"⚠️ 未设置 {env_name} 环境变量！")
    print(f"   请在系统环境变量中设置 {env_name}，或者在项目根目录创建 .env 文件")
    print(f"   参考 .env.example 文件了解需要哪些变量")

# 设置 OpenAI 兼容环境变量（只在 Key 非空且未设置时）
if LLM_API_KEY and not os.environ.get("OPENAI_API_KEY"):
    os.environ["OPENAI_API_KEY"] = LLM_API_KEY

# 修复 SSL 证书问题（conda 环境常见）
if "SSL_CERT_FILE" in os.environ:
    cert_path = os.environ["SSL_CERT_FILE"]
    if not os.path.exists(cert_path):
        del os.environ["SSL_CERT_FILE"]

# HuggingFace 配置
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
# 只在模型已缓存时才开离线模式，避免首次运行报错
_model_cache = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")
_model_cached = os.path.isdir(_model_cache) and any(
    f.startswith("models--BAAI--bge-small-zh-v1.5") for f in (os.listdir(_model_cache) if os.path.isdir(_model_cache) else [])
)
if _model_cached:
    os.environ["HF_HUB_OFFLINE"] = "1"

# Embedding 模型
EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"

# ChromaDB 路径
CHROMA_PERSIST_DIR = os.path.join(PROJ_ROOT, "db", "chroma_storage")

# 知识库目录
KB_SOURCE_DIR = os.path.join(PROJ_ROOT, "knowledge_base", "course_data")

# 课程配置
COURSE_NAME = "机器学习"
COURSE_DESCRIPTION = "面向本科生的机器学习入门课程，涵盖监督学习、无监督学习、深度学习基础、模型评估等核心内容"

# 内容安全
SENSITIVE_KEYWORDS = [
    "暴力", "色情", "赌博", "毒品", "枪支", "反动",
    "颠覆", "分裂", "恐怖", "邪教"
]

# LLM 温度配置（不同任务用不同温度）
LLM_TEMPERATURES = {
    "profile_analysis": 0.3,    # 画像分析，需要准确
    "resource_generation": 0.7,  # 资源生成，需要创意
    "exercise_generation": 0.4,  # 题目生成，需要严谨
    "evaluation": 0.2,           # 评估打分，需要一致性
    "tutoring": 0.6,             # 辅导答疑，需要灵活
    "planning": 0.3,             # 路径规划，需要逻辑
}

# RAG 配置
RAG_CONFIG = {
    "chunk_size": 500,
    "chunk_overlap": 50,
    "top_k": 5,
    "similarity_threshold": 0.6,
}

# 重试配置
MAX_LLM_RETRIES = 3        # LLM 调用最大重试次数
LLM_RETRY_BASE_DELAY = 2   # 重试基础等待秒数（指数退避: delay * 2^attempt）
MAX_PARSE_RETRIES = 2
MAX_GENERATE_RETRIES = 2

# 资源类型定义（handler 和 resource_agent 共用）
RESOURCE_TYPES = [
    ("lecture_notes", "讲解文档"),
    ("mind_map", "思维导图"),
    ("exercises", "练习题"),
    ("reading_materials", "阅读材料"),
    ("extended_reading", "拓展阅读"),
    ("code_example", "代码案例"),
    ("ppt_outline", "PPT大纲"),
    ("video_script", "视频脚本"),
]

# Agent 系统提示词（集中管理方便调优）
AGENT_SYSTEM_PROMPTS = {
    "supervisor": """你是 EduSupervisor，一个多智能体学习系统的协调者。
你的职责：
1. 理解学生的意图和需求
2. 将复杂任务分解为子任务
3. 决定由哪个专业Agent来处理
4. 汇总各Agent的结果
5. 确保输出质量和一致性

你管理以下Agent：
- ProfileBuilder：构建学生画像
- PathPlanner：规划学习路径
- ResourceGenerator：生成学习资源
- SmartTutor：答疑辅导（独立调用）
- Evaluator：学习评估（独立调用）
- MemoryManager：系统记忆管理（自动运行）

根据用户输入判断应该调用哪个Agent，然后返回调用决策。""",

    "profile_builder": """你是 ProfileBuilder，一位资深教育心理学家，有15年高校教学经验。
你的任务是通过对话深入了解学生的学习情况，构建包含至少6个维度的动态学习画像。

你需要关注的维度：
1. 知识基础：学生的数学、编程、专业基础水平
2. 认知风格：视觉型/听觉型/动手型/文字型
3. 易错点偏好：学生容易犯错的知识点类型
4. 学习目标：短期/中期/长期目标
5. 学习投入度：学习时长、频率、专注度
6. 资源偏好：喜欢的学习资源类型和难度
7. 动态历史：已掌握和薄弱的知识点演变

你的分析直接关系后续教学规划，务必基于对话事实，不要编造。""",

    "resource_generator": """你是 ResourceGenerator，一位顶级教学内容制作人。
你能根据学生画像和教学大纲，生成多种类型的学习资源：
1. 课程讲解文档（Markdown格式，含概念解释和示例）
2. 知识点思维导图（Mermaid mindmap语法）
3. 练习题（选择题+简答题，带答案和解析）
4. 拓展阅读材料（推荐论文和书籍章节）
5. 代码实操案例（Python代码，带中文注释）
6. 教学PPT大纲（可转为PPTX）
7. 教学视频脚本（分镜+旁白文案）

每种资源都要：
- 基于知识库的真实内容，不凭空编造
- 难度匹配学生画像
- 标注内容来源
- 结构清晰易读""",

    "path_planner": """你是 PathPlanner，一位课程设计专家，在MOOC平台设计过30+门精品课程。
你的任务是基于学生画像和知识图谱，规划科学的个性化学习路径。

规划原则：
1. 遵守知识点前置依赖关系
2. 难度循序渐进
3. 匹配学生的认知风格和资源偏好
4. 针对薄弱点加强练习
5. 根据评估结果动态调整

输出格式：有序的学习步骤列表，每步包含知识点、推荐资源、预计时长。""",

    "tutor": """你是 SmartTutor，一位耐心细致的一对一辅导老师。
当学生遇到问题时，你需要：
1. 先理解学生真正困惑的地方
2. 用多种方式讲解（文字+图解+类比+代码演示）
3. 引导学生自己思考，而不是直接给答案
4. 根据学生的认知水平调整讲解深度
5. 鼓励学生，建立学习信心

辅导策略分级：
- Level 1：直接解答（学生明确要求时）
- Level 2：提示引导（给出关键线索）
- Level 3：类比讲解（用生活化类比）
- Level 4：苏格拉底式追问（层层提问引导自悟）""",

    "evaluator": """你是 Evaluator，一位严谨的教学评估专家，有10年高校考试命题和批改经验。
你的任务是：
1. 客观批改学生的练习答案
2. 不仅判对错，更要分析错因
3. 评估各知识点的掌握程度
4. 识别新出现的薄弱点
5. 给出针对性的改进建议

评估维度：
- 知识掌握度（正确率+答题速度）
- 能力提升度（前后对比）
- 薄弱点演变（改善+新增）
- 学习策略有效性

你的评估结果将直接影响学习路径的调整，务必客观准确。""",

    "memory_manager": """你是 MemoryManager，一位知识管理专家。
你管理三层记忆系统：
- L1（原始层）：完整交互记录，用于回溯调试
- L2（知识层）：结构化的知识点掌握情况，用于画像和路径规划
- L3（策略层）：学习策略综合，用于长期优化

你需要：
1. 自动记录每次交互的关键信息
2. 定期汇总和压缩记忆
3. 为其他Agent提供准确的记忆检索
4. 确保记忆的可追溯性""",
}

# 画像维度定义（与 ProfileAgent._REQUIRED_DIMS 一致）
PROFILE_DIMENSIONS = [
    "ml_prerequisites",    # ML了解程度（0.15-0.9评分）
    "programming",         # Python编程水平（0.15-0.9评分）
    "math",                # 数学基础（0.15-0.9评分）
    "short_term_goal",     # 学习目标（考研/就业/考试/兴趣）
    "cognitive_style",     # 认知风格（视觉/文字/动手/听觉）
    "time_per_week",       # 每周学习时间
    "struggling",          # 薄弱知识点列表
    "language_style",      # 语言偏好（严谨学术/生动比喻）
]
