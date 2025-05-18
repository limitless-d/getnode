import yaml
import os
import logging
from typing import List, Dict
from .tools import NodeUtils

logger = logging.getLogger("getnode")

class HistoryManager:
    @staticmethod
    def load_history_nodes(yaml_path='output/all_subs/all_clash_config.yaml') -> List[Dict]:
        """加载历史节点并与nodesjob格式对齐"""
        logger.debug(f"开始加载历史节点文件: {yaml_path}")
        if not os.path.exists(yaml_path):
            logger.warning("历史配置文件不存在")
            return []

        try:
            with open(yaml_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                nodes = config.get('proxies', [])
                logger.info(f"成功加载历史节点数量: {len(nodes)}")
                return nodes
            
        except Exception as e:
            logger.error(f"加载历史节点失败: {str(e)}")
            return []

    @staticmethod
    def merge_nodes(new_nodes, history_nodes):
        """合并新旧节点并去重节点"""
        logger.debug("开始合并节点数据")
        logger.info(f"新节点：{len(new_nodes['nodes'])}, 历史节点：{len(history_nodes)}")
        seen = set()
        result = {'nodes':[]}

        if not history_nodes:
            return new_nodes
        
        # 添加新节点
        nodes_to_merge = new_nodes.get('nodes', [])
        for node in nodes_to_merge:
            fingerprint = NodeUtils.generate_fingerprint(node['data'])
            if fingerprint not in seen:
                seen.add(fingerprint)
                result['nodes'].append(node)
        # 处理历史节点
        NodeUtils.add_nodes(result, seen, history_nodes, None, 'clash')
        
        result['total_nodes'] = len(result['nodes'])  # 更新result统计信息

        logger.info(f"合并后总节点数: {len(result['nodes'])}")
        return result
