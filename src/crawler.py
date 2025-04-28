import os
import re
import time
import requests
import json
import base64
import binascii
import yaml
import logging
from datetime import datetime
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type
from collections import OrderedDict
from typing import List, Dict
from urllib.parse import urlparse
import hashlib

# 配置日志系统
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('crawler.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 配置常量
GITHUB_API_URL = "https://api.github.com/search/repositories"
MAX_RESULTS = 30
RESULTS_PER_PAGE = 30
SLEEP_INTERVAL = 1.2
MAX_RETRIES = 5
MAX_FILE_SIZE = 1024 * 512  # 500KB
MAX_RECURSION_DEPTH = 1
PER_PAGE = 100
NODE_KEYWORDS = ['v2ray', 'subscribe', 'clash', 'sub', 'config', 'vless', 'vmess']  # 节点文件关键词

class APICounter:
    """API调用计数器"""
    count = 0
    last_reset = datetime.now()

    @classmethod
    def check_limit(cls):
        current_time = datetime.now()
        if (current_time - cls.last_reset).seconds >= 3590:
            cls.count = 0
            cls.last_reset = current_time
        
        cls.count += 1
        if cls.count >= 4800:
            wait_time = 3600 - (current_time - cls.last_reset).seconds
            logger.warning(f"接近API限制，等待{wait_time}秒")
            time.sleep(wait_time)
            cls.last_reset = current_time
            cls.count = 0

        if cls.count % 10 == 0:  # 新增监控日志
            logger.info(f"已使用API次数: {cls.count}/小时")

class FileCounter:
    total = 0
    skipped = 0
    total_nodes = 0
    dup_nodes = 0
    total_links = 0

class GitHubCrawler:
    def __init__(self):
        self.token = os.getenv("CRAWLER_GITHUB_TOKEN")
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github.v3+json"
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    @retry(wait=wait_exponential(multiplier=1, max=20), 
           stop=stop_after_attempt(MAX_RETRIES),
           retry=retry_if_exception_type((requests.HTTPError, json.JSONDecodeError)))
    def safe_request(self, url: str, params: Dict) -> Dict:
        APICounter.check_limit()
        try:
            response = self.session.get(url, params=params, timeout=20)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP Error {response.status_code}: {response.text[:200]}")
            if response.status_code == 403:
                reset_time = int(response.headers.get('X-RateLimit-Reset', 0))
                sleep_time = max(reset_time - time.time(), 60)
                logger.warning(f"触发速率限制，等待{sleep_time}秒")
                time.sleep(sleep_time)
            raise

    def search_repos(self) -> list:
        repos = []
        params = {
            "q": "v2ray free in:readme,description",  # 使用单一关键词
            "sort": "updated",
            "order": "desc",
            "per_page": RESULTS_PER_PAGE
        }

        try:
            # 添加查询验证
            if any(op in params["q"] for op in [" OR ", " AND ", " NOT "]):
                raise ValueError("搜索查询包含非法逻辑操作符")
            
            for page in range(1, (MAX_RESULTS // RESULTS_PER_PAGE) + 1):
                params["page"] = page
                try:
                    data = self.safe_request(GITHUB_API_URL, params)
                    repos.extend(data.get("items", []))
                    time.sleep(SLEEP_INTERVAL)
                except requests.HTTPError as e:
                    if e.response.status_code == 422:
                        logger.error("GitHub API查询验证失败，请简化搜索条件")
                        break
                    raise

                if len(repos) >= MAX_RESULTS:
                    break
        except Exception as e:
            logger.error(f"仓库搜索失败: {str(e)}", exc_info=True)

        return repos

    def find_node_files(self, repo_url: str) -> list:
        logger.info(f"开始处理仓库: {repo_url}")  # 新增日志
        repo_api_url = repo_url.replace("https://github.com/", "https://api.github.com/repos/")
        return self._search_contents(repo_api_url + "/contents/")

    def _search_contents(self, path: str, depth=0) -> list:
        if depth > MAX_RECURSION_DEPTH:
            logger.warning(f"达到最大递归深度{depth}: {path}")
            return []
            
        node_files = []
        page = 1
        while True:
            try:
                logger.debug(f"扫描目录: {path} [第{page}页]")
                params = {"page": page, "per_page": PER_PAGE}
                contents = self.safe_request(path, params)
                
                if not isinstance(contents, list):
                    logger.warning(f"异常响应类型: {type(contents)}")
                    break
                    
                if not contents:
                    logger.debug(f"空目录: {path}")
                    break

                for item in contents:
                    if not self._process_item(item, depth):
                        continue
                    
                    node_files.append({
                        "name": item["name"],
                        "url": item["html_url"],
                        "download_url": item["download_url"]
                    })
                    FileCounter.total_links += 1
                    logger.info(f"发现节点文件: {item['name']}")

                if len(contents) < PER_PAGE:
                    break
                page += 1
                time.sleep(SLEEP_INTERVAL)
                
            except requests.HTTPError as e:
                logger.error(f"API请求失败[{e.status_code}]: {path}")
                break
            except Exception as e:
                logger.error(f"处理异常: {str(e)}", exc_info=True)
                break
                
        return node_files

    def _process_item(self, item, depth) -> bool:
        """处理单个目录项，返回是否有效节点文件"""
        FileCounter.total += 1
        
        # 验证基础字段
        if not all(key in item for key in ['type', 'name', 'url', 'download_url']):
            logger.debug(f"字段缺失: {item.get('name')}")
            return False
            
        # 过滤特殊文件
        name = item["name"].lower()
        if name.startswith(('.', '_')):
            logger.debug(f"忽略系统文件: {name}")
            return False
            
        # 文件大小过滤
        if item.get("size", 0) > MAX_FILE_SIZE:
            FileCounter.skipped += 1
            logger.debug(f"跳过 {item['size']/1024:.1f}KB 文件: {name}")
            return False
            
        # 目录递归
        if item["type"] == "dir":
            logger.debug(f"进入子目录: {name}")
            self._search_contents(item["url"], depth+1)
            return False
            
        # 文件类型过滤
        if not name.endswith((".yaml", ".yml", ".txt")):
            return False
            
        # 关键词匹配
        keyword_pattern = re.compile(r'v2ray|clash|node|proxy|sub|vless|vmess', re.IGNORECASE)
        if not keyword_pattern.search(name):
            return False
            
        # 验证下载链接
        parsed = urlparse(item["download_url"])
        if not parsed.scheme.startswith('http'):
            logger.debug(f"非常用协议: {parsed.scheme}")
            return False
            
        return True


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
                
                # 尝试解析为Clash配置
                clash_result = NodeProcessor._parse_clash_config(url)
                if clash_result['success']:
                    result['success_count'] += 1
                    NodeProcessor._add_nodes(result, seen, clash_result['data'], url, 'clash')
                    continue
                
                # 尝试解析为文本节点
                txt_result = NodeProcessor._parse_txt_config(url)
                if txt_result['success']:
                    result['success_count'] += 1
                    NodeProcessor._add_nodes(result, seen, txt_result['data'], url, 'text')
                    continue

                # 新增：尝试解析为Base64编码内容
                base64_result = NodeProcessor._parse_base64_config(url)
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
    def _parse_base64_config(url: str, depth=0, is_content=False) -> Dict:
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
            # 获取原始内容
            if is_content:
                encoded_content = url  # 直接使用传入的内容
            else:
                response = requests.get(url, timeout=15)
                response.raise_for_status()
                encoded_content = response.text.strip()

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
                    is_content=True    # 标记为内容模式
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
        """解析Clash配置内容（非URL）"""
        result = {'success': False, 'data': []}
        try:
            config = yaml.safe_load(content)
            proxies = config.get('proxies', [])
            result['data'] = proxies
            result['success'] = True
        except yaml.YAMLError as e:
            logger.error(f"Clash内容解析失败: {str(e)}")
        return result

    @staticmethod
    def _parse_txt_content(content: str) -> Dict:
        """解析纯文本内容（非URL）"""
        result = {'success': False, 'data': []}
        nodes = []
        
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
                
            # 尝试解析为各种协议
            node = NodeProcessor._parse_single_line(line)
            if node:
                nodes.append(node)
                
        if nodes:
            result['success'] = True
            result['data'] = nodes
            
        return result

    @staticmethod
    def _add_nodes(result, seen, nodes, url, source_type):
        for node in nodes:
            # 新增：提取关键特征生成唯一指纹
            node_fingerprint = NodeProcessor._generate_fingerprint(node)

            FileCounter.total_nodes += 1
            if node_fingerprint in seen:
                FileCounter.dup_nodes += 1

            if node_fingerprint not in seen:
                seen.add(node_fingerprint)
                result['nodes'].append({
                    'source_type': source_type,
                    'url': url,
                    'data': node
                })
            else:
                logger.debug(f"发现重复节点: {NodeProcessor._get_node_identity(node)}")
        logger.info(f"去重统计: 总发现节点={FileCounter.total_nodes} 重复节点={FileCounter.dup_nodes}")

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
        # URI生成逻辑
        pass

    @staticmethod
    def _convert_to_clash(node_data):
        # Clash配置转换逻辑
        pass

    @staticmethod
    def _write_files(output_dir, clash_config, v2rayn_lines):
        txt_path = os.path.join(output_dir, 'subscription.txt')
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(v2rayn_lines))

        yaml_path = os.path.join(output_dir, 'clash_config.yaml')
        with open(yaml_path, 'w', encoding='utf-8') as f:
            yaml.safe_dump(clash_config, f, allow_unicode=True, sort_keys=False)
