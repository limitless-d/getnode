import asyncio
import aiohttp
import logging
from tenacity import retry, stop_after_attempt, wait_random

TEST_TIMEOUT = 15    # 单次测试超时
MAX_CONCURRENT = 50  # 最大并发数 
RETRY_COUNT = 2      # 重试次数

logger = logging.getLogger("getnode")

class NodeTester:
    def __init__(self):
        self.timeout = aiohttp.ClientTimeout(total=TEST_TIMEOUT)
        self.test_urls = [
            'http://www.gstatic.com/generate_204',  # 基础连通性测试
            'http://captive.apple.com/hotspot-detect.html'  # 备用测试
        ]
    
    async def _test_protocol(self, session, node):
        """协议专用测试逻辑"""
        logger.debug(f"协议测试启动 | 类型: {node.get('type', 'unknown')}, 地址: {node.get('server', '')}:{node.get('port', '')}") 
        try:
            if node['type'] == 'ss':
                # Shadowsocks测试
                proxy = f"socks5://{node['server']}:{node['port']}"
                async with session.get(self.test_urls[0], proxy=proxy) as resp:
                    success = resp.status == 204
                    # 新增日志：测试结果
                    if success:
                        logger.debug(f"Shadowsocks节点验证成功 | {node['server']}:{node['port']}")
                    else:
                        logger.debug(f"Shadowsocks节点异常 | 状态码: {resp.status}")
                    return success
            elif node['type'] in ['vmess', 'vless', 'trojan']:
                # 使用CONNECT方法测试
                async with session.head(self.test_urls[0], 
                                     proxy=f"http://{node['server']}:{node['port']}") as resp:
                    success = resp.status in [200, 204]
                    # 新增日志：测试结果
                    logger.debug(f"{node['type'].title()}节点测试 {'通过' if success else '失败'} | 状态码: {resp.status}")
                    return success
            else:
                # 通用HTTP测试
                async with session.get(self.test_urls[1]) as resp:
                    success = resp.status == 200
                    # 新增日志：测试结果
                    logger.debug(f"未知协议节点测试 | 状态码: {resp.status}")
                    return success
        except Exception as e:
            # 新增日志：异常捕获
            # logger.error(f"协议测试异常 | 错误: {str(e)}", exc_info=True)
            return False
    
    @retry(stop=stop_after_attempt(RETRY_COUNT), wait=wait_random(min=1, max=3))
    async def _test_node(self, node):
        """双重测试机制"""
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            try:
                # 统一基础测试
                async with session.get(self.test_urls[0]) as resp:
                    if resp.status != 204:
                        logger.debug(f"基础连通性测试失败 | 地址: {node.get('server')}")
                        return False
                
                # 协议专用测试
                return await self._test_protocol(session, node)
            except:
                return False
   
    async def batch_test(self, result):
        """批量测试节点（适配新result格式）"""
        nodes_to_test = [item['data'] for item in result['nodes']]  # 提取data字段中的节点
        logger.info(f"=== 批量测试开始 | 总节点数: {len(nodes_to_test)} ===")

        semaphore = asyncio.Semaphore(MAX_CONCURRENT)   # 控制并发数
        
        async def limited_test(node):
            async with semaphore:
                return await self._test_node(node)  # 直接测试node数据
        
        # 创建任务并运行
        tasks = [limited_test(node) for node in nodes_to_test]
        results = await asyncio.gather(*tasks)
        
        # 更新result统计信息
        result['total_nodes'] = len(nodes_to_test)
        
        
        # 直接过滤无效节点，仅保留成功的节点
        result['nodes'] = [
            {**item}  # 保留原始节点信息（source_type, url, data）
            for item, success in zip(result['nodes'], results)
            if success  # 仅在测试成功时保留
        ]
        # 记录失败详情
        result['failures'] = [
            {'source': item['url'], 'reason': '测试未通过'}
            for item, success in zip(result['nodes'], results)
            if not success
        ]
        
        logger.info(
            f"=== 批量测试完成 | 有效节点: {len(result['nodes'])} "
            f"(成功率: {len(result['nodes'])/result['total_nodes']*100:.1f}%) ==="
        )
    
        return result
    