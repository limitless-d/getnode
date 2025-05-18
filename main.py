
import asyncio
from src import (
    GitHubCrawler,
    NodeProcessor,
    FileGenerator,
    RepoManager,
    HistoryManager,
    NodeTester,
    FileCounter,
    NodeCounter
)

import logging
from src.logger import setup_logger

# 在程序最开始初始化日志
logger = setup_logger(
    log_level=logging.INFO,  # 开发时用DEBUG，生产环境改为INFO
    log_file="logs/getnode.log"
)

async def main():
    try:
        logger.info("=== 开始执行爬虫任务 ===")
        
        # 搜索GitHub仓库
        crawler = GitHubCrawler()
        repos = crawler.search_repos()
        logger.info(f"发现 {len(repos)} 个相关仓库")

        # 收集节点文件
        node_links = []
        logger.info("开始收集节点文件...")
        for repo in repos:
            links = crawler.find_node_files(repo['html_url'])
            node_links.extend(links)
        logger.info(f"总共发现 {len(node_links)} 个节点文件")

        # 处理节点链接
        new_nodes = NodeProcessor.parse_node_links([link['download_url'] for link in node_links])

        # 合并历史节点
        history_nodes = HistoryManager.load_history_nodes()
        # new_nodes = [n['data'] for n in parsed['nodes']]
        merged_nodes = HistoryManager.merge_nodes(new_nodes, history_nodes)
        
        # 保存去重后的节点结果
        save_result = FileGenerator.save_results(merged_nodes)
        if not save_result['success']:
            raise RuntimeError("文件保存失败")

        # 节点测试
        tester = NodeTester()
        results = await tester.batch_test(merged_nodes)
        
        # 保存最终结果
        save_result = FileGenerator.save_results(results, output_dir='speedtest')
        if not save_result['success']:
            raise RuntimeError("文件保存失败")
        
        # 更新仓库状态
        repo_manager = RepoManager()
        for repo in repos:
            repo_manager.update_status(repo['html_url'], {
                'timestamp': repo['pushed_at'],
                'hash': repo['node_id']
            })

    except Exception as e:
        logger.error(f"执行失败: {str(e)}", exc_info=True)
        # 新增文件系统错误检查
        if isinstance(e, (PermissionError, FileNotFoundError)):
            logger.error("文件系统权限或路径错误")
            
    finally:
        # 添加统计输出
        if FileCounter.total > 0:
            logger.info(
                f"\n=== 文件处理统计 ==="
                f"\n• 扫描文件总数: {FileCounter.total}"
                f"\n• 因大小跳过:   {FileCounter.skipped} ({(FileCounter.skipped/FileCounter.total)*100:.1f}%)"
                f"\n• 有效处理文件: {FileCounter.total - FileCounter.skipped}"
                f"\n=== 节点处理统计 ==="
                f"\n• 扫描节点总数: {NodeCounter.total_nodes}"
                f"\n• 节点去重数:   {NodeCounter.dup_nodes}"
                f"\n• 真实节点数:   {NodeCounter.total_nodes - NodeCounter.dup_nodes}"
                f"\n"
            )
        else:
            logger.warning("未扫描到任何文件")

# if __name__ == "__main__":
#     main()
if __name__ == "__main__":
    asyncio.run(main())  # 使用 asyncio 运行异步主函数
