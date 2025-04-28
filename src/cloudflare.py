import os
import json
import logging
from datetime import datetime
import requests

logger = logging.getLogger(__name__)

class CloudflareDeployer:
    @staticmethod
    def deploy(output_dir='output'):
        try:
            cf_dir = CloudflareDeployer.prepare_structure(output_dir)
            metadata = CloudflareDeployer.generate_metadata(output_dir, cf_dir)
            
            account_id = os.getenv("CF_ACCOUNT_ID")
            api_token = os.getenv("CF_API_TOKEN")
            project_name = os.getenv("CF_PROJECT_NAME", "node-subscription")

            if not account_id or not api_token:
                raise ValueError("缺少Cloudflare认证信息")

            version = datetime.now().strftime("%Y%m%d%H%M")
            deploy_cmd = (
                f"npx wrangler pages deploy {cf_dir} "
                f"--project-name {project_name} "
                f"--branch main "
                f"--env {version}"
            )
            
            exit_code = os.system(deploy_cmd)
            if exit_code != 0:
                raise RuntimeError(f"部署失败，退出码：{exit_code}")
            
            logger.info(f"成功部署版本 {version}")
            return True
        except Exception as e:
            logger.error(f"Cloudflare部署失败: {str(e)}", exc_info=True)
            return False

    @staticmethod
    def prepare_structure(output_dir):
        cf_dir = os.path.join(output_dir, 'cloudflare')
        os.makedirs(cf_dir, exist_ok=True)
        
        # 生成索引页面
        index_content = '''<!DOCTYPE html>
        <html>
        <!-- 索引页面内容 -->
        </html>'''
        
        with open(os.path.join(cf_dir, 'index.html'), 'w') as f:
            f.write(index_content)
            
        return cf_dir

    @staticmethod
    def generate_metadata(output_dir, cf_dir):
        file_list = []
        total_size = 0

        for root, _, files in os.walk(output_dir):
            for file in files:
                if 'cloudflare' in root:
                    continue
                
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, output_dir)
                size_kb = os.path.getsize(file_path) / 1024
                
                file_list.append({
                    'name': file,
                    'path': f'/{rel_path}',
                    'size': round(size_kb, 2)
                })
                total_size += size_kb

        metadata = {
            'timestamp': datetime.utcnow().isoformat() + "Z",
            'total_files': len(file_list),
            'total_size_kb': round(total_size, 2),
            'files': file_list      
        }
        
        meta_path = os.path.join(cf_dir, 'file-list.json')
        with open(meta_path, 'w') as f:
            json.dump(metadata, f, indent=2)
            
        return metadata
