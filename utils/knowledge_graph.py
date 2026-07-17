"""
知识图谱工具 -- 基于 course_data 里的实际教材章节构建依赖图
"""
import json, os, re
import networkx as nx
from typing import List, Dict, Optional, Set

def _scan_course_chapters() -> list[dict]:
    """从 course_data 目录扫描所有章节文件名，生成节点列表"""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    course_dir = os.path.join(base, "knowledge_base", "course_data")
    chapters = []
    if not os.path.isdir(course_dir):
        return _fallback_chapters()
    for fname in sorted(os.listdir(course_dir)):
        if not fname.endswith(('.txt', '.md')):
            continue
        name = fname.replace(".txt", "").replace(".md", "")
        # 优先匹配"第X章"格式的章节号
        m = re.search(r'第(\d+)章', name)
        order = int(m.group(1)) if m else 999
        # 去掉"第X章_"前缀，只留标题
        name = re.sub(r'^第\d+章_?', '', name)
        # 附录特殊处理
        if "附录" in name or "矩阵" in name:
            order = 998
            name = "附录A 矩阵"
        node_id = f"ch{order}" if order < 900 else "appendix_a"
        chapters.append({
            "id": node_id,
            "name": name,
            "difficulty": "入门" if order <= 2 else ("中等" if order <= 9 else "进阶"),
            "hours": 1.5 if order <= 2 else (2.0 if order <= 9 else 2.5),
            "category": "基础" if order <= 2 else ("核心算法" if order <= 9 else "进阶专题"),
            "order": order,
        })
    return chapters if chapters else _fallback_chapters()

def _fallback_chapters() -> list[dict]:
    return [
        {"id": "ch1", "name": "绪论", "difficulty": "入门", "hours": 1.0, "category": "基础", "order": 1},
        {"id": "ch2", "name": "模型评估与选择", "difficulty": "入门", "hours": 2.0, "category": "基础", "order": 2},
        {"id": "ch3", "name": "线性模型", "difficulty": "入门", "hours": 2.0, "category": "核心算法", "order": 3},
        {"id": "ch4", "name": "决策树", "difficulty": "中等", "hours": 2.0, "category": "核心算法", "order": 4},
        {"id": "ch5", "name": "神经网络", "difficulty": "中等", "hours": 2.5, "category": "核心算法", "order": 5},
        {"id": "ch6", "name": "支持向量机", "difficulty": "进阶", "hours": 2.5, "category": "核心算法", "order": 6},
        {"id": "ch7", "name": "贝叶斯分类器", "difficulty": "中等", "hours": 2.0, "category": "核心算法", "order": 7},
        {"id": "ch8", "name": "集成学习", "difficulty": "中等", "hours": 2.0, "category": "核心算法", "order": 8},
        {"id": "ch9", "name": "聚类", "difficulty": "中等", "hours": 2.0, "category": "核心算法", "order": 9},
        {"id": "ch10", "name": "降维与度量学习", "difficulty": "进阶", "hours": 2.5, "category": "进阶专题", "order": 10},
        {"id": "ch11", "name": "特征选择与稀疏学习", "difficulty": "进阶", "hours": 2.5, "category": "进阶专题", "order": 11},
        {"id": "ch12", "name": "计算学习理论", "difficulty": "进阶", "hours": 3.0, "category": "进阶专题", "order": 12},
        {"id": "ch13", "name": "半监督学习", "difficulty": "进阶", "hours": 2.5, "category": "进阶专题", "order": 13},
        {"id": "ch14", "name": "概率图模型", "difficulty": "进阶", "hours": 3.0, "category": "进阶专题", "order": 14},
        {"id": "ch15", "name": "规则学习", "difficulty": "进阶", "hours": 2.0, "category": "进阶专题", "order": 15},
        {"id": "ch16", "name": "强化学习", "difficulty": "进阶", "hours": 3.0, "category": "进阶专题", "order": 16},
        {"id": "appendix", "name": "附录A 矩阵", "difficulty": "进阶", "hours": 1.0, "category": "参考", "order": 998},
    ]

class KnowledgeGraph:
    """课程知识图谱 -- 教材章节依赖图"""

    def __init__(self, course_name: str = "机器学习"):
        self.course_name = course_name
        self.graph = nx.DiGraph()
        self._nodes_list = None
        self._build_from_course_data()

    def _build_from_course_data(self):
        """从 course_data 目录扫描实际章节构建图"""
        nodes = _scan_course_chapters()
        self._nodes_list = nodes
        for node in nodes:
            self.graph.add_node(node["id"], **node)
        # 依赖边：每章依赖前一章
        ordered = sorted(nodes, key=lambda n: n.get("order", 999))
        ids = [n["id"] for n in ordered]
        # 线性前置：1→2→3→4...
        for i in range(1, len(ids)):
            if ordered[i].get("order", 999) < 900:
                prev_id = ids[i-1]
                curr_id = ids[i]
                if self.graph.has_node(prev_id) and self.graph.has_node(curr_id):
                    self.graph.add_edge(prev_id, curr_id)

        # 交叉依赖：从 cross_edges.json 加载
        edges_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                  "knowledge_base", "cross_edges.json")
        if os.path.exists(edges_file):
            try:
                with open(edges_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for a, b in data.get("cross_edges", []):
                    # cross_edges: ["ch8","ch4"] 表示 ch8 依赖 ch4
                    # add_edge(prereq, dependent) 即 ch4→ch8
                    if self.graph.has_node(a) and self.graph.has_node(b):
                        if not self.graph.has_edge(b, a):
                            self.graph.add_edge(b, a)
            except Exception:
                pass

    def get_node(self, node_id: str) -> Optional[Dict]:
        if node_id in self.graph:
            return dict(self.graph.nodes[node_id])
        return None

    def get_prerequisites(self, node_id: str) -> List[str]:
        if node_id not in self.graph:
            return []
        return list(self.graph.predecessors(node_id))

    def get_dependents(self, node_id: str) -> List[str]:
        if node_id not in self.graph:
            return []
        return list(self.graph.successors(node_id))

    def get_available_nodes(self, mastered: Set[str]) -> List[Dict]:
        available = []
        for node_id in self.graph.nodes:
            if node_id in mastered:
                continue
            prerequisites = set(self.get_prerequisites(node_id))
            if prerequisites.issubset(mastered):
                node_data = dict(self.graph.nodes[node_id])
                node_data["id"] = node_id
                available.append(node_data)
        return available

    def get_learning_path(self, mastered: Set[str], target: str = None, max_steps: int = 20) -> List[Dict]:
        """拓扑排序 + 难度排序生成学习路径"""
        path = []
        remaining = set(self.graph.nodes) - mastered
        current_mastered = set(mastered)
        difficulty_order = {"入门": 0, "中等": 1, "进阶": 2}

        for _ in range(max_steps):
            available = self.get_available_nodes(current_mastered)
            if not available:
                break

            # 优先选：通向target + 简单
            if target and target in remaining:
                best = None
                best_len = 999
                for node in available:
                    try:
                        sp = nx.shortest_path(self.graph, node["id"], target)
                        score = len(sp) * 10 + difficulty_order.get(node.get("difficulty","中等"),1)
                        if score < best_len:
                            best_len = score
                            best = node
                    except (nx.NetworkXNoPath, nx.NodeNotFound):
                        continue
                if best:
                    node = best
                else:
                    available.sort(key=lambda n: (difficulty_order.get(n.get("difficulty","中等"),1), n.get("hours",1)))
                    node = available[0]
            else:
                available.sort(key=lambda n: (difficulty_order.get(n.get("difficulty","中等"),1), n.get("hours",1)))
                node = available[0]

            path.append(node)
            current_mastered.add(node["id"])
            remaining.discard(node["id"])

            if target and target in current_mastered:
                break
        return path

    def get_all_nodes(self) -> List[Dict]:
        result = []
        for node_id in self.graph.nodes:
            data = dict(self.graph.nodes[node_id])
            data["id"] = node_id
            data["prerequisites"] = self.get_prerequisites(node_id)
            data["dependents"] = self.get_dependents(node_id)
            result.append(data)
        return sorted(result, key=lambda n: n.get("order", 999))

    def export_graph_data(self) -> Dict:
        nodes = []
        edges = []
        for node_id in self.graph.nodes:
            data = dict(self.graph.nodes[node_id])
            nodes.append({
                "id": node_id,
                "name": data.get("name", node_id),
                "difficulty": data.get("difficulty", "中等"),
                "category": data.get("category", ""),
                "hours": data.get("hours", 1.0),
            })
        for src, dst in self.graph.edges:
            edges.append({"source": src, "target": dst})
        return {"nodes": nodes, "edges": edges}

    def find_weakness_path(self, weakness_nodes: List[str], mastered: Set[str]) -> List[Dict]:
        """找到薄弱点的所有传递前置（递归），返回复习路径"""
        path = []
        seen = set()
        for node_id in weakness_nodes:
            # 用nx.ancestors找所有传递前置
            all_prereqs = nx.ancestors(self.graph, node_id) if node_id in self.graph else set()
            missing = all_prereqs - mastered - seen
            for missing_node in sorted(missing):
                nd = self.get_node(missing_node)
                if nd:
                    nd["id"] = missing_node
                    nd["reason"] = f"前置知识（{node_id}需要）"
                    path.append(nd)
                    seen.add(missing_node)
            # 加上薄弱点本身
            nd = self.get_node(node_id)
            if nd:
                nd["id"] = node_id
                nd["reason"] = "薄弱点复习"
                path.append(nd)
                seen.add(node_id)
        return path

_knowledge_graph = None

def get_knowledge_graph() -> KnowledgeGraph:
    global _knowledge_graph
    if _knowledge_graph is None:
        _knowledge_graph = KnowledgeGraph()
    return _knowledge_graph
