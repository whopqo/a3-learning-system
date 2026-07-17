"""
清理脚本 —— 一键删除运行过程中产生的临时文件
用完可删。如果不要了，整坨删掉也行。

会删除：
- ChromaDB向量存储（db/chroma_storage/）
- 记忆文件（db/memory/）
- Python缓存（__pycache__/）
- Streamlit缓存

不会删除：
- 知识库源文件（knowledge_base/course_data/）
- 代码文件
- 配置文件
"""
import os
import sys
import shutil

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("正在清理临时文件...")

# ChromaDB存储
chroma_dir = os.path.join("db", "chroma_storage")
if os.path.exists(chroma_dir):
    shutil.rmtree(chroma_dir)
    print(f"  已删除: {chroma_dir}")

# 记忆文件
memory_dir = os.path.join("db", "memory")
if os.path.exists(memory_dir):
    shutil.rmtree(memory_dir)
    print(f"  已删除: {memory_dir}")

# Python缓存
for root, dirs, files in os.walk("."):
    for d in dirs:
        if d == "__pycache__":
            cache_path = os.path.join(root, d)
            shutil.rmtree(cache_path)
            print(f"  已删除: {cache_path}")

print("清理完成！下次启动需要重新构建知识库。")
