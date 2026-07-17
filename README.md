# EduSynth · AI 个性化学习助手

> **第十五届中国软件杯大赛 · A组赛题** | 出题企业：科大讯飞股份有限公司

基于大模型的多智能体学习系统：7 个专业 Agent 通过有向图协同，画像→路径→资源→答疑→评估→复盘形成教学闭环。

---

## 快速开始

```bash
pip install -r requirements.txt
python knowledge_base/build_kb.py
python run.py                     # ↑ 首次需联网下载模型，等几分钟
```
浏览器自动打开 → 设置 → 模型配置 → 填密钥 → 开始使用

Python ≥ 3.10，推荐用 conda。Key 写在项目根目录 `.env` 文件里（参考 `.env.example`），**不会被提交到 GitHub**。

---

## 功能一览

| 功能 | 说明 |
|---|---|
| 对话式画像 | 8 维动态画像，快速开始按钮一轮建好，支持手动修正 + 判断溯源 |
| 多智能体资源生成 | 8 种资源（讲义/思维导图/练习题/阅读材料/拓展阅读/代码/PPT/视频脚本），引文溯源 |
| 学习路径规划 | 基于 NetworkX 章节依赖图 + LLM 阶段式计划 |
| 智能答疑 | L1-L4 分级辅导 + Mermaid 图解 |
| 学习评估 | 关键词快判 + LLM 深度分析，掌握度地图 + 遗忘曲线 |
| 模型配置 | 10 家服务商热切换（OpenAI/Anthropic 双协议），UI 一键测试连接 |
| 教学模式 | SKILL.md 自定义教学规则，手动勾选/关键词自动触发 |
| 错题本 + 每日一练 | 错题自动归档，复习卷变式出题；守护进程每天自动出针对性练习 |
| 环境检测 + 系统日志 | 一键体检（conda/依赖/API/磁盘绿勾红叉），日志按天落盘 |

---

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | HTML5 + 原生 JS（ECharts 图表 + Markmap 思维导图 + Mermaid 流程图） |
| 后端 | FastAPI + Uvicorn（REST + SSE 流式） |
| 多智能体 | 自研 AgentGraph 有向图引擎 |
| LLM | 10 家服务商可切换（DeepSeek/星火/千问/智谱/Kimi/Claude/硅基流动/OpenRouter/Ollama/自定义） |
| 向量库 | ChromaDB + BAAI/bge-small-zh-v1.5 |
| 知识图谱 | NetworkX 章节依赖 DAG |
| PPT | python-pptx |
| 协议适配 | 自研 Anthropic 翻译器 |

---

## 目录

```
a3-learning-system/
├── run.py / install.py / server.py / handler.py / config.py
├── requirements.txt / .env.example
├── static/                  前端（index.html + style.css + app.js）
├── agents/                  7 个 Agent + graph.py 协同引擎
├── rag/engine.py            RAG 检索引擎
├── utils/                   10 个工具模块
├── skills/                  教学模式 SKILL.md 文件
├── knowledge_base/          教材数据 + 构建脚本
├── db/                      运行时数据（不进 Git）
├── docs/                    全部文档（项目说明+简历叙述+赛题存档）
└── output/                  PPT/视频导出
```

---

## 文档说明

所有文档都在 `docs/` 文件夹：

- `docs/项目说明.md`：**完整手册**（每个文件的用途、运行步骤、常见问题、功能对照，随代码持续更新）← 看这个
- `docs/技术架构与实现逻辑.txt`：简历用技术叙述
- `docs/赛题原始存档/`：比赛提交的原始文档（系统开发说明书、测试说明书），仅存档不再更新

---

> 文档版本：v4.7 | 日期：2026-07-17
>
> 详细说明请查看 `docs/项目说明.md`
