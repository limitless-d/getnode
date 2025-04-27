import requests
import json
import time
from dotenv import load_dotenv
import os

load_dotenv()  # 加载.env文件

# ↓↓↓ 替换成你的令牌 ↓↓↓
GITHUB_TOKEN = os.getenv("CRAWLER_GITHUB_TOKEN")  # 从环境变量获取

# SEARCH_KEYWORDS = ["v2ray free", "vmess nodes", "ssr订阅", "free proxies"]
SEARCH_KEYWORDS = ["v2ray free"]

def search_github():
    """自动搜索含节点的仓库"""
    print("🚀 正在搜索GitHub仓库...")
    all_repos = []
    
    for keyword in SEARCH_KEYWORDS:
        page = 1
        while True:
            # 构造搜索URL
            url = f"https://api.github.com/search/repositories?q={keyword}&sort=updated&page={page}"
            headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}
            
            # 发送请求
            response = requests.get(url, headers=headers)
            if response.status_code != 200:
                print(f"⚠ 错误：{response.status_code}，可能达到API限制")
                break
                
            data = response.json()
            if not data["items"]:
                break  # 没有更多结果
                
            # 收集仓库信息
            for repo in data["items"]:
                all_repos.append({
                    "name": repo["full_name"],
                    "url": repo["html_url"],
                    "description": repo["description"]
                })
            
            print(f"📦 已找到 {len(all_repos)} 个仓库")
            page += 1
            time.sleep(1)  # 防止请求过快
            
    return all_repos

def find_nodes_in_repo(repo_url):
    """在仓库中查找节点文件"""
    print(f"\n🔍 正在扫描仓库：{repo_url}")
    api_url = repo_url.replace("https://github.com/", "https://api.github.com/repos/") + "/contents/"
    
    try:
        response = requests.get(api_url, headers={"Authorization": f"Bearer {GITHUB_TOKEN}"})
        files = response.json()
        
        # 识别可能的节点文件
        node_files = []
        for file in files:
            name = file["name"].lower()
            if name.endswith((".json", ".txt")) or "node" in name or "subscribe" in name:
                node_files.append(file["download_url"])
        
        return node_files
    except Exception as e:
        print(f"❌ 扫描失败：{str(e)}")
        return []

def parse_node_file(file_url):
    """解析节点文件"""
    try:
        response = requests.get(file_url)
        content = response.text
        
        # 尝试解析JSON格式
        if file_url.endswith(".json"):
            return json.loads(content)
            
        # 处理vmess://等协议
        nodes = []
        for line in content.splitlines():
            line = line.strip()
            if line.startswith(("vmess://", "ss://", "trojan://")):
                nodes.append(line)
                
        return nodes
    except:
        return []

# 主程序
if __name__ == "__main__":
    # 步骤1：搜索仓库
    repositories = search_github()
    
    # 步骤2：遍历仓库收集节点
    all_nodes = []
    for repo in repositories[:3]:  # 先测试前3个仓库
        files = find_nodes_in_repo(repo["url"])
        
        for file_url in files:
            nodes = parse_node_file(file_url)
            if nodes:
                print(f"✅ 从 {file_url.split('/')[-1]} 找到 {len(nodes)} 个节点")
                all_nodes.extend(nodes)
    
    # 保存结果
    with open("nodes.json", "w") as f:
        json.dump(all_nodes, f, indent=2)
    print(f"\n🎉 完成！共收集到 {len(all_nodes)} 个节点，已保存到 nodes.json")
