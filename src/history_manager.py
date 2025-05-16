import yaml
import os

class HistoryManager:
    @staticmethod
    def load_history_nodes(yaml_path='output/all_clash_config.yaml'):
        """从YAML加载历史节点"""
        if not os.path.exists(yaml_path):
            return []
            
        with open(yaml_path, 'r') as f:
            config = yaml.safe_load(f)
            return config.get('proxies', [])
    
    @staticmethod
    def merge_nodes(new_nodes, history_nodes):
        """合并并去重节点"""
        seen = set()
        merged = []
        
        # 保留历史节点
        for node in history_nodes:
            fingerprint = HistoryManager._node_fingerprint(node)
            if fingerprint not in seen:
                seen.add(fingerprint)
                merged.append(node)
        
        # 添加新节点
        for node in new_nodes:
            fingerprint = HistoryManager._node_fingerprint(node['data'])
            if fingerprint not in seen:
                seen.add(fingerprint)
                merged.append(node['data'])
        
        return merged
    
    @staticmethod
    def _node_fingerprint(node):
        """生成节点唯一标识"""
        return f"{node['type']}://{node['server']}:{node['port']}@{hash(frozenset(node.items()))}"
    