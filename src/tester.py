import asyncio
import aiohttp
from tenacity import retry, stop_after_attempt, wait_random

TEST_TIMEOUT = 15    # 单次测试超时
MAX_CONCURRENT = 50  # 最大并发数 
RETRY_COUNT = 2      # 重试次数

class NodeTester:
    def __init__(self):
        self.timeout = aiohttp.ClientTimeout(total=TEST_TIMEOUT)
        self.test_urls = [
            'http://www.gstatic.com/generate_204',  # 基础连通性测试
            'http://captive.apple.com/hotspot-detect.html'  # 备用测试
        ]
    
    async def _test_protocol(self, session, node):
        """协议专用测试逻辑"""
        try:
            if node['type'] == 'ss':
                # Shadowsocks测试
                proxy = f"socks5://{node['server']}:{node['port']}"
                async with session.get(self.test_urls[0], proxy=proxy) as resp:
                    return resp.status == 204
            elif node['type'] in ['vmess', 'vless', 'trojan']:
                # 使用CONNECT方法测试
                async with session.head(self.test_urls[0], 
                                     proxy=f"http://{node['server']}:{node['port']}") as resp:
                    return resp.status in [200, 204]
            else:
                # 通用HTTP测试
                async with session.get(self.test_urls[1]) as resp:
                    return resp.status == 200
        except:
            return False
    
    @retry(stop=stop_after_attempt(RETRY_COUNT), wait=wait_random(min=1, max=3))
    async def _test_node(self, node):
        """双重测试机制"""
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            try:
                # 统一基础测试
                async with session.get(self.test_urls[0]) as resp:
                    if resp.status != 204:
                        return False
                
                # 协议专用测试
                return await self._test_protocol(session, node)
            except:
                return False
    
    async def batch_test(self, nodes):
        """批量测试节点"""
        semaphore = asyncio.Semaphore(MAX_CONCURRENT)  # 控制并发数
        
        async def limited_test(node):
            async with semaphore:
                return await self._test_node(node)
        
        tasks = [limited_test(node) for node in nodes]
        results = await asyncio.gather(*tasks)
        return [node for node, success in zip(nodes, results) if success]
    