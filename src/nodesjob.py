import os
import re
import requests
import json
import base64
import binascii
import yaml
import hashlib
import logging
from urllib.parse import urlparse, unquote, parse_qs, quote
from collections import OrderedDict
from typing import List, Dict

logger = logging.getLogger(__name__)

class NodeCounter:
    total_nodes = 0
    dup_nodes = 0

class NodeProcessor:
    @staticmethod
    def parse_node_links(links: List[str]) -> Dict:
        logger.info(f"开始处理链接集合，共 {len(links)} 个链接")
        result = {
            'total_links': len(links),
            'success_count': 0,
            'failure_count': 0,
            'total_nodes': 0,
            'nodes': [],
            'failures': []
        }
        
        seen = set()

        for index, url in enumerate(links, 1):
            try:
                logger.info(f"正在处理链接 ({index}/{len(links)}): {url}")
                
                # 新增内容获取步骤
                response = requests.get(url, timeout=15)
                response.raise_for_status()
                content = response.text



                # 尝试解析为Clash配置
                clash_result = NodeProcessor._parse_clash_config_content(content)
                if clash_result['success']:
                    result['success_count'] += 1
                    NodeProcessor._add_nodes(result, seen, clash_result['data'], url, 'clash')
                    continue
                
                # 尝试解析为文本节点
                txt_result = NodeProcessor._parse_txt_content(content)
                if txt_result['success']:
                    result['success_count'] += 1
                    NodeProcessor._add_nodes(result, seen, txt_result['data'], url, 'text')
                    continue

                # 新增：尝试解析为Base64编码内容
                base64_result = NodeProcessor._parse_base64_config(content)
                if base64_result['success']:
                    result['success_count'] += 1
                    NodeProcessor._add_nodes(result, seen, base64_result['data'], url, 'base64')
                    continue
                
                result['failure_count'] += 1
                result['failures'].append({'url': url, 'error': '无法识别配置格式'})
                
            except Exception as e:
                error_msg = f'处理异常: {str(e)}'
                logger.error(f"处理链接时发生异常: {error_msg}", exc_info=True)
                result['failure_count'] += 1
                result['failures'].append({'url': url, 'error': error_msg})
        
        result['total_nodes'] = len(result['nodes'])
        logger.info(f"处理完成。成功: {result['success_count']}, 失败: {result['failure_count']}, 节点数: {result['total_nodes']}")
        return result

    @staticmethod
    def _parse_base64_config(url: str, depth=0) -> Dict:
        """
        解析Base64编码内容（支持递归）
        :param url: 当is_content=False时为URL，否则为待解码的Base64字符串
        :param depth: 当前递归深度
        :param is_content: 标记当前处理的是否为原始内容
        """
        if depth > 2:
            return {'success': False, 'message': '超过最大递归深度（3层）'}
        
        result = {'success': False, 'data': [], 'message': ''}
        
        try:
            """
            # 获取原始内容
            if is_content:
                encoded_content = url  # 直接使用传入的内容
            else:
                response = requests.get(url, timeout=15)
                response.raise_for_status()
                encoded_content = response.text.strip()
            """

            # 修复Base64填充
            missing_padding = len(encoded_content) % 4
            if missing_padding:
                encoded_content += '=' * (4 - missing_padding)

            # 解码内容
            decoded_content = base64.b64decode(encoded_content).decode('utf-8')
            logger.debug(f"Base64解码成功（深度{depth}），内容长度: {len(decoded_content)}")

            # 递归解析场景：解码后的内容仍是Base64
            if NodeProcessor._is_base64(decoded_content):
                logger.debug(f"检测到嵌套Base64（深度{depth}），尝试递归解析")
                nested_result = NodeProcessor._parse_base64_config(
                    decoded_content,  # 传递解码后的内容
                    depth=depth + 1,   # 深度+1
                #    is_content=True    # 标记为内容模式
                )
                if nested_result['success']:
                    return nested_result

            # 解析解码后的内容
            if decoded_content.startswith('proxies:'):  # Clash配置
                clash_result = NodeProcessor._parse_clash_config_content(decoded_content)
                if clash_result['success']:
                    result['success'] = True
                    result['data'] = clash_result['data']
            else:  # 文本节点列表
                txt_result = NodeProcessor._parse_txt_content(decoded_content)
                if txt_result['success']:
                    result['success'] = True
                    result['data'] = txt_result['data']

            if not result['success']:
                result['message'] = '解码成功但内容无法识别'

        except requests.RequestException as e:
            result['message'] = f'请求失败: {str(e)}'
        except (UnicodeDecodeError, binascii.Error) as e:
            result['message'] = f'Base64解码失败: {str(e)}'
        except Exception as e:
            result['message'] = f'未知错误: {str(e)}'
            logger.error(f"Base64解析异常: {str(e)}", exc_info=True)
        
        return result

    @staticmethod
    def _is_base64(content: str) -> bool:
        """判断内容是否为Base64编码"""
        try:
            # 特征检查：Base64字符集+长度为4的倍数
            if not re.match(r'^[A-Za-z0-9+/=]+$', content):
                return False
            
            # 尝试解码验证
            base64.b64decode(content)
            return True
        except Exception:
            return False

    @staticmethod
    def _parse_clash_config_content(content: str) -> Dict:
        """解析Clash配置内容"""
        try:
            # 添加内容预览日志
            logger.debug(f"解析Clash配置内容片段: {content[:200]}...")

            # 添加内容类型验证
            if isinstance(content, str):
                config = yaml.safe_load(content)
            elif isinstance(content, dict):
                config = content
            else:
                raise ValueError("无效的配置类型")

            # 添加配置结构验证
            if not isinstance(config, dict):
                logger.error("Clash配置格式错误")
                return {'success': False, 'data': []}

            # 增强proxies字段检查
            proxies = config.get('proxies', [])
            if not isinstance(proxies, list):
                logger.warning("proxies字段类型异常")
                proxies = []

            return {'success': bool(proxies), 'data': proxies}

        except yaml.YAMLError as e:
            logger.error(f"YAML解析失败: {str(e)}")
            return {'success': False, 'data': []}
        
    @staticmethod
    def _parse_txt_content(content: str) -> Dict:
        """解析纯文本内容（非URL）
        参数:
            content: 包含多行节点链接的文本内容
        返回:
            包含解析结果的字典 {'success': bool, 'data': list}
        """
        result = {'success': False, 'data': []}
        nodes = []
        
        # 逐行处理文本内容
        for line in content.splitlines():
            line = line.strip()  # 去除前后空白
            if not line:
                continue  # 跳过空行
                
            # 尝试解析单行数据
            node = NodeProcessor._parse_single_line(line)
            if node:
                nodes.append(node)
                
        # 如果有成功解析的节点
        if nodes:
            result['success'] = True
            result['data'] = nodes
            
        return result

    @staticmethod
    def _parse_single_line(line: str):
        """解析单行节点链接
        参数:
            line: 单个节点链接字符串
        返回:
            解析后的节点信息字典 或 None（解析失败时）
        """
        try:
            line = line.strip()
            if not line:
                return None

            # 根据协议类型调用对应的解析方法
            if line.startswith("vmess://"):
                return NodeProcessor._parse_vmess(line)
            elif line.startswith("ss://"):
                return NodeProcessor._parse_ss(line)
            elif line.startswith("trojan://"):
                return NodeProcessor._parse_trojan(line)
            elif line.startswith("vless://"):
                return NodeProcessor._parse_vless(line)
            else:
                logger.debug(f"未知协议: {line[:50]}...")
                return None
                
        except Exception as e:
            logger.debug(f"解析失败: {line[:50]}... | 错误: {str(e)}")
            return None

    @staticmethod
    def _parse_vmess(line: str) -> dict:
        """解析VMESS协议链接
        格式：vmess://base64(json配置)
        """
        try:
            # 截取base64部分并解码
            encoded = line[8:]  # 去掉开头的"vmess://"
            decoded = base64.b64decode(unquote(encoded)).decode('utf-8')
            config = json.loads(decoded)
            
            # 验证必要字段
            required_fields = ['add', 'port', 'id']
            if not all(field in config for field in required_fields):
                raise ValueError("缺少必要字段")
                
            return {
                'type': 'vmess',
                'name': config.get('ps', '未命名节点'),
                'server': config['add'],
                'port': config['port'],
                'uuid': config['id'],
                'alterId': config.get('aid', 0),
                'network': config.get('net', 'tcp'),
                'tls': 'tls' if config.get('tls') else ''
            }
        except (binascii.Error, json.JSONDecodeError, KeyError) as e:
            raise ValueError(f"VMESS解析错误: {str(e)}")

    @staticmethod
    def _parse_ss(line: str) -> dict:
        """解析Shadowsocks协议链接
        格式：ss://method:password@host:port#备注
        """
        try:
            # 分割基本信息和备注
            parts = line[5:].split('#', 1)  # 去掉开头的"ss://"
            encoded_part = parts[0]
            name = unquote(parts[1]) if len(parts) > 1 else ''
            
            # 处理不同base64编码格式
            if '_' in encoded_part or '-' in encoded_part:
                decoded = base64.urlsafe_b64decode(encoded_part + '==').decode()
            else:
                decoded = base64.b64decode(unquote(encoded_part)).decode()
                
            # 分割认证信息和服务器信息
            if '@' not in decoded:
                raise ValueError("格式错误")
            auth, server = decoded.split('@', 1)
            
            # 分割加密方法和密码
            if ':' not in auth:
                raise ValueError("认证信息格式错误")
            method, password = auth.split(':', 1)
            
            # 分割主机和端口
            if ':' not in server:
                raise ValueError("服务器格式错误")
            host, port = server.split(':', 1)
            
            return {
                'type': 'ss',
                'name': name,
                'server': host,
                'port': port,
                'password': password,
                'cipher': method
            }
        except (binascii.Error, ValueError) as e:
            raise ValueError(f"SS解析错误: {str(e)}")

    @staticmethod
    def _parse_trojan(line: str) -> dict:
        """解析Trojan协议链接
        格式：trojan://password@host:port?params#备注
        """
        try:
            # 使用urllib解析URL
            parsed = urlparse(line)
            
            # 分割密码和服务器信息
            if '@' not in parsed.netloc:
                raise ValueError("格式错误")
            password, hostport = parsed.netloc.split('@', 1)
            
            # 分割主机和端口
            if ':' not in hostport:
                raise ValueError("服务器格式错误")
            host, port = hostport.split(':', 1)
            
            # 解析查询参数
            query = parse_qs(parsed.query)
            
            return {
                'type': 'trojan',
                'name': unquote(parsed.fragment) if parsed.fragment else '未命名节点',
                'server': host,
                'port': port,
                'password': password,
                'sni': query.get('sni', [''])[0],  # 服务器名称指示
                'security': query.get('security', ['tls'])[0],  # 安全类型
                'type': query.get('type', ['tcp'])[0]  # 传输类型
            }
        except ValueError as e:
            raise ValueError(f"Trojan解析错误: {str(e)}")

    @staticmethod
    def _parse_vless(line: str) -> dict:
        """解析VLESS协议链接
        格式：vless://uuid@host:port?params#备注
        """
        try:
            parsed = urlparse(line)
            
            # 分割UUID和服务器信息
            if '@' not in parsed.netloc:
                raise ValueError("格式错误")
            uuid, hostport = parsed.netloc.split('@', 1)
            
            # 分割主机和端口
            if ':' not in hostport:
                raise ValueError("服务器格式错误")
            host, port = hostport.split(':', 1)
            
            # 解析查询参数
            query = parse_qs(parsed.query)
            
            return {
                'type': 'vless',
                'name': unquote(parsed.fragment) if parsed.fragment else '未命名节点',
                'server': host,
                'port': port,
                'uuid': uuid,
                'security': query.get('security', ['none'])[0],  # 安全协议
                'sni': query.get('sni', [''])[0],  # 服务器名称指示
                'flow': query.get('flow', [''])[0],  # 流控模式
                'network': query.get('type', ['tcp'])[0]  # 传输类型
            }
        except ValueError as e:
            raise ValueError(f"VLESS解析错误: {str(e)}")
        
    @staticmethod
    def _add_nodes(result, seen, nodes, url, source_type):
        for node in nodes:
            # 新增：提取关键特征生成唯一指纹
            node_fingerprint = NodeProcessor._generate_fingerprint(node)

            NodeCounter.total_nodes += 1
            if node_fingerprint in seen:
                NodeCounter.dup_nodes += 1

            if node_fingerprint not in seen:
                seen.add(node_fingerprint)
                result['nodes'].append({
                    'source_type': source_type,
                    'url': url,
                    'data': node
                })
            else:
                logger.debug(f"发现重复节点: {NodeProcessor._get_node_identity(node)}")
        logger.info(f"去重统计: 总发现节点={NodeCounter.total_nodes} 重复节点={NodeCounter.dup_nodes}")

    @staticmethod
    def _generate_fingerprint(node_data: dict) -> str:
        """生成节点唯一指纹"""
        # 按协议类型提取关键字段
        node_type = node_data.get('type', 'unknown').lower()
        core_fields = OrderedDict()

        # 通用关键字段
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
            # 未知协议使用完整数据哈希
            return hashlib.md5(
                json.dumps(node_data, sort_keys=True).encode()
            ).hexdigest()

        # 生成标准化哈希
        return hashlib.md5(
            json.dumps(core_fields, sort_keys=True).encode()
        ).hexdigest()

    @staticmethod
    def _get_node_identity(node_data: dict) -> str:
        """获取节点可读标识"""
        base_info = f"{node_data.get('type', 'unknown')}://"
        if 'server' in node_data:
            base_info += f"{node_data['server']}:{node_data.get('port', '')}"
        return base_info
    
class FileGenerator:
    @staticmethod
    def save_results(node_results, output_dir='output'):
        try:
            os.makedirs(output_dir, exist_ok=True)
            clash_config = {'proxies': []}
            v2rayn_lines = []
            node_counter = {}

            for node in node_results['nodes']:
                FileGenerator._process_node(node, clash_config, v2rayn_lines, node_counter)

            FileGenerator._write_files(output_dir, clash_config, v2rayn_lines)
            return {
                'success': True,
                'files': [
                    os.path.join(output_dir, 'subscription.txt'),
                    os.path.join(output_dir, 'clash_config.yaml')
                ],
                'node_counts': node_counter
            }
        except Exception as e:
            logger.error(f"保存失败: {str(e)}", exc_info=True)
            return {'success': False, 'message': str(e)}

    @staticmethod
    def _process_node(node, clash_config, v2rayn_lines, node_counter):
        node_type = node['data'].get('type', 'unknown')
        node_counter[node_type] = node_counter.get(node_type, 0) + 1

        if node['source_type'] == 'text' and 'raw' in node['data']:
            v2rayn_lines.append(node['data']['raw'])
        else:
            uri = FileGenerator._generate_uri(node['data'])
            if uri:
                v2rayn_lines.append(uri)

        clash_proxy = FileGenerator._convert_to_clash(node['data'])
        if clash_proxy:
            clash_config['proxies'].append(clash_proxy)

    @staticmethod
    def _generate_uri(node_data):
        """将Clash节点转换为标准URI格式"""
        node_type = node_data.get('type')
        try:
            if node_type == 'ss':
                # ss://method:password@server:port#name
                method = node_data.get('cipher', '')
                password = node_data.get('password', '')
                server = node_data.get('server', '')
                port = node_data.get('port', '')
                name = quote(node_data.get('name', ''))
                
                ss_uri = f"{method}:{password}@{server}:{port}"
                encoded = base64.b64encode(ss_uri.encode()).decode()
                return f"ss://{encoded}#{name}"

            elif node_type == 'vmess':
                # vmess://base64(json)
                vmess_json = {
                    "v": "2",
                    "ps": node_data.get('name', ''),
                    "add": node_data.get('server', ''),
                    "port": node_data.get('port', ''),
                    "id": node_data.get('uuid', ''),
                    "aid": node_data.get('alterId', '0'),
                    "scy": "auto",
                    "net": node_data.get('network', 'tcp'),
                    "type": "none",
                    "tls": "tls" if node_data.get('tls') else ""
                }
                encoded = base64.b64encode(json.dumps(vmess_json).encode()).decode()
                return f"vmess://{encoded}"

            elif node_type == 'trojan':
                # trojan://password@server:port?security=tls#name
                password = node_data.get('password', '')
                server = node_data.get('server', '')
                port = node_data.get('port', '')
                name = quote(node_data.get('name', ''))
                sni = node_data.get('sni', '')
                
                query = f"security=tls&sni={sni}" if sni else "security=tls"
                return f"trojan://{password}@{server}:{port}?{query}#{name}"
                
        except Exception as e:
            logger.warning(f"转换URI失败：{str(e)}")
        return None

    @staticmethod
    def _convert_to_clash(node_data):
        """转换为Clash兼容配置"""
        base_proxy = {
            'name': node_data.get('name', ''),
            'type': node_data.get('type'),
            'server': node_data.get('server'),
            'port': node_data.get('port')
        }
        
        # 协议特定字段
        if node_data['type'] == 'ss':
            base_proxy.update({
                'cipher': node_data.get('cipher'),
                'password': node_data.get('password'),
                'udp': True
            })
        elif node_data['type'] == 'vmess':
            base_proxy.update({
                'uuid': node_data.get('uuid'),
                'alterId': node_data.get('alterId', 0),
                'cipher': 'auto',
                'tls': node_data.get('tls', False),
                'network': node_data.get('network', 'tcp')
            })
        elif node_data['type'] == 'trojan':
            base_proxy.update({
                'password': node_data.get('password'),
                'sni': node_data.get('sni', ''),
                'udp': True
            })
        
        return base_proxy

    @staticmethod
    def _write_files(output_dir, clash_config, v2rayn_lines):
        txt_path = os.path.join(output_dir, 'subscription.txt')
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(v2rayn_lines))

        yaml_path = os.path.join(output_dir, 'clash_config.yaml')
        with open(yaml_path, 'w', encoding='utf-8') as f:
            yaml.safe_dump(clash_config, f, allow_unicode=True, sort_keys=False)
