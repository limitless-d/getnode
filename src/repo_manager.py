import json
import os
from datetime import datetime
from urllib.parse import urlparse

class RepoManager:
    def __init__(self, file_path='output/repo_status.json'):
        self.file_path = file_path
        self.repo_status = self._load_status()
    
    def _load_status(self):
        if os.path.exists(self.file_path):
            with open(self.file_path, 'r') as f:
                return json.load(f)
        return {}
    
    def should_process(self, repo_url, latest_commit):
        """检查仓库是否需要处理"""
        parsed = urlparse(repo_url)
        repo_key = f"{parsed.path.strip('/')}"
        
        if repo_key in self.repo_status:
            stored_date = datetime.fromisoformat(self.repo_status[repo_key]['last_commit'])
            return datetime.fromisoformat(latest_commit) > stored_date
        return True
    
    def update_status(self, repo_url, commit_info):
        """更新仓库状态"""
        parsed = urlparse(repo_url)
        repo_key = f"{parsed.path.strip('/')}"
        
        self.repo_status[repo_key] = {
            'last_commit': commit_info['timestamp'],
            'commit_hash': commit_info['hash']
        }
        self._save()
    
    def _save(self):
        with open(self.file_path, 'w') as f:
            json.dump(self.repo_status, f, indent=2, default=str)
            