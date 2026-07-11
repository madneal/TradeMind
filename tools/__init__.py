"""工具包。导入即触发各工具模块的注册。"""

from tools import market, indicators  # noqa: F401
from tools.registry import register, get_tool, list_tools, call_tool, all_schemas  # noqa: F401
