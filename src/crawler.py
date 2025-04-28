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
MAX_RESULTS = 60
RESULTS_PER_PAGE = 30
SLEEP_INTERVAL = 1.2
MAX_RETRIES = 5
MAX_FILE_SIZE = 1024 * 512  # 500KB

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
    totol = 0
    skipped = 0

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
        if depth > 5:
            logger.warning(f"达到最大递归深度: {path}")
            return []
            
        node_files = []
        page = 1
        while True:
            try:
                logger.debug(f"处理目录: {path} [第{page}页]")
                params = {"page": page, "per_page": 100}
                contents = self.safe_request(path, params)
                
                if not isinstance(contents, list):
                    logger.warning(f"异常目录响应: {contents}")
                    break
                    
                if not contents:
                    logger.debug(f"空目录: {path}")
                    break

                for item in contents:
                    logger.debug(f"处理条目: {item.get('name')}")
                    FileCounter.total += 1  # 总文件数+1

                    # 文件大小过滤
                    if item.get("size", 0) > MAX_FILE_SIZE:
                        FileCounter.skipped += 1  # 跳过计数+1
                        logger.debug(f"跳过大文件（{item.get('size',0)/1024:.1f}KB）: {item.get('name','')}")
                        continue
                    
                    # 目录递归
                    if item.get("type") == "dir":
                        node_files.extend(self._search_contents(item["url"], depth+1))
                        continue
                    
                    # 文件处理
                    name = item.get("name", "").lower()
                    download_url = item.get("download_url", "")
                    
                    if not download_url.startswith("http"):
                        logger.debug(f"无效下载链接: {download_url}")
                        continue
                        
                    if "v2ray free" in name and name.endswith((".yaml", ".yml", ".txt", ".json")):
                        logger.info(f"发现节点文件: {name}")
                        node_files.append({
                            "name": item["name"],
                            "url": item["html_url"],
                            "download_url": download_url
                        })
                
                # 检查是否还有下一页
                if len(contents) < 100:
                    break
                page += 1
                time.sleep(0.5)  # 添加页间延迟
                
            except Exception as e:
                logger.error(f"目录处理异常: {str(e)}")
                break
                
        return node_files

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
