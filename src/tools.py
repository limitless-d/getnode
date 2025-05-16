import base64
import hashlib
import json
import logging
import re
from collections import OrderedDict
# from urllib.parse import urlparse, parse_qs, unquote, quote

logger = logging.getLogger(__name__)

class NodeUtils:
    @staticmethod
    def generate_fingerprint(node_data: dict) -> str:
        """生成节点唯一指纹（与nodesjob逻辑一致）"""
        node_type = node_data.get('type', 'unknown').lower()
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
        