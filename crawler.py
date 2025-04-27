import requests
import json

def fetch_nodes():
    # 示例：抓取GitHub上的公开节点仓库（替换为实际URL）
    url = "https://raw.githubusercontent.com/limitless-d/getnode/main/nodes.json"
    response = requests.get(url)
    return response.json()

def save_nodes(nodes):
    with open('docs/nodes.json', 'w') as f:
        json.dump(nodes, f, indent=2)

if __name__ == "__main__":
    nodes = fetch_nodes()
    save_nodes(nodes)
    print("节点已保存到 docs/nodes.json！")
