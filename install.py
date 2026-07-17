"""
一键安装脚本 —— 评审老师双击/右键运行即可
自动完成: Python版本检查 → pip安装依赖 → 下载嵌入模型 → 构建知识库
"""
import os, sys, subprocess

os.chdir(os.path.dirname(os.path.abspath(__file__)))
MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"


def step(title):
    print(f"\n{'='*50}")
    print(f"  {title}")
    print(f"{'='*50}")


# 1. Python 版本
step("1/5 Python 版本检查")
v = sys.version_info
print(f"  Python {v.major}.{v.minor}.{v.micro}")
if v < (3, 10):
    print("  需要 Python 3.10+")
    sys.exit(1)
print("  通过")

# 2. 安装核心依赖
step("2/5 安装核心依赖（约2-5分钟）")
ok = subprocess.run(
    f'"{sys.executable}" -m pip install -r requirements.txt -i {MIRROR}',
    shell=True
).returncode == 0
if not ok:
    subprocess.run(f'"{sys.executable}" -m pip install -r requirements.txt', shell=True)
print("  完成")

# 3. 预下载嵌入模型
step("3/5 预下载嵌入模型（约400MB，仅首次）")
try:
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("BAAI/bge-small-zh-v1.5", device="cpu")
    print(f"  模型就绪，向量维度: {model.get_sentence_embedding_dimension()}")
except Exception as e:
    print(f"  下载失败({e})，首次运行时会自动下载")

# 4. 构建知识库
step("4/5 构建知识库")
try:
    from rag.engine import build_knowledge_base
    col = build_knowledge_base()
    count = col.count() if col else 0
    print(f"  知识库就绪，共 {count} 个片段")
except Exception as e:
    print(f"  构建失败: {e}")

# 5. 完成
step("5/5 安装完成")
print(f"  启动: 双击 run.py")
print(f"  访问: http://localhost:8000")
print()
input("按回车键退出...")
