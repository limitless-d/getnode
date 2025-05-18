import base64
import hashlib
import json
import logging
import re
from collections import OrderedDict
from .counters import NodeCounter

logger = logging.getLogger("getnode")

class NodeUtils:
    @staticmethod
    def generate_fingerprint(node_data: dict) -> str:
        """生成节点唯一指纹"""
        node_type = node_data.get('type', 'unknown').lower()
        logger.debug(f"开始生成指纹，节点类型: {node_type}")
        
        core_fields = OrderedDict()

        # 通用字段
        core_fields['type'] = node_type
        core_fields['server'] = node_data.get('server', '')
        core_fields['port'] = str(node_data.get('port', ''))

        # 协议特定字段
        if node_type == 'ss':
            core_fields.update({
                'cipher': node_data.get('cipher', ''),
                'password': node_data.get('password', '')
            })
        elif node_type == 'vmess':
            core_fields.update({
                'uuid': node_data.get('uuid', ''),
                'alterId': str(node_data.get('alterId', '0')),
                'network': node_data.get('network', 'tcp')
            })
        elif node_type == 'trojan':
            core_fields.update({
                'password': node_data.get('password', ''),
                'sni': node_data.get('sni', '')
            })
        else:
            return hashlib.md5(
                json.dumps(node_data, sort_keys=True).encode()
            ).hexdigest()

        return hashlib.md5(
            json.dumps(core_fields, sort_keys=True).encode()
        ).hexdigest()

    @staticmethod
    def parse_base64(content: str, depth=0) -> str:
        """递归解析Base64内容"""
        if depth > 2:
            return content
            
        logger.debug(f"检测Base64有效性，内容长度: {len(content)}")
        try:
            if not NodeUtils.is_base64(content):
                return content
                
            # 修正填充
            content = content.rstrip('=')
            content += '=' * (4 - len(content) % 4)
            decoded = base64.b64decode(content).decode()
            
            logger.debug(f"Base64解码成功（深度{depth}）")
            if NodeUtils.is_base64(decoded):
                return NodeUtils.parse_base64(decoded, depth+1)
            return decoded
        except Exception as e:
            logger.error(f"Base64解析失败: {str(e)}")
            return content

    @staticmethod
    def is_base64(content: str) -> bool:
        """判断是否为有效Base64"""
        try:
            return re.match(r'^[A-Za-z0-9+/]*={0,2}$', content) and \
                len(content) % 4 == 0 and \
                base64.b64decode(content)
        except Exception:
            return False

    @staticmethod
    def add_nodes(result, seen, nodes, url, source_type):
        for node in nodes:
            # 新增：提取关键特征生成唯一指纹
            node_fingerprint = NodeUtils.generate_fingerprint(node)
            NodeCounter.total_nodes += 1

            if node_fingerprint not in seen:
                seen.add(node_fingerprint)
                result['nodes'].append({
                    'source_type': source_type,
                    'url': url,
                    'data': node
                })
            else:
                NodeCounter.dup_nodes += 1
                logger.debug(f"发现重复节点: {NodeUtils._get_node_identity(node)}")    

    @staticmethod
    def _get_node_identity(node_data: dict) -> str:
        """获取节点可读标识"""
        base_info = f"{node_data.get('type', 'unknown')}://"
        if 'server' in node_data:
            base_info += f"{node_data['server']}:{node_data.get('port', '')}"
        return base_info
    