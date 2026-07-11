# TradeMind

A 股票分析 Agent —— 基于 ReAct + function calling，用自然语言查询行情、计算技术指标、分析走势。

## 快速开始

```bash
# 1. 安装依赖
uv sync

# 2. 配置 API Key
cp .env.example .env
# 编辑 .env 填入智谱 API Key

# 3. 运行
uv run trademind                      # 进入交互式对话
uv run trademind "分析一下贵州茅台最近走势"  # 单次查询
```

## 能力

- **行情查询**：实时行情、历史 K 线
- **技术指标**：MA / MACD / RSI / KDJ / BOLL
- **交互**：CLI 多轮对话 + 单次查询
