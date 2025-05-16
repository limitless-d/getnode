import yaml
import os
import logging
from typing import List, Dict
from .tools import NodeUtils

logger = logging.getLogger(__name__)

class HistoryManager:
    @staticmethod
    def load_history_nodes(yaml_path='output/all_clash_config.yaml') -> List[Dict]:
        """加载历史节点并与nodesjob格式对齐"""
        logger.debug(f"开始加载历史节点文件: {yaml_path}")
        if not os.path.exists(yaml_path):
            logger.warning("历史配置文件不存在")
            return []

        try:
            with open(yaml_path, 'r') as f:
                config = yaml.safe_load(f)
                nodes = config.get('proxies', [])
                logger.info(f"成功加载历史节点数量: {len(nodes)}")
                return nodes
                # return [HistoryManager._format_node(n) for n in nodes]
        except Exception as e:
            logger.error(f"加载历史节点失败: {str(e)}")
            return []

    @staticmethod
    # def merge_nodes(new_nodes: List[Dict], history_nodes: List[Dict]) -> List[Dict]:
    #     """合并新旧节点（以nodesjob格式为准）"""
    def merge_nodes(new_nodes, history_nodes):
        """合并并去重节点"""
        logger.debug("开始合并节点数据")
        seen = set()
        merged = []

        # 处理历史节点
        for node in history_nodes:
            fingerprint = NodeUtils.generate_fingerprint(node)
            if fingerprint not in seen:
                seen.add(fingerprint)
                merged.append(node)
                logger.debug(f"保留历史节点: {node.get('name')}")

        # 处理新节点
        node_data = new_nodes.get('nodes', [])
        for node in node_data:
            fingerprint = NodeUtils.generate_fingerprint(node)
            if fingerprint not in seen:
                seen.add(fingerprint)
                merged.append(node)
                logger.debug(f"添加新节点: {node.get('name')}")

        logger.info(f"合并后总节点数: {len(merged)}")
        return merged
