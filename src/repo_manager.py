import json
import os
from datetime import datetime
from urllib.parse import urlparse
import dateutil.parser
import logging

logger = logging.getLogger("getnode")

class RepoManager:
    def __init__(self, file_path='output/repo_status.json'):
        self.file_path = file_path
        os.makedirs(os.path.dirname(file_path), exist_ok=True)  # 新增目录创建
        self.repo_status = self._load_status()
    
    def _load_status(self):
        """加载仓库状态文件，自动处理空文件或格式错误"""
        if not os.path.exists(self.file_path):
            return {}

        try:
            with open(self.file_path, 'r') as f:
                content = f.read().strip()
                
                # 处理空文件
                if not content:
                    logger.warning(f"状态文件为空: {self.file_path}")
                    return {}
                    
                # 解析JSON内容
                return json.loads(content)
                
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败！文件内容无效: {self.file_path}\n错误详情: {str(e)}")
            return {}
        except Exception as e:
            logger.error(f"加载状态文件异常: {type(e).__name__} - {str(e)}")
            return {}
    
    def should_process(self, repo_url, latest_commit):
        """检查仓库是否需要处理"""

        parsed = urlparse(repo_url)
        repo_key = parsed.path.strip('/')
        
        if repo_key in self.repo_status:
            try:
                # 解析时间（兼容带 Z 的格式）
                latest_date = dateutil.parser.isoparse(latest_commit)
                stored_date_str = self.repo_status[repo_key]['last_commit']
                stored_date = dateutil.parser.isoparse(stored_date_str)
                return latest_date > stored_date
            except Exception as e:
                logger.error(f"时间解析失败: {str(e)}", exc_info=True)
                return True  # 默认处理该仓库
        return True

    def update_status(self, repo_url, commit_info):
        """更新仓库状态"""

        parsed = urlparse(repo_url)
        repo_key = parsed.path.strip('/')  # 或改用 commit_info['hash'] 作为键
        
        self.repo_status[repo_key] = {
            'last_commit': commit_info['timestamp'],  # 直接使用原始时间字符串
            'commit_hash': commit_info['hash']
        }
        self._save()
    
    def _save(self):
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)  # 确保目录存在
        with open(self.file_path, 'w') as f:
            json.dump(self.repo_status, f, indent=2, default=str)
            