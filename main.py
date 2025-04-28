from crawler import GitHubCrawler, NodeProcessor, FileGenerator
from cloudflare import CloudflareDeployer
import logging

logger = logging.getLogger(__name__)

def main():
    try:
        logger.info("=== 开始执行爬虫任务 ===")
        
        # 搜索GitHub仓库
        crawler = GitHubCrawler()
        repos = crawler.search_repos()
        logger.info(f"发现 {len(repos)} 个相关仓库")

        # 收集节点文件
        node_links = []
        for repo in repos:
            links = crawler.find_node_files(repo['html_url'])
            node_links.extend(links)
        logger.info(f"发现 {len(node_links)} 个节点文件")

        # 处理节点链接
        parsed = NodeProcessor.parse_node_links([link['download_url'] for link in node_links])

        # 保存结果
        save_result = FileGenerator.save_results(parsed)
        if not save_result['success']:
            raise RuntimeError("文件保存失败")

        # 部署到Cloudflare
        if CloudflareDeployer.deploy():
            logger.info("=== 部署成功 ===")
        else:
            logger.error("=== 部署失败 ===")

    except Exception as e:
        logger.error(f"执行失败: {str(e)}", exc_info=True)

if __name__ == "__main__":
    main()
