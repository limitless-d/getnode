import os
import time
import requests
import json
import base64
import yaml
import logging
from datetime import datetime
from tenacity import retry, wait_exponential, stop_after_attempt
from typing import List, Dict
from collections import OrderedDict
from urllib.parse import urlparse, unquote

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
MAX_RETRIES = 3
NODE_KEYWORDS = [ 'v2ray free', 'subscribe', 'clash']


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
    def __init__(self):
        self.token = os.getenv("CRAWLER_GITHUB_TOKEN")
        self.headers = {
            "Authorization": f"Bearer {self.token}",
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

    def search_repos(self) -> list:
        repos = []
        params = {
            "q": "v2ray free OR clash OR subscribe",
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
            logger.error(f"仓库搜索失败: {str(e)}")

        return repos[:MAX_RETRIES]

    def find_node_files(self, repo_url: str) -> list:
        """递归查找仓库中的节点文件"""
        repo_api_url = repo_url.replace("https://github.com/", "https://api.github.com/repos/")
        return self._search_contents(repo_api_url + "/contents/")

    def _search_contents(self, path: str) -> list:
        """递归搜索目录内容"""
        try:
            contents = self.safe_request(path)
            node_files = []

            for item in contents:
                if item["type"] == "dir":
                    node_files.extend(self._search_contents(item["url"]))
                else:
                    name = item["name"].lower()
                    if any(kw in name for kw in NODE_KEYWORDS) and \
                       (name.endswith((".yaml", ".yml", ".txt", ".json"))):
                        node_files.append({
                            "name": item["name"],
                            "url": item["html_url"],
                            "download_url": item.get("download_url", "")
                        })

            return node_files
        except Exception as e:
            logger.error(f"搜索目录失败 {path}: {str(e)}")
            return []

""" 链接处理相关函数 """
def parse_clash_meta_config_from_url(url):
    """
    从URL解析Clash-Meta配置文件并提取节点信息
    
    参数:
        url (str): Clash-Meta配置文件的URL地址
        
    返回:
        dict: {
            'success': bool,  # 是否成功
            'data': list,     # 节点信息列表
            'message': str    # 错误信息(如果有)
        }
    """
    result = {
        'success': False,
        'data': [],
        'message': ''
    }
    
    try:
        # 验证URL格式
        parsed_url = urlparse(url)
        if not all([parsed_url.scheme, parsed_url.netloc]):
            raise ValueError("提供的URL格式不正确")
        
        # 获取YAML文件内容
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        # 解析YAML内容
        config = yaml.safe_load(response.text)
        
        # 提取节点信息
        proxies = config.get('proxies', [])
        
        # 处理节点信息
        nodes = []
        for proxy in proxies:
            node_info = {
                'name': proxy.get('name', ''),
                'type': proxy.get('type', ''),
                'server': proxy.get('server', ''),
                'port': proxy.get('port', ''),
                'raw': proxy  # 保留原始数据
            }
            
            # 根据不同类型添加特定信息
            if proxy.get('type') == 'ss':
                node_info.update({
                    'password': proxy.get('password', ''),
                    'cipher': proxy.get('cipher', '')
                })
            elif proxy.get('type') == 'vmess':
                node_info.update({
                    'uuid': proxy.get('uuid', ''),
                    'alterId': proxy.get('alterId', ''),
                    'network': proxy.get('network', 'tcp')
                })
            elif proxy.get('type') == 'trojan':
                node_info.update({
                    'password': proxy.get('password', ''),
                    'sni': proxy.get('sni', '')
                })
            
            nodes.append(node_info)
        
        result['success'] = True
        result['data'] = nodes
        
    except requests.RequestException as e:
        result['message'] = f"网络请求失败: {str(e)}"
    except yaml.YAMLError as e:
        result['message'] = f"YAML解析失败: {str(e)}"
    except Exception as e:
        result['message'] = f"处理配置时出错: {str(e)}"
    
    return result

def parse_txt_from_url(file_url):
    """
    解析文本格式的节点文件
    
    参数:
        file_url (str): 节点文件的URL地址
        
    返回:
        dict: {
            'success': bool,  # 是否成功
            'data': list,     # 节点信息列表
            'message': str    # 错误信息(如果有)
        }
    """
    result = {
        'success': False,
        'data': [],
        'message': ''
    }
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(file_url, headers=headers, timeout=15)
        response.raise_for_status()
        
        content = response.text
        nodes = []
        
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
                
            node_info = {'raw': line}
            
            if line.startswith("vmess://"):
                try:
                    # 解码base64
                    encoded = line[8:]
                    decoded = base64.b64decode(unquote(encoded)).decode('utf-8')
                    vmess_config = json.loads(decoded)
                    
                    node_info.update({
                        'type': 'vmess',
                        'name': vmess_config.get('ps', ''),
                        'server': vmess_config.get('add', ''),
                        'port': vmess_config.get('port', ''),
                        'uuid': vmess_config.get('id', ''),
                        'alterId': vmess_config.get('aid', ''),
                        'network': vmess_config.get('net', 'tcp')
                    })
                except:
                    continue
                    
            elif line.startswith("ss://"):
                try:
                    # 处理SS链接
                    encoded = line[5:]
                    if '#' in encoded:
                        encoded, name = encoded.split('#', 1)
                        name = unquote(name)
                    else:
                        name = ''
                    
                    decoded = base64.b64decode(unquote(encoded)).decode('utf-8')
                    if '@' in decoded:
                        method_password, server_port = decoded.split('@', 1)
                        method, password = method_password.split(':', 1)
                        server, port = server_port.split(':', 1)
                    else:
                        continue
                    
                    node_info.update({
                        'type': 'ss',
                        'name': name,
                        'server': server,
                        'port': port,
                        'password': password,
                        'cipher': method
                    })
                except:
                    continue
                    
            elif line.startswith("trojan://"):
                try:
                    # 处理Trojan链接
                    parts = line[9:].split('@', 1)
                    if len(parts) != 2:
                        continue
                    
                    password = parts[0]
                    rest = parts[1]
                    
                    if '#' in rest:
                        server_port, name = rest.split('#', 1)
                        name = unquote(name)
                    else:
                        server_port = rest
                        name = ''
                    
                    server, port = server_port.split(':', 1)
                    
                    node_info.update({
                        'type': 'trojan',
                        'name': name,
                        'server': server,
                        'port': port,
                        'password': password
                    })
                except:
                    continue
                    
            if node_info.get('type'):
                nodes.append(node_info)
        
        result['success'] = True
        result['data'] = nodes
        
    except requests.RequestException as e:
        result['message'] = f"网络请求失败: {str(e)}"
    except Exception as e:
        result['message'] = f"处理节点时出错: {str(e)}"
    
    return result

def process_node_links(links):
    """
    处理包含节点信息的链接集合
    
    参数:
        links (list): 包含多个URL的列表
        
    返回:
        dict: {
            'total_links': int,      # 总处理链接数
            'success_count': int,    # 成功解析的链接数
            'failure_count': int,    # 解析失败的链接数
            'total_nodes': int,      # 合并后的节点总数
            'nodes': list,           # 合并后的节点列表
            'failures': list         # 失败详情[{'url':..., 'error':...}]
        }
    """
    logger.info(f"开始处理链接集合，共 {len(links)} 个链接")
    result = {
        'total_links': len(links),
        'success_count': 0,
        'failure_count': 0,
        'total_nodes': 0,
        'nodes': [],
        'failures': []
    }
    
    seen = set()  # 用于去重
    
    for index, url in enumerate(links, 1):
        try:
            logger.info(f"正在处理链接 ({index}/{len(links)}): {url}")
            
            # 先尝试解析为Clash-Meta配置
            clash_result = parse_clash_meta_config_from_url(url)
            if clash_result['success'] and clash_result['data']:
                node_count = len(clash_result['data'])
                logger.info(f"成功解析为Clash配置，发现 {node_count} 个节点")
                
                for node in clash_result['data']:
                    unique_id = f"{node['server']}:{node['port']}-{node['type']}-{node['name']}"
                    if unique_id not in seen:
                        seen.add(unique_id)
                        result['nodes'].append({
                            'source_type': 'clash-meta',
                            'url': url,
                            'data': node
                        })
                result['success_count'] += 1
                continue
                
            # 如果Clash解析失败，尝试解析为文本节点
            logger.debug("Clash解析无结果，尝试解析为文本节点")
            txt_result = parse_txt_from_url(url)
            if txt_result['success'] and txt_result['data']:
                node_count = len(txt_result['data'])
                logger.info(f"成功解析为文本节点，发现 {node_count} 个节点")
                
                for node in txt_result['data']:
                    unique_id = node['raw']
                    if unique_id not in seen:
                        seen.add(unique_id)
                        result['nodes'].append({
                            'source_type': 'text',
                            'url': url,
                            'data': node
                        })
                result['success_count'] += 1
                continue
                
            # 两种解析方式都失败
            error_msg = '无法识别为有效的节点配置'
            logger.warning(f"解析失败: {error_msg}")
            result['failure_count'] += 1
            result['failures'].append({
                'url': url,
                'error': error_msg
            })
            
        except Exception as e:
            error_msg = f'处理异常: {str(e)}'
            logger.error(f"处理链接时发生异常: {error_msg}", exc_info=True)
            result['failure_count'] += 1
            result['failures'].append({
                'url': url,
                'error': error_msg
            })
    
    result['total_nodes'] = len(result['nodes'])
    logger.info(
        f"处理完成。成功: {result['success_count']}, 失败: {result['failure_count']}, "
        f"去重后总节点数: {result['total_nodes']}"
    )
    return result

"""保存节点信息相关函数"""
def save_node_results(node_results):
    """
    保存节点信息到文件（适配GitHub环境）
    
    参数:
        node_results (dict): process_node_links函数的返回结果
        
    返回:
        dict: {
            'success': bool,
            'files': list,       # 生成的文件路径
            'node_counts': dict,  # 各类型节点统计
            'message': str
        }
    """
    result = {
        'success': False,
        'files': [],
        'node_counts': {},
        'message': ''
    }
    
    try:
        # 创建输出目录（适配GitHub Actions工作目录）
        output_dir = os.path.join(os.getcwd(), 'output')
        os.makedirs(output_dir, exist_ok=True)
        logger.info(f"输出目录已创建：{output_dir}")

        # 准备数据结构
        clash_config = {'proxies': []}
        v2rayn_lines = []
        node_counter = {}

        for node in node_results['nodes']:
            try:
                node_type = node['data'].get('type', 'unknown')
                raw_data = node['data']
                
                # 统计节点类型
                node_counter[node_type] = node_counter.get(node_type, 0) + 1

                # 生成v2rayN格式（标准订阅格式）
                if node['source_type'] == 'text' and 'raw' in raw_data:
                    # 直接使用原始链接
                    v2rayn_lines.append(raw_data['raw'])
                else:
                    # 从Clash配置转换生成标准URI
                    uri = _convert_to_uri(raw_data)
                    if uri:
                        v2rayn_lines.append(uri)

                # 生成Clash配置
                clash_proxy = _convert_to_clash(raw_data)
                if clash_proxy:
                    clash_config['proxies'].append(clash_proxy)

            except Exception as e:
                logger.warning(f"处理节点时出错：{str(e)}", exc_info=True)

        # 保存v2rayN订阅文件
        txt_path = os.path.join(output_dir, 'subscription.txt')
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(v2rayn_lines))
        result['files'].append(txt_path)
        logger.info(f"已生成v2rayN订阅文件：{txt_path} ({len(v2rayn_lines)}节点)")

        # 保存Clash配置
        yaml_path = os.path.join(output_dir, 'clash_config.yaml')
        with open(yaml_path, 'w', encoding='utf-8') as f:
            yaml.safe_dump(clash_config, f, 
                          allow_unicode=True, 
                          sort_keys=False,
                          default_flow_style=False)
        result['files'].append(yaml_path)
        logger.info(f"已生成Clash配置文件：{yaml_path} ({len(clash_config['proxies'])}节点)")

        result['success'] = True
        result['node_counts'] = node_counter
        
    except Exception as e:
        result['message'] = f"保存失败: {str(e)}"
        logger.error(f"保存文件时发生错误：{str(e)}", exc_info=True)
    
    return result

def _convert_to_uri(node_data):
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

"""推送cloudflare pages页面相关函数"""
def prepare_for_cloudflare(output_dir):
    """
    准备Cloudflare Pages发布需要的文件结构
    """
    try:
        # 创建Cloudflare要求的部署目录
        cf_dir = os.path.join(output_dir, 'cloudflare')
        os.makedirs(cf_dir, exist_ok=True)
        
        # 生成索引页面
        index_content = """<!DOCTYPE html>
<html>
<head>
    <title>Subscription Files</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 2rem; }
        .file-list { list-style: none; padding: 0; }
        .file-item { margin: 1rem 0; }
        .timestamp { color: #666; font-size: 0.9rem; }
    </style>
</head>
<body>
    <h1>Available Files</h1>
    <ul class="file-list" id="fileList"></ul>
    <div class="timestamp">Last updated: <span id="timestamp"></span></div>

    <script>
        fetch('/file-list.json')
            .then(response => response.json())
            .then(data => {
                const list = document.getElementById('fileList');
                const timestamp = document.getElementById('timestamp');
                
                timestamp.textContent = new Date(data.timestamp).toLocaleString();
                
                data.files.forEach(file => {
                    const li = document.createElement('li');
                    li.className = 'file-item';
                    li.innerHTML = `<a href="${file.path}">${file.name}</a> (${file.size} KB)`;
                    list.appendChild(li);
                });
            });
    </script>
</body>
</html>"""
        
        with open(os.path.join(cf_dir, 'index.html'), 'w') as f:
            f.write(index_content)
        
        return cf_dir
        
    except Exception as e:
        logger.error(f"准备Cloudflare目录失败: {str(e)}")
        raise

def generate_metadata(output_dir, cf_dir):
    """
    生成部署元数据文件
    """
    try:
        # 生成文件清单
        file_list = []
        total_size = 0
        
        for root, dirs, files in os.walk(output_dir):
            for file in files:
                if 'cloudflare' in root:
                    continue
                
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, output_dir)
                size_kb = os.path.getsize(file_path) / 1024
                
                file_list.append({
                    'name': file,
                    'path': f'/{rel_path}',
                    'size': round(size_kb, 2)
                })
                total_size += size_kb
        
        metadata = {
            'timestamp': datetime.utcnow().isoformat() + "Z",
            'total_files': len(file_list),
            'total_size_kb': round(total_size, 2),
            'files': file_list      
        }
        
        # 保存元数据文件
        meta_path = os.path.join(cf_dir, 'file-list.json')
        with open(meta_path, 'w') as f:
            json.dump(metadata, f, indent=2)
            
        return metadata
        
    except Exception as e:
        logger.error(f"生成元数据失败: {str(e)}")
        raise

def deploy_to_cloudflare(cf_dir):
    """
    使用Wrangler部署到Cloudflare Pages（带版本控制）
    """
    try:
        account_id = os.getenv('CF_ACCOUNT_ID')
        api_token = os.getenv('CF_API_TOKEN')
        project_name = os.getenv('CF_PROJECT_NAME') or 'subscription-center'
        
        if not account_id or not api_token:
            raise ValueError("缺少Cloudflare认证信息")
        
        # 生成唯一版本号
        version = datetime.now().strftime("%Y%m%d%H%M")
        wrangler_config = {
            "name": project_name,
            "compatibility_date": "2023-08-01",
            "pages_build_output_dir": "cloudflare",
            "env": {  # 添加环境配置
                version: {
                    "vars": {
                        "DEPLOY_VERSION": version
                    }
                }
            }
        }
        
        config_path = os.path.join(os.getcwd(), 'wrangler.toml')
        with open(config_path, 'w') as f:
            f.write(f"""name = "{wrangler_config['name']}"
compatibility_date = "{wrangler_config['compatibility_date']}"
pages_build_output_dir = "{wrangler_config['pages_build_output_dir']}"
[vars]
DEPLOY_VERSION = "{version}"\n""")
        
        deploy_cmd = (
            f"npx wrangler pages deploy {cf_dir} "
            f"--project-name {project_name} "
            f"--branch main "
            f"--env {version}"  # 使用版本号作为环境标识
        )
        exit_code = os.system(deploy_cmd)
        
        if exit_code != 0:
            raise RuntimeError(f"部署失败，退出码：{exit_code}")
        
        logger.info(f"已部署版本 {version}")
        return True
        
    except Exception as e:
        logger.error(f"Cloudflare部署失败: {str(e)}")
        return False

"""******** 主函数 ********"""    
if __name__ == "__main__":
    try:
        logger.info("=== 开始执行爬虫任务 ===")
        crawler = GitHubCrawler()
        
        logger.info("正在搜索GitHub仓库...")
        repos = crawler.search_repos()
        logger.info(f"发现 {len(repos)} 个相关仓库")
        
        logger.info("正在查找节点文件...")
        for repo in repos:
            repo_url = repo["html_url"]
            node_links = crawler.find_node_files(repo_url)
        logger.info(f"发现 {len(node_links)} 个相关节点文件")

        logger.info("正在处理节点文件...")
        parsed = process_node_links(node_links)
    
        # 保存原始文件
        save_result = save_node_results(parsed)
        
        if save_result['success']:
            # 准备Cloudflare部署
            cf_dir = prepare_for_cloudflare('output')
            metadata = generate_metadata('output', cf_dir)
            
            # 部署到Cloudflare
            deploy_result = deploy_to_cloudflare(cf_dir)
            
            if deploy_result:
                logger.info("部署到Cloudflare Pages成功！")
            else:
                logger.error("部署到Cloudflare Pages失败")
        else:
            logger.error("文件保存失败，跳过部署")
        
        logger.info(f"=== 任务完成，有效节点数：{len(parsed)} ===")
    except Exception as e:
        logger.error(f"执行失败: {str(e)}")
        exit(1)
