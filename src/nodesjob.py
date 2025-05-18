import os
import re
import requests
import json
import base64
import binascii
import yaml
import logging
from urllib.parse import urlparse, unquote, parse_qs, quote
from typing import List, Dict
from .tools import NodeUtils

logger = logging.getLogger("getnode")

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
                logger.debug(f"正在处理链接 ({index}/{len(links)}): {url}")
                
                # 内容获取步骤
                response = requests.get(url, timeout=15)
                response.raise_for_status()
                content = response.text

                # 尝试解析为Base64编码内容
                content = NodeProcessor._parse_base64_config(content)
                
                # 尝试解析为文本节点
                txt_result = NodeProcessor._parse_txt_content(content)
                if txt_result['success']:
                    result['success_count'] += 1
                    NodeUtils.add_nodes(result, seen, txt_result['data'], url, 'text')
                    continue

                # 尝试解析为Clash配置
                clash_result = NodeProcessor._parse_clash_config_content(content)
                if clash_result['success']:
                    result['success_count'] += 1
                    NodeUtils.add_nodes(result, seen, clash_result['data'], url, 'clash')
                    continue
                
                # 尝试解析为Json配置
                json_result = NodeProcessor._parse_clash_config_content(content)
                if json_result['success']:
                    result['success_count'] += 1
                    NodeUtils.add_nodes(result, seen, json_result['data'], url, 'clash')
                    continue
                
                logger.debug(f"无法解析链接内容: {url}")
                result['failure_count'] += 1
                result['failures'].append({'url': url, 'error': '无法识别配置格式'})
                
            except Exception as e:
                error_msg = f'处理异常: {str(e)}'
                logger.error(f"处理链接时发生异常: {error_msg}", exc_info=True)
                result['failure_count'] += 1
                result['failures'].append({'url': url, 'error': error_msg})
        
        result['total_nodes'] = len(result['nodes'])
        logger.info(f"链接处理完成。成功: {result['success_count']}, 失败: {result['failure_count']}")
        return result

    @staticmethod
    def _parse_base64_config(encoded_content: str, depth=0) -> Dict:
        """
        解析Base64编码内容（支持递归）
        :param encoded_content: 待解码的Base64字符串
        :param depth: 当前递归深度
        """
        if depth > 2:
            return encoded_content
                
        try:
            if NodeProcessor._is_base64(encoded_content):
                # 修复Base64填充
                encoded_content = encoded_content.rstrip('=')  # 移除多余的 '='
                missing_padding = len(encoded_content) % 4
                if missing_padding:
                    encoded_content += '=' * (4 - missing_padding)

                # 解码内容
                decoded_content = base64.b64decode(encoded_content).decode('utf-8')
                logger.debug(f"Base64解码成功（深度{depth}），内容长度: {len(decoded_content)}")

                # 如果解码后的内容仍是Base64，递归解析
                if NodeProcessor._is_base64(decoded_content):
                    logger.debug(f"检测到嵌套Base64（深度{depth}），尝试递归解析")
                    return NodeProcessor._parse_base64_config(decoded_content, depth + 1)
                
                return decoded_content  # 返回解码后的内容
            
            # 处理非Base64编码的内容 返回原始内容
            return encoded_content  
        
        # 处理异常情况，返回原始内容    
        except Exception as e:
            logger.error(f"Base64解码失败: {str(e)}")
            return encoded_content

    @staticmethod
    def _is_base64(content: str) -> bool:
        """判断内容是否为Base64编码"""
        try:
            # 特征检查：Base64字符集+长度为4的倍数
            if not re.match(r'^[A-Za-z0-9+/]*={0,2}$', content):
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
                logger.debug("Clash配置格式错误")
                return {'success': False, 'data': []}

            # 增强proxies字段检查
            proxies = config.get('proxies', [])
            if not isinstance(proxies, list):
                logger.debug("proxies字段类型异常")
                proxies = []

            # 验证每个节点的格式
            valid_proxies = []
            for proxy in proxies:
                if all(key in proxy for key in ['name', 'type', 'server', 'port']):
                    valid_proxies.append(proxy)
                else:
                    logger.debug(f"跳过无效节点: {proxy}")
            proxies = valid_proxies

            # 日志记录
            if proxies:
                logger.debug(f"成功解析到 {len(proxies)} 个节点")
            else:
                logger.debug("未解析到任何有效的节点，可能是配置文件格式错误或内容为空")

            return {
                'success': bool(proxies),
                'data': proxies
            }

        except yaml.YAMLError as e:
            logger.debug(f"YAML解析失败: {str(e)}")
            return {'success': False, 'data': []}
        except Exception as e:
            logger.error(f"解析Clash配置文件时发生未知错误: {str(e)}", exc_info=True)
            return {'success': False, 'data': []}
        
    @staticmethod
    def _parse_json_content(content: str) -> Dict:
        """
        解析JSON格式的节点文件
        :param content: JSON字符串
        :return: 包含解析结果的字典 {'success': bool, 'data': list}
        """
        try:
            # 尝试将内容解析为JSON
            config = json.loads(content)
            logger.debug(f"成功解析JSON内容，长度: {len(content)}")

            # 验证JSON结构是否包含节点信息
            if not isinstance(config, dict) or 'nodes' not in config:
                logger.debug("JSON内容不包含有效的节点信息")
                return {'success': False, 'data': []}

            nodes = config.get('nodes', [])
            if not isinstance(nodes, list):
                logger.debug("JSON中的节点信息格式错误")
                return {'success': False, 'data': []}

            # 返回解析结果
            return {'success': True, 'data': nodes}

        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {str(e)}")
            return {'success': False, 'data': []}
        except Exception as e:
            logger.error(f"解析JSON内容时发生未知错误: {str(e)}", exc_info=True)
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
            elif line.startswith("hysteria2://"):
                return NodeProcessor._parse_hysteria2(line)
            elif line.startswith("tcp://"):
                return NodeProcessor._parse_tcp(line)
            elif line.startswith("ws://"):
                return NodeProcessor._parse_ws(line)
            elif line.startswith("ssr://"):
                return NodeProcessor._parse_ssr(line)
            elif line.startswith("grpc://"):
                return NodeProcessor._parse_grpc(line)
            elif line.startswith("httpupgrade://"):
                return NodeProcessor._parse_httpupgrade(line)
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
    def _parse_hysteria2(line: str) -> dict:
        """解析Hysteria2协议链接
        格式：hysteria2://server:port?protocol=protocol&auth=auth&obfs=obfs&peer=peer#name
        """
        try:
            parsed = urlparse(line)
            server, port = parsed.netloc.split(':')
            query = parse_qs(parsed.query)
            return {
                'type': 'hysteria2',
                'name': unquote(parsed.fragment) if parsed.fragment else '未命名节点',
                'server': server,
                'port': port,
                'protocol': query.get('protocol', ['udp'])[0],
                'auth': query.get('auth', [''])[0],
                'obfs': query.get('obfs', [''])[0],
                'peer': query.get('peer', [''])[0]
            }
        except ValueError as e:
            raise ValueError(f"Hysteria2解析错误: {str(e)}")

    @staticmethod
    def _parse_tcp(line: str) -> dict:
        """解析TCP协议链接
        格式：tcp://server:port#name
        """
        try:
            parsed = urlparse(line)
            server, port = parsed.netloc.split(':')
            return {
                'type': 'tcp',
                'name': unquote(parsed.fragment) if parsed.fragment else '未命名节点',
                'server': server,
                'port': port
            }
        except ValueError as e:
            raise ValueError(f"TCP解析错误: {str(e)}")

    @staticmethod
    def _parse_ws(line: str) -> dict:
        """解析WebSocket协议链接
        格式：ws://server:port?host=host&path=path#name
        """
        try:
            parsed = urlparse(line)
            server, port = parsed.netloc.split(':')
            query = parse_qs(parsed.query)
            return {
                'type': 'ws',
                'name': unquote(parsed.fragment) if parsed.fragment else '未命名节点',
                'server': server,
                'port': port,
                'host': query.get('host', [''])[0],
                'path': query.get('path', ['/'])[0]
            }
        except ValueError as e:
            raise ValueError(f"WebSocket解析错误: {str(e)}")

    @staticmethod
    def _parse_ssr(line: str) -> dict:
        """解析ShadowsocksR协议链接
        格式：ssr://base64(server:port:protocol:method:obfs:password_base64/?params)
        """
        try:
            encoded = line[6:]  # 去掉开头的"ssr://"
            decoded = base64.b64decode(encoded).decode('utf-8')
            server_info, params = decoded.split('/?', 1)
            server, port, protocol, method, obfs, password = server_info.split(':')
            query = parse_qs(params)
            return {
                'type': 'ssr',
                'name': base64.b64decode(query.get('remarks', [''])[0]).decode() if 'remarks' in query else '未命名节点',
                'server': server,
                'port': port,
                'protocol': protocol,
                'cipher': method,
                'obfs': obfs,
                'password': base64.b64decode(password).decode(),
                'obfs_param': base64.b64decode(query.get('obfsparam', [''])[0]).decode() if 'obfsparam' in query else '',
                'protocol_param': base64.b64decode(query.get('protoparam', [''])[0]).decode() if 'protoparam' in query else '',
                'group': base64.b64decode(query.get('group', [''])[0]).decode() if 'group' in query else ''
            }
        except (binascii.Error, ValueError) as e:
            raise ValueError(f"SSR解析错误: {str(e)}")

    @staticmethod
    def _parse_grpc(line: str) -> dict:
        """解析gRPC协议链接
        格式：grpc://uuid@server:port?serviceName=serviceName&security=security#name
        """
        try:
            parsed = urlparse(line)
            uuid, server_port = parsed.netloc.split('@')
            server, port = server_port.split(':')
            query = parse_qs(parsed.query)
            return {
                'type': 'grpc',
                'name': unquote(parsed.fragment) if parsed.fragment else '未命名节点',
                'server': server,
                'port': port,
                'uuid': uuid,
                'serviceName': query.get('serviceName', [''])[0],
                'security': query.get('security', ['none'])[0]
            }
        except ValueError as e:
            raise ValueError(f"gRPC解析错误: {str(e)}")

    @staticmethod
    def _parse_httpupgrade(line: str) -> dict:
        """解析HTTP Upgrade协议链接
        格式：httpupgrade://server:port?host=host&path=path#name
        """
        try:
            parsed = urlparse(line)
            server, port = parsed.netloc.split(':')
            query = parse_qs(parsed.query)
            return {
                'type': 'httpupgrade',
                'name': unquote(parsed.fragment) if parsed.fragment else '未命名节点',
                'server': server,
                'port': port,
                'host': query.get('host', [''])[0],
                'path': query.get('path', ['/'])[0]
            }
        except ValueError as e:
            raise ValueError(f"HTTP Upgrade解析错误: {str(e)}")
    
class FileGenerator:
    
    @staticmethod
    def save_results(node_results, output_dir='output'):
        """保存结果到文件"""
        try:
            logger.info(f"开始保存节点结果到目录: {output_dir}")
            os.makedirs(output_dir, exist_ok=True)
            logger.debug(f"已创建/确认输出目录: {os.path.abspath(output_dir)}")

            clash_config = {'proxies': []}
            v2rayn_lines = []
            node_counter = {}

            # 处理节点统计
            total_nodes = len(node_results.get('nodes', []))
            logger.debug(f"需要处理的节点总数: {total_nodes}")

            for index, node in enumerate(node_results.get('nodes', []), 1):
                FileGenerator._process_node(node, clash_config, v2rayn_lines, node_counter)
                if index % 500 == 0:  # 每50个节点记录进度
                    logger.debug(f"节点处理进度: {index}/{total_nodes}")

            # 写入文件
            logger.info("开始写入输出文件...")

            # 判断是否需要分成多份
            if len(clash_config['proxies']) > 5000 or len(v2rayn_lines) > 5000:
                logger.debug("节点数量超过 5000，开始分成多份保存")
                FileGenerator._write_split_files(output_dir, clash_config, v2rayn_lines, 5000)
            
            FileGenerator._write_files(output_dir, clash_config, v2rayn_lines)

            logger.info(f"成功生成订阅文件，总节点数: {len(v2rayn_lines)}")
            logger.debug(f"节点类型分布: {node_counter}")

            return {
                'success': True,
                'files': [
                    os.path.join(output_dir, 'subscription.txt'),
                    os.path.join(output_dir, 'clash_config.yaml')
                ],
                'node_counts': node_counter
            }
        except Exception as e:
            logger.error(f"保存结果时发生严重错误: {str(e)}", exc_info=True)
            return {'success': False, 'message': str(e)}

    @staticmethod
    def _write_split_files(output_dir, clash_config, v2rayn_lines, chunk_size):
        """将节点按指定大小分成多份并写入文件"""
        try:
            # 按指定大小分割数据
            def split_into_chunks(data, chunk_size):
                return [data[i:i + chunk_size] for i in range(0, len(data), chunk_size)]

            clash_chunks = split_into_chunks(clash_config['proxies'], chunk_size)
            v2rayn_chunks = split_into_chunks(v2rayn_lines, chunk_size)

            # 写入分割后的文件
            for i, (clash_part, v2rayn_part) in enumerate(zip(clash_chunks, v2rayn_chunks), 1):
                # 写入 v2rayn 文件
                txt_path = os.path.abspath(os.path.join(output_dir, f'subscription_{i}.txt'))
                with open(txt_path, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(v2rayn_part))
                    logger.debug(f"v2rayN订阅文件写入成功: subscription_{i}.txt，文件大小: {os.path.getsize(txt_path)}字节，节点数: {len(v2rayn_part)}")

                # 写入 Clash 配置文件
                yaml_path = os.path.abspath(os.path.join(output_dir, f'clash_config_{i}.yaml'))
                clash_config_part = {'proxies': clash_part}
                with open(yaml_path, 'w', encoding='utf-8') as f:
                    yaml.safe_dump(clash_config_part, f, allow_unicode=True, sort_keys=False)
                    logger.debug(f"Clash配置文件写入成功: clash_config_{i}.yaml，文件大小: {os.path.getsize(yaml_path)}字节，节点数: {len(clash_part)}")

        except IOError as e:
            logger.error(f"文件写入失败: {str(e)}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"写入文件时发生未知错误: {str(e)}", exc_info=True)
            raise
            
    @staticmethod
    def _process_node(node, clash_config, v2rayn_lines, node_counter):
        """处理单个节点"""
        try:
            node_type = node['data'].get('type', 'unknown').lower()
            node_name = node['data'].get('name', 'unnamed')
            logger.debug(f"处理节点: [类型]{node_type} [名称]{node_name}")

            # 统计节点类型
            node_counter[node_type] = node_counter.get(node_type, 0) + 1

            # 原始文本处理
            if node['source_type'] == 'text' and 'raw' in node['data']:
                v2rayn_lines.append(node['data']['raw'])
                logger.debug(f"添加原始文本节点: {node['data']['raw'][:50]}...")
            else:
                # 生成URI
                uri = FileGenerator._generate_uri(node['data'])
                if uri:
                    v2rayn_lines.append(uri)
                    logger.debug(f"生成URI成功: {uri[:50]}...")
                else:
                    logger.debug(f"无法生成URI: {node_type}节点 {node_name}")

            # 生成Clash配置
            clash_proxy = FileGenerator._convert_to_clash(node['data'])
            if clash_proxy:
                clash_config['proxies'].append(clash_proxy)
                logger.debug(f"添加Clash配置: {clash_proxy.get('name')}")
            else:
                logger.debug(f"无法生成Clash配置: {node_type}节点 {node_name}")
                
        except KeyError as e:
            logger.error(f"节点数据缺少必要字段: {str(e)}", exc_info=True)
        except Exception as e:
            logger.error(f"处理节点时发生意外错误: {str(e)}", exc_info=True)

    @staticmethod
    def _generate_uri(node_data):
        """生成标准URI"""
        try:
            node_type = node_data.get('type')
            node_name = node_data.get('name', 'unnamed')
            logger.debug(f"开始生成URI: [类型]{node_type} [名称]{node_name}")

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
            
            elif node_type == 'vless':
                # vless://uuid@server:port?params#name
                uuid = node_data.get('uuid', '')
                server = node_data.get('server', '')
                port = node_data.get('port', '')
                name = quote(node_data.get('name', ''))
                security = node_data.get('security', 'none')
                sni = node_data.get('sni', '')
                flow = node_data.get('flow', '')
                network = node_data.get('network', 'tcp')
                host = node_data.get('host', '')
                path = node_data.get('path', '/')

                # 构建查询参数
                query_params = []
                if security:
                    query_params.append(f"security={security}")
                if sni:
                    query_params.append(f"sni={sni}")
                if flow:
                    query_params.append(f"flow={flow}")
                if network:
                    query_params.append(f"type={network}")
                if host:
                    query_params.append(f"host={host}")
                if path:
                    query_params.append(f"path={path}")

                query = '&'.join(query_params)
                return f"vless://{uuid}@{server}:{port}?{query}#{name}"

            elif node_type == 'hysteria2':
                # hysteria2://server:port?protocol=protocol&auth=auth&obfs=obfs&peer=peer#name
                server = node_data.get('server', '')
                port = node_data.get('port', '')
                name = quote(node_data.get('name', ''))
                protocol = node_data.get('protocol', 'udp')  # 默认协议为 udp
                auth = node_data.get('auth', '')  # 认证信息
                obfs = node_data.get('obfs', '')  # 混淆信息
                peer = node_data.get('peer', '')  # TLS peer 名称

                # 构建查询参数
                query_params = []
                if protocol:
                    query_params.append(f"protocol={protocol}")
                if auth:
                    query_params.append(f"auth={auth}")
                if obfs:
                    query_params.append(f"obfs={obfs}")
                if peer:
                    query_params.append(f"peer={peer}")

                query = '&'.join(query_params)
                return f"hysteria2://{server}:{port}?{query}#{name}"
            
            elif node_type == 'tcp':
                # tcp://server:port#name
                server = node_data.get('server', '')
                port = node_data.get('port', '')
                name = quote(node_data.get('name', ''))
                return f"tcp://{server}:{port}#{name}"

            elif node_type == 'ws':
                # ws://server:port?host=host&path=path#name
                server = node_data.get('server', '')
                port = node_data.get('port', '')
                name = quote(node_data.get('name', ''))
                host = node_data.get('host', '')
                path = node_data.get('path', '/')

                # 构建查询参数
                query_params = []
                if host:
                    query_params.append(f"host={host}")
                if path:
                    query_params.append(f"path={path}")

                query = '&'.join(query_params)
                return f"ws://{server}:{port}?{query}#{name}"

            elif node_type == 'ssr':
                # ssr://base64(server:port:protocol:method:obfs:password_base64/?params)
                server = node_data.get('server', '')
                port = node_data.get('port', '')
                protocol = node_data.get('protocol', 'origin')
                method = node_data.get('cipher', 'aes-256-cfb')
                obfs = node_data.get('obfs', 'plain')
                password = base64.b64encode(node_data.get('password', '').encode()).decode()
                name = quote(node_data.get('name', ''))
                
                # 构建 SSR 链接的参数部分
                params = []
                obfs_param = node_data.get('obfs_param', '')
                if obfs_param:
                    params.append(f"obfsparam={base64.b64encode(obfs_param.encode()).decode()}")
                protocol_param = node_data.get('protocol_param', '')
                if protocol_param:
                    params.append(f"protoparam={base64.b64encode(protocol_param.encode()).decode()}")
                remarks = base64.b64encode(node_data.get('name', '').encode()).decode()
                group = base64.b64encode(node_data.get('group', '').encode()).decode()
                params.append(f"remarks={remarks}")
                params.append(f"group={group}")
                
                # 拼接参数部分
                params_str = '&'.join(params)
                
                # 构建完整的 SSR URI
                ssr_uri = f"{server}:{port}:{protocol}:{method}:{obfs}:{password}/?{params_str}"
                encoded_ssr_uri = base64.b64encode(ssr_uri.encode()).decode()
                return f"ssr://{encoded_ssr_uri}"
            
            elif node_type == 'grpc':
                # grpc://uuid@server:port?serviceName=serviceName&security=security#name
                uuid = node_data.get('uuid', '')
                server = node_data.get('server', '')
                port = node_data.get('port', '')
                name = quote(node_data.get('name', ''))
                service_name = node_data.get('serviceName', '')
                security = node_data.get('security', 'none')

                # 构建查询参数
                query_params = []
                if service_name:
                    query_params.append(f"serviceName={service_name}")
                if security:
                    query_params.append(f"security={security}")

                query = '&'.join(query_params)
                return f"grpc://{uuid}@{server}:{port}?{query}#{name}"

            elif node_type == 'httpupgrade':
                # httpupgrade://server:port?host=host&path=path#name
                server = node_data.get('server', '')
                port = node_data.get('port', '')
                name = quote(node_data.get('name', ''))
                host = node_data.get('host', '')
                path = node_data.get('path', '/')

                # 构建查询参数
                query_params = []
                if host:
                    query_params.append(f"host={host}")
                if path:
                    query_params.append(f"path={path}")

                query = '&'.join(query_params)
                return f"httpupgrade://{server}:{port}?{query}#{name}"
            
            else:
                logger.debug(f"未知节点类型: {node_type}")
                return None    
        
        except KeyError as e:
            logger.error(f"生成URI缺少必要字段: {node_type}节点 {node_name} - {str(e)}")
            return None
        except Exception as e:
            logger.warning(f"生成URI失败: {node_type}节点 {node_name} - {str(e)}")
            return None

    @staticmethod
    def _convert_to_clash(node_data):
        """转换为Clash配置"""
        try:
            node_type = node_data.get('type')
            node_name = node_data.get('name', 'unnamed')
            
            # 基础字段验证
            if not all(key in node_data for key in ['server', 'port']):
                logger.error(f"Clash配置缺少server/port字段: {node_type}节点 {node_name}")
                return None

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

            logger.debug(f"成功生成Clash配置: {base_proxy.get('name')}")
            return base_proxy
        
        except KeyError as e:
            logger.error(f"生成Clash配置缺少字段: {node_type}节点 {node_name} - {str(e)}")
            return None
        except Exception as e:
            logger.warning(f"生成Clash配置失败: {node_type}节点 {node_name} - {str(e)}")
            return None

    @staticmethod
    def _write_files(output_dir, clash_config, v2rayn_lines):
        """写入文件"""
        try:
            txt_path = os.path.abspath(os.path.join(output_dir, 'all_subscription.txt'))
            logger.debug(f"生成v2rayN订阅文件: {txt_path} ({len(v2rayn_lines)}节点)")
            
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(v2rayn_lines))
                logger.debug(f"v2rayN订阅文件写入成功: all_subscription.txt，文件大小: {os.path.getsize(txt_path)}字节，节点数: {len(v2rayn_lines)}")

            yaml_path = os.path.abspath(os.path.join(output_dir, 'all_clash_config.yaml'))
            logger.debug(f"生成Clash配置文件: {yaml_path} ({len(clash_config['proxies'])}节点)")
            
            with open(yaml_path, 'w', encoding='utf-8') as f:
                yaml.safe_dump(clash_config, f, allow_unicode=True, sort_keys=False)
                logger.debug(f"Clash配置文件写入成功: all_clash_config.yaml，文件大小: {os.path.getsize(yaml_path)}字节，节点数: {len(clash_config['proxies'])}")
                
            logger.debug(f"示例Clash节点: {clash_config['proxies'][0] if clash_config['proxies'] else '无'}") 
            logger.debug(f"示例订阅链接: {v2rayn_lines[0] if v2rayn_lines else '无'}")
            
        except IOError as e:
            logger.error(f"文件写入失败: {str(e)}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"写入文件时发生未知错误: {str(e)}", exc_info=True)
            raise