# src/logger.py
import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Optional

def setup_logger(
    name: str = "getnode",
    log_level: int = logging.INFO,
    log_file: Optional[str] = "output/logs/getnode.log",
    max_bytes: int = 2 * 1024 * 1024,  # 2MB
    backup_count: int = 3
) -> logging.Logger:
    """统一日志配置
    
    Args:
        name: 日志器名称
        log_level: 日志级别
        log_file: 日志文件路径（None表示不保存到文件）
        max_bytes: 单个日志文件最大大小
        backup_count: 保留的备份文件数量
    """
    logger = logging.getLogger(name)
    logger.setLevel(log_level)

    # 统一的日志格式
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'
    )

    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 文件处理器（如果需要）
    if log_file:
        # 确保日志目录存在
        log_dir = os.path.dirname(log_file)
        os.makedirs(log_dir, exist_ok=True)
        
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger