import os
import time
import requests
import json
import base64
import yaml
import logging
from datetime import datetime
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type
from typing import List, Dict
from urllib.parse import urlparse, unquote, quote
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
MAX_RESULTS = 210
RESULTS_PER_PAGE = 30
SLEEP_INTERVAL = 1.2
MAX_RETRIES = 5
NODE_KEYWORDS = ['v2ray', 'clash', 'subscribe', 'proxy', 'node', 'free', 'config']
MAX_FILE_SIZE = 1024 * 200  # 200KB

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
            "q": " OR ".join(NODE_KEYWORDS) + " in:readme,description",
            "sort": "updated",
            "order": "desc",
            "per_page": RESULTS_PER_PAGE
        }

        try:
            for page in range(1, (MAX_RESULTS // RESULTS_PER_PAGE) + 1):
                params["page"] = page
                data = self.safe_request(GITHUB_API_URL, params)
                repos.extend(data.get("items", []))
                time.sleep(SLEEP_INTERVAL)

                if len(repos) >= MAX_RESULTS:
                    break
        except Exception as e:
            logger.error(f"仓库搜索失败: {str(e)}", exc_info=True)

        return repos[:MAX_RESULTS]

    def find_node_files(self, repo_url: str) -> list:
        repo_api_url = repo_url.replace("https://github.com/", "https://api.github.com/repos/")
        return self._search_contents(repo_api_url + "/contents/")

    def _search_contents(self, path: str) -> list:
        try:
            contents = self.safe_request(path, {})
            node_files = []

            for item in contents:
                if not isinstance(item, dict):
                    logger.warning(f"异常响应内容: {item}")
                    continue
                
                if item.get("size", 0) > MAX_FILE_SIZE:
                    logger.debug(f"跳过过大文件: {item.get('name')}")
                    continue

                if item.get("type") == "dir":
                    node_files.extend(self._search_contents(item["url"]))
                else:
                    name = item.get("name", "").lower()
                    download_url = item.get("download_url", "")
                    
                    if not download_url.startswith("http"):
                        continue
                    
                    if any(kw in name for kw in NODE_KEYWORDS) and \
                       name.endswith((".yaml", ".yml", ".txt", ".json")):
                        node_files.append({
                            "name": item["name"],
                            "url": item["html_url"],
                            "download_url": download_url
                        })
            return node_files
        except Exception as e:
            logger.error(f"搜索目录失败 {path}: {str(e)}", exc_info=True)
            return []

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
    def _add_nodes(result, seen, nodes, url, source_type):
        for node in nodes:
            node_hash = hashlib.md5(json.dumps(node, sort_keys=True).encode()).hexdigest()
            if node_hash not in seen:
                seen.add(node_hash)
                result['nodes'].append({
                    'source_type': source_type,
                    'url': url,
                    'data': node
                })

    @staticmethod
    def _parse_clash_config(url):
        # 实现与之前相同的Clash解析逻辑
        pass
    
    @staticmethod
    def _parse_txt_config(url):
        # 实现与之前相同的文本解析逻辑
        pass

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
