import os
import json
import logging
import subprocess  # 更安全的命令执行方式
from datetime import datetime
from typing import Dict, List
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

class CloudflareDeployer:
    @staticmethod
    def deploy(output_dir='output') -> bool:
        """
        部署到Cloudflare Pages
        返回: bool - 是否部署成功
        """
        try:
            # 验证环境变量
            required_envs = {
                "CLOUDFLARE_ACCOUNT_ID": os.getenv("CLOUDFLARE_ACCOUNT_ID"),
                "CLOUDFLARE_API_TOKEN": os.getenv("CLOUDFLARE_API_TOKEN")
            }
            missing = [k for k, v in required_envs.items() if not v]
            if missing:
                raise ValueError(f"缺少必要环境变量: {', '.join(missing)}")

            # 准备目录结构
            cf_dir = CloudflareDeployer.prepare_structure(output_dir)
            CloudflareDeployer.generate_metadata(output_dir, cf_dir)

            # 构造部署命令
            project_name = os.getenv("CF_PROJECT_NAME", "node-subscription")
            deploy_cmd = [
                "npx", "wrangler", "pages", "deploy", cf_dir,
                "--project-name", project_name,
                "--branch", "main",
                "--commit-dirty=true"  # 允许未提交的更改
            ]

            # 执行部署命令
            logger.info(f"执行部署命令: {' '.join(deploy_cmd)}")
            result = subprocess.run(
                deploy_cmd,
                capture_output=True,
                text=True,
                env=os.environ.copy()  # 传递所有环境变量
            )

            # 处理结果
            if result.returncode == 0:
                logger.info("成功部署到Cloudflare Pages")
                logger.debug(f"部署输出:\n{result.stdout}")
                return True
            else:
                logger.error(f"部署失败，退出码: {result.returncode}")
                logger.error(f"错误输出:\n{result.stderr}")
                return False

        except Exception as e:
            logger.error(f"部署过程异常: {str(e)}", exc_info=True)
            return False

    @staticmethod
    def prepare_structure(output_dir: str) -> str:
        """准备部署目录结构"""
        cf_dir = os.path.join(output_dir, 'cloudflare')
        os.makedirs(cf_dir, exist_ok=True)

        # 生成基础索引页面
        index_content = """<!DOCTYPE html>
<html>
<head>
    <title>节点订阅中心</title>
    <meta charset="utf-8">
</head>
<body>
    <h1>订阅文件列表</h1>
    <div id="file-list"></div>
    <script src="/file-list.json"></script>
</body>
</html>"""
        
        index_path = os.path.join(cf_dir, 'index.html')
        if not os.path.exists(index_path):
            with open(index_path, 'w') as f:
                f.write(index_content)
        
        return cf_dir

    @staticmethod
    def generate_metadata(output_dir: str, cf_dir: str) -> Dict:
        """生成文件元数据"""
        file_list = []
        total_size = 0.0

        for root, _, files in os.walk(output_dir):
            # 跳过cloudflare目录自身
            if os.path.abspath(root) == os.path.abspath(cf_dir):
                continue

            for file in files:
                file_path = os.path.join(root, file)
                
                # 验证文件有效性
                if not os.path.isfile(file_path):
                    continue

                # 计算相对路径
                rel_path = os.path.relpath(file_path, output_dir)
                
                # 获取文件信息
                size_kb = os.path.getsize(file_path) / 1024
                file_stat = {
                    'name': file,
                    'path': f'/{rel_path}',
                    'size': round(size_kb, 2),
                    'last_modified': datetime.fromtimestamp(
                        os.path.getmtime(file_path)
                    ).isoformat()
                }
                
                file_list.append(file_stat)
                total_size += size_kb

        metadata = {
            'timestamp': datetime.utcnow().isoformat() + "Z",
            'total_files': len(file_list),
            'total_size_kb': round(total_size, 2),
            'files': sorted(file_list, key=lambda x: x['path'])
        }

        # 写入元数据文件
        meta_path = os.path.join(cf_dir, 'file-list.json')
        with open(meta_path, 'w') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        
        return metadata