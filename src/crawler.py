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
# from .repo_manager import RepoManager
from .counters import FileCounter

logger = logging.getLogger("getnode")

# 配置常量
GITHUB_API_URL = "https://api.github.com/search/repositories"
MAX_RESULTS = 180
RESULTS_PER_PAGE = 30
SLEEP_INTERVAL = 1.2
MAX_RETRIES = 5
MAX_FILE_SIZE = 1024 * 1024 * 1.2  # 1.2MB
MAX_RECURSION_DEPTH = 3
PER_PAGE = 100
MAX_CONTENTS_TOTAL = 100

# 新增：时间限制（最近3个月）
DAYS_BACK = 90

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
            logger.info(f"已使用API次数: {cls.count}/小时")
            wait_time = 3600 - (current_time - cls.last_reset).seconds
            logger.warning(f"接近API限制，等待{wait_time}秒")
            time.sleep(wait_time)
            cls.last_reset = current_time
            cls.count = 0

        if cls.count % 100 == 0:
            logger.info(f"已使用API次数: {cls.count}/小时")
        elif cls.count > 4000:
            if cls.count % 50 == 0:
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
        """搜索仓库，增加热度与更新时间条件"""
        repos = []
        # 计算三个月前的日期
        since_date = (datetime.now() - timedelta(days=DAYS_BACK)).strftime("%Y-%m-%d")
        # 修改查询：包含关键词、stars>=50、最近3个月有更新
        query = "v2ray free in:readme,description stars:>=50 pushed:>={}".format(since_date)
        params = {
            "q": query,
            "sort": "updated",
            "order": "desc",
            "per_page": RESULTS_PER_PAGE
        }
        # repo_manager = RepoManager()
        page = 1

        try:
            # 查询验证
            if any(op in params["q"] for op in [" OR ", " AND ", " NOT "]):
                raise ValueError("搜索查询包含非法逻辑操作符")

            while len(repos) < MAX_RESULTS:
                params["page"] = page
                try:
                    data = self.safe_request(GITHUB_API_URL, params)
                    raw_repos = data.get("items", [])
                    
                    if not raw_repos:
                        logger.debug(f"第 {page} 页无数据，终止搜索")
                        break

                    for repo in raw_repos:
                        FileCounter.repo_total += 1
                        repos.append(repo)
                        if len(repos) >= MAX_RESULTS:
                            break

                    logger.debug(f"第 {page} 页处理完成，有效仓库数: {len(repos)}/{MAX_RESULTS}")
                    page += 1
                    time.sleep(SLEEP_INTERVAL)

                except requests.HTTPError as e:
                    if e.response.status_code == 422:
                        logger.error("GitHub API查询验证失败，请简化搜索条件")
                        break
                    raise

            logger.info(
                f"仓库搜索完成 | 总扫描仓库: {FileCounter.repo_total} "
                f"有效仓库: {FileCounter.repo_added} "
                f"跳过: {FileCounter.repo_total - FileCounter.repo_added}"
            )
            return repos

        except Exception as e:
            logger.error(f"仓库搜索失败: {str(e)}", exc_info=True)
            return []

    def find_node_files(self, repo_url: str) -> list:
        """递归查找节点文件，返回文件信息列表"""
        logger.debug(f"开始处理仓库: {repo_url}")
        repo_api_url = repo_url.replace("https://github.com/", "https://api.github.com/repos/")
        return self._search_contents(repo_api_url + "/contents/")

    def _search_contents(self, path: str, depth=0) -> list:
        """递归扫描目录，收集节点文件信息"""
        if depth > MAX_RECURSION_DEPTH:
            logger.debug(f"达到最大递归深度{depth}: {path}")
            return []
            
        node_files = []
        page = 1
        while True:
            try:
                logger.debug(f"扫描目录: {path} ")
                params = {"page": page, "per_page": PER_PAGE}
                contents = self.safe_request(path, params)
                
                if not isinstance(contents, list):
                    logger.debug(f"异常响应类型: {type(contents)}")
                    break

                if not contents:
                    logger.debug(f"空目录: {path}")
                    break

                if len(contents) > MAX_CONTENTS_TOTAL:
                    logger.debug(f"条目过多跳过：{path}\n 该目录条目数：{len(contents)}")
                    break

                for item in contents:
                    if not self._process_item(item, depth):
                        continue
                    
                    node_files.append({
                        "name": item["name"],
                        "url": item["html_url"],
                        "download_url": item["download_url"]
                    })
                    logger.debug(f"发现节点文件: {item['name']}")

                if len(contents) <= PER_PAGE:
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
        
        if not all(key in item for key in ['type', 'name', 'url', 'download_url']):
            logger.debug(f"字段缺失: {item.get('name')}")
            return False
            
        name = item["name"].lower()
        if name.startswith(('.', '_')):
            logger.debug(f"忽略系统文件: {name}")
            return False
            
        if item.get("size", 0) > MAX_FILE_SIZE:
            FileCounter.skipped += 1
            logger.debug(f"跳过 {item['size']/1024:.1f}KB 文件: {item.get('url')}")
            return False
            
        if item["type"] == "dir":
            dir_name = item["name"].strip()
            # 匹配6-8位纯数字（示例：202501 或 20250101）
            if re.fullmatch(r'\d{6,8}', dir_name):
                logger.debug(f"跳过时间数字目录: {dir_name}")
                return False
            
            logger.debug(f"进入子目录: {name}")
            self._search_contents(item["url"], depth+1)
            return False
        
        if not name:
            return False
            
        # 关键词匹配
        keyword_pattern = re.compile(r'v2ray|clash|node|proxy|sub|ss|trojan|conf|tls|ws|converted', re.IGNORECASE)
        if not keyword_pattern.search(name):
            return False
    
        parsed = urlparse(item["download_url"])
        scheme = parsed.scheme

        if isinstance(scheme, bytes):
            scheme = scheme.decode('utf-8')
        if not scheme.startswith('http'):
            logger.debug(f"非常用协议: {scheme}")
            return False
            
        return True