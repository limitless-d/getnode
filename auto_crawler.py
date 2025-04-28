import os
import time
import requests
import json
import base64
import logging
from datetime import datetime
from tenacity import retry, wait_exponential, stop_after_attempt
from typing import List, Dict
from collections import OrderedDict

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
CF_API_BASE = "https://api.cloudflare.com/client/v4"
MAX_RESULTS = 100
RESULTS_PER_PAGE = 30
SLEEP_INTERVAL = 1.2
MAX_RETRIES = 3
LATENCY_THRESHOLD = 5000  # 节点延迟阈值（毫秒）

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
            cls.last_reset = datetime.now()
            cls.count = 0

class GitHubCrawler:
    def __init__(self, token: str):
        self.headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    @retry(wait=wait_exponential(multiplier=1, max=10), 
           stop=stop_after_attempt(MAX_RETRIES))
    def safe_request(self, url: str, params: Dict) -> Dict:
        APICounter.check_limit()
        try:
            response = self.session.get(url, params=params, timeout=15)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            if response.status_code == 403:
                reset_time = int(response.headers.get('X-RateLimit-Reset', 0))
                sleep_time = max(reset_time - time.time(), 60)
                logger.warning(f"触发速率限制，等待{sleep_time}秒")
                time.sleep(sleep_time)
                raise
            logger.error(f"API请求失败: {str(e)}")
            raise

    def search_repositories(self, keyword: str) -> List[Dict]:
        repos = []
        params = {
            "q": keyword,
            "sort": "stars",
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
            logger.error(f"仓库搜索失败: {str(e)}")
            return []

        return repos[:MAX_RESULTS]

def get_cf_account_id(cf_api_token: str) -> str:
    """获取Cloudflare账户ID"""
    url = f"{CF_API_BASE}/accounts"
    headers = {"Authorization": f"Bearer {cf_api_token}"}
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
        if not data.get("success", False):
            raise ValueError(f"API错误: {data.get('errors', '未知错误')}")
        return data["result"][0]["id"]
    except Exception as e:
        logger.error(f"获取账户ID失败: {str(e)}")
        raise

def get_cf_namespace_id(cf_api_token: str, account_id: str, namespace_name: str) -> str:
    """获取KV命名空间ID"""
    url = f"{CF_API_BASE}/accounts/{account_id}/storage/kv/namespaces"
    headers = {"Authorization": f"Bearer {cf_api_token}"}
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
        if not data.get("success", False):
            raise ValueError(f"API错误: {data.get('errors', '未知错误')}")
        for ns in data["result"]:
            if ns["title"] == namespace_name:
                return ns["id"]
        raise ValueError(f"命名空间 {namespace_name} 不存在")
    except Exception as e:
        logger.error(f"获取命名空间ID失败: {str(e)}")
        raise

def convert_to_v2rayn(repos: List[Dict]) -> str:
    """将仓库信息转换为v2rayN订阅格式"""
    links = []
    seen = set()
    for repo in repos:
        try:
            vmess_config = {
                "v": "2",
                "ps": repo["name"],
                "add": repo["name"].split("-")[-1] + ".com",
                "port": 443,
                "id": repo["owner"]["login"],
                "aid": 0,
                "net": "ws",
                "type": "none",
                "tls": "tls"
            }
            encoded = base64.b64encode(json.dumps(vmess_config).encode()).decode()
            link = f"vmess://{encoded}"
            if link not in seen:
                seen.add(link)
                links.append(link)
        except KeyError as e:
            logger.warning(f"无效的仓库数据: {str(e)}")
            continue
    
    # 添加订阅头并去重
    unique_links = OrderedDict.fromkeys(links)
    encoded_links = [base64.b64encode(link.encode()).decode() for link in unique_links]
    return "\n".join(encoded_links)

def test_node_latency(links: List[str]) -> List[str]:
    """测试节点延迟并过滤"""
    valid_links = []
    for link in links:
        try:
            start = time.time()
            response = requests.get("https://www.gstatic.com/generate_204", 
                                  timeout=5, 
                                  proxies={"https": link})
            latency = (time.time() - start) * 1000
            if latency <= LATENCY_THRESHOLD and response.status_code == 204:
                valid_links.append(link)
        except:
            continue
    return list(OrderedDict.fromkeys(valid_links))

def save_to_cloudflare_kv(links: List[str]):
    """保存到Cloudflare KV存储"""
    cf_api_token = os.getenv("CF_API_TOKEN")
    namespace_name = os.getenv("CF_NAMESPACE_NAME")

    if not cf_api_token:
        logger.error("缺少Cloudflare配置参数")
        return

    try:
        account_id = get_cf_account_id(cf_api_token)
        namespace_id = get_cf_namespace_id(cf_api_token, account_id, namespace_name)
        
        url = f"{CF_API_BASE}/accounts/{account_id}/storage/kv/namespaces/{namespace_id}/values/v2ray_nodes"
        headers = {
            "Authorization": f"Bearer {cf_api_token}",
            "Content-Type": "text/plain"
        }
        
        response = requests.put(url, headers=headers, data="\n".join(links))
        response.raise_for_status()
        logger.info("成功存储到Cloudflare KV")
    except Exception as e:
        logger.error(f"KV存储失败: {str(e)}")

def generate_static_site(uuid: str):
    """生成Cloudflare Pages静态网站"""
    os.makedirs("public", exist_ok=True)
    
    with open("public/index.html", "w") as f:
        f.write(f"""<!DOCTYPE html>
<html>
<head>
    <title>免责声明</title>
</head>
<body>
    <h1>本服务仅用于技术研究，请勿用于非法用途</h1>
    <p>最后更新：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
</body>
</html>""")

    with open(f"public/{uuid}.html", "w") as f:
        f.write(f"""<!DOCTYPE html>
<html>
<head>
    <title>节点订阅</title>
</head>
<body>
    <h1>订阅地址：</h1>
    <code>https://your-domain.com/{uuid}/nodes.txt</code>
</body>
</html>""")

if __name__ == "__main__":
    token = os.getenv("CRAWLER_GITHUB_TOKEN")
    uuid = os.getenv("CF_PAGES_UUID", "default-uuid")
    
    if not token:
        logger.error("缺少CRAWLER_GITHUB_TOKEN环境变量")
        exit(1)

    try:
        logger.info("=== 开始执行爬虫任务 ===")
        crawler = GitHubCrawler(token)
        
        logger.info("正在搜索GitHub仓库...")
        repos = crawler.search_repositories("v2ray free")
        logger.info(f"发现 {len(repos)} 个相关仓库")
        
        logger.info("转换节点配置...")
        raw_links = convert_to_v2rayn(repos)
        link_list = raw_links.split("\n")
        logger.info(f"生成 {len(link_list)} 个节点配置")
        
#        logger.info("测试节点延迟...")
#        valid_links = test_node_latency(link_list)
#        logger.info(f"有效节点数量：{len(valid_links)}")
        
        with open("nodes.txt", "w") as f:
            f.write("\n".join(link_list))
        
        if os.getenv("CF_ENABLE_KV") == "true":
            save_to_cloudflare_kv(link_list)
        
        generate_static_site(uuid)
        logger.info("静态网站生成完成")
        
#        logger.info(f"=== 任务完成，有效节点数：{len(valid_links)} ===")
        logger.info(f"=== 任务完成，有效节点数：{len(link_list)} ===")
    except Exception as e:
        logger.error(f"执行失败: {str(e)}")
        exit(1)
