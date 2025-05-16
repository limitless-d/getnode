
# 显式导入所有子模块
from . import (
    crawler,
    nodesjob,
    repo_manager,
    history_manager,
    tester,
    counters
)


# 暴露主要类和方法
__all__ = [
    'GitHubCrawler', 
    'NodeProcessor',
    'FileGenerator',
    'RepoManager',
    'HistoryManager',
    'NodeTester',
    'FileCounter',
    'NodeCounter'
]


def __getattr__(name):
    if name == "NodeTester":
        from .tester import NodeTester
        return NodeTester
    if name == "GitHubCrawler":
        from .crawler import GitHubCrawler
        return GitHubCrawler
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

# 从子模块导入关键类
from .crawler import GitHubCrawler, FileCounter
from .nodesjob import NodeProcessor, FileGenerator, NodeCounter
from .repo_manager import RepoManager
from .history_manager import HistoryManager
from .tester import NodeTester
from .counters import FileCounter, NodeCounter
