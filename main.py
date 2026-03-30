import asyncio
import logging
import os
from src import GitHubCrawler
from src.logger import setup_logger

logger = setup_logger(
    log_level=logging.INFO,
    log_file="output/logs/getnode.log"
)

async def main():
    try:
        logger.info("=== 开始执行爬虫任务（全量模式 + 内容验证）===")

        crawler = GitHubCrawler()
        repos = crawler.search_repos()
        logger.info(f"发现 {len(repos)} 个相关仓库")

        all_links = set()
        for repo in repos:
            links = crawler.find_node_files(repo['html_url'])
            for link in links:
                all_links.add(link['download_url'])

        logger.info(f"共收集到 {len(all_links)} 个有效节点文件链接")

        output_file = "output/urls.txt"
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(sorted(all_links)))
        logger.info(f"链接已保存至 {output_file}")

    except Exception as e:
        logger.error(f"执行失败: {str(e)}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(main())