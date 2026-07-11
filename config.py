"""配置加载：从环境变量 / .env 读取。"""

import os
from dotenv import load_dotenv

load_dotenv()

ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY", "")
ZHIPU_MODEL = os.getenv("ZHIPU_MODEL", "glm-4")

# Agent 主循环最多调用工具的次数，防止死循环
MAX_TOOL_ITERATIONS = 8

# 数据缓存库路径
DB_PATH = os.getenv("TRADEMIND_DB_PATH", "trademind.db")
