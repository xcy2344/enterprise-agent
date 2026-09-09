import logging
import sys
from datetime import datetime
import os


def setup_logger(name: str = "enterprise_kb") -> logging.Logger:
    """
    配置并返回日志记录器

    参数：
        name: 日志记录器名称

    返回：
        配置好的 Logger 对象
    """
    # 创建日志记录器
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # 如果已经有处理器了，不重复添加
    if logger.handlers:
        return logger

    # ===== 格式定义 =====
    # 格式：时间 - 名称 - 级别 - 消息
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # ===== 1. 控制台输出（显示在终端） =====
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # ===== 2. 文件输出（保存到文件） =====
    # 创建 logs 目录
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # 按日期命名日志文件：logs/app_2026-09-08.log
    log_filename = f"{log_dir}/app_{datetime.now().strftime('%Y-%m-%d')}.log"
    file_handler = logging.FileHandler(log_filename, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


# ===== 创建全局日志实例 =====
logger = setup_logger()