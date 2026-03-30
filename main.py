import asyncio
import logging
from src import (
    GitHubCrawler,
    FileGenerator,   # 仅用于保存文件，保留但不解析节点
    RepoManager,
    FileCounter,
    NodeCounter
)
from src.logger import setup_logger

logger = setup_logger(
    log_level=logging.INFO,
    log_file="output/logs/getnode.log"
)

async def main():
    try:
        logger.info("=== 开始执行爬虫任务 ===")
        
        # 搜索GitHub仓库
        crawler = GitHubCrawler()
        repos = crawler.search_repos()
        logger.info(f"发现 {len(repos)} 个相关仓库")

        # 收集节点文件
        node_links = []  # 存储每个文件的raw链接
        logger.info("开始收集节点文件...")
        for repo in repos:
            links = crawler.find_node_files(repo['html_url'])
            for link in links:
                node_links.append(link['download_url'])
        logger.info(f"总共发现 {len(node_links)} 个节点文件")

        # 去重（可选，但保留以防重复链接）
        unique_links = list(set(node_links))
        logger.info(f"去重后剩余 {len(unique_links)} 个唯一链接")

        # 保存链接到txt文件
        output_file = "output/urls.txt"
        import os
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(unique_links))
        logger.info(f"链接已保存至 {output_file}")

        # 更新仓库状态（可选）
        # repo_manager = RepoManager()
        # for repo in repos:
        #     repo_manager.update_status(repo['html_url'], {
        #         'timestamp': repo['pushed_at'],
        #         'hash': repo['node_id']
        #     })

    except Exception as e:
        logger.error(f"执行失败: {str(e)}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(main())