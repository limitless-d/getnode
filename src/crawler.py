import os
import re
import time
import requests
import json
import logging
from datetime import datetime, timedelta
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type
from urllib.parse import urlparse
from typing import Dict
from .counters import FileCounter

logger = logging.getLogger("getnode")

# 配置常量
GITHUB_API_URL = "https://api.github.com/search/repositories"
MAX_RESULTS = 50
RESULTS_PER_PAGE = 30
SLEEP_INTERVAL = 1.2
MAX_RETRIES = 5
MAX_FILE_SIZE = 1024 * 1024 * 1.2  # 1.2MB
MAX_RECURSION_DEPTH = 3
PER_PAGE = 100
MAX_CONTENTS_TOTAL = 100
DAYS_BACK = 90  # 最近3个月

class APICounter:
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
            logger.info(f"已使用API次数: {cls.count}/小时")
            wait_time = 3600 - (current_time - cls.last_reset).seconds
            logger.warning(f"接近API限制，等待{wait_time}秒")
            time.sleep(wait_time)
            cls.last_reset = current_time
            cls.count = 0
        if cls.count % 100 == 0:
            logger.info(f"已使用API次数: {cls.count}/小时")
        elif cls.count > 4000 and cls.count % 50 == 0:
            logger.info(f"API调用次数: {cls.count}/小时")
                
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
        """搜索仓库（全量模式，不依赖repo_manager）"""
        repos = []
        since_date = (datetime.now() - timedelta(days=DAYS_BACK)).strftime("%Y-%m-%d")
        query = "v2ray free in:readme,description stars:>=50 pushed:>={}".format(since_date)
        params = {
            "q": query,
            "sort": "updated",
            "order": "desc",
            "per_page": RESULTS_PER_PAGE
        }
        page = 1
        try:
            while len(repos) < MAX_RESULTS:
                params["page"] = page
                data = self.safe_request(GITHUB_API_URL, params)
                raw_repos = data.get("items", [])
                if not raw_repos:
                    break
                for repo in raw_repos:
                    FileCounter.repo_total += 1
                    repos.append(repo)
                    if len(repos) >= MAX_RESULTS:
                        break
                page += 1
                time.sleep(SLEEP_INTERVAL)
            logger.info(f"仓库搜索完成，共 {len(repos)} 个仓库")
            return repos
        except Exception as e:
            logger.error(f"仓库搜索失败: {str(e)}", exc_info=True)
            return []

    def find_node_files(self, repo_url: str) -> list:
        logger.debug(f"开始处理仓库: {repo_url}")
        repo_api_url = repo_url.replace("https://github.com/", "https://api.github.com/repos/")
        return self._search_contents(repo_api_url + "/contents/")

    def _search_contents(self, path: str, depth=0) -> list:
        node_files = []
        page = 1
        while True:
            try:
                logger.debug(f"扫描目录: {path} ")
                params = {"page": page, "per_page": PER_PAGE}
                contents = self.safe_request(path, params)
                if not isinstance(contents, list):
                    break
                if not contents:
                    break
                if len(contents) > MAX_CONTENTS_TOTAL:
                    logger.debug(f"条目过多跳过：{path}\n 该目录条目数：{len(contents)}")
                    break

                for item in contents:
                    if self._process_item(item, depth):
                        node_files.append({
                            "name": item["name"],
                            "url": item["html_url"],
                            "download_url": item["download_url"]
                        })
                        logger.debug(f"发现有效节点文件: {item['name']}")

                if len(contents) <= PER_PAGE:
                    break
                page += 1
                time.sleep(SLEEP_INTERVAL)
            except Exception as e:
                logger.error(f"处理异常: {str(e)}", exc_info=True)
                break
        return node_files

    def _process_item(self, item, depth) -> bool:
        """处理单个目录项，返回是否有效节点文件（增加内容验证）"""
        FileCounter.total += 1

        # 字段完整性检查
        if not all(key in item for key in ['type', 'name', 'url', 'download_url']):
            return False

        name = item["name"].lower()
        if name.startswith(('.', '_')):
            return False

        # 大小过滤
        if item.get("size", 0) > MAX_FILE_SIZE:
            FileCounter.skipped += 1
            return False

        # 目录递归
        if item["type"] == "dir":
            dir_name = item["name"].strip()
            if re.fullmatch(r'\d{6,8}', dir_name):
                return False
            self._search_contents(item["url"], depth + 1)
            return False

        # 文件扩展名/关键词过滤
        if not name:
            return False
        keyword_pattern = re.compile(r'v2ray|clash|node|proxy|sub|ss|trojan|conf|tls|ws|converted', re.IGNORECASE)
        if not keyword_pattern.search(name):
            return False

        # 验证下载链接协议
        parsed = urlparse(item["download_url"])
        if not parsed.scheme.startswith('http'):
            return False

        # 内容验证：下载前几KB并检查节点特征
        download_url = item["download_url"]
        try:
            r = requests.get(download_url, timeout=8, stream=True)
            if r.status_code != 200:
                return False
            content_chunk = ''
            for chunk in r.iter_content(chunk_size=512):
                if chunk:
                    content_chunk += chunk.decode('utf-8', errors='ignore')
                    if len(content_chunk) > 2048:
                        break
            if not self._looks_like_node_config(content_chunk):
                logger.debug(f"内容验证失败: {item['name']}")
                return False
        except Exception as e:
            logger.debug(f"下载验证失败 {download_url}: {e}")
            return False

        return True

    def _looks_like_node_config(self, content: str) -> bool:
        """简单判断内容是否像节点配置文件"""
        if len(content) < 50:
            return False
        content_lower = content.lower()
        patterns = [
            r'proxies:',           # clash 配置
            r'vmess://', r'ss://', r'trojan://', r'vless://', r'ssr://',  # 协议链接
            r'- name:',           # clash 节点名
            r'server:',           # 通用节点字段
            r'port:',
            r'type:',
            r'uuid:',
            r'password:',
            r'method:',
            r'cipher:',
        ]
        return any(re.search(p, content_lower) for p in patterns)