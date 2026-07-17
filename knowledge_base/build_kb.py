"""
知识库构建脚本 —— 读取 course_data 目录下的文本，构建 ChromaDB 向量索引
右键运行或在终端: python knowledge_base/build_kb.py
保留以便重建知识库（修改课程内容后需要重新运行）
"""
import os, sys, time

proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(proj_root)
sys.path.insert(0, proj_root)

from rag.engine import build_knowledge_base, is_kb_ready

if __name__ == "__main__":
    if is_kb_ready():
        resp = input("知识库已存在，是否删除并重建？(y/N): ")
        if resp.lower() != "y":
            print("已取消。")
            sys.exit(0)

    print("=" * 50)
    print("  正在构建机器学习课程知识库...")
    print("=" * 50)

    try:
        start = time.time()
        col = build_knowledge_base()
        elapsed = time.time() - start
        count = col.count() if col else 0
        print("=" * 50)
        print(f"  知识库构建完成！共 {count} 个片段，耗时 {elapsed:.1f} 秒")
        print("  现在可以启动系统了: python run.py")
        print("=" * 50)
    except FileNotFoundError as e:
        print(f"\n文件错误: {e}")
        print("请确保 knowledge_base/course_data/ 目录存在且包含 .txt 或 .md 文件")
        sys.exit(1)
    except OSError as e:
        if "local" in str(e).lower() or "connect" in str(e).lower():
            print(f"\n模型未下载。请先联网运行 install.py 下载依赖和模型。")
        else:
            print(f"\n系统错误: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n构建失败: {e}")
        sys.exit(1)
