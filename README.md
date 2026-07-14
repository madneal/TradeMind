# TradeMind

A 股票分析 Agent —— 基于 ReAct + function calling，用自然语言查询行情、计算技术指标、分析走势。

## 快速开始

```bash
# 1. 安装依赖
uv sync

# 2. 配置 API Key（默认 xAI Grok）
cp .env.example .env
# 编辑 .env 填入 XAI_API_KEY（https://console.x.ai）

# 3. 运行
uv run trademind chat                      # 进入交互式对话
uv run trademind chat "分析一下贵州茅台最近走势"  # 单次查询
```

## 能力

- **LLM**：默认 [xAI Grok](https://docs.x.ai)（`XAI_API_KEY` + `https://api.x.ai/v1`）
- **固定策略决策**：均线 / MACD / RSI / 布林 + **经营质量过滤(F0/F1)** + 持仓纪律 → 买入/卖出/观望
- **行情查询**：实时行情、历史 K 线
- **技术指标**：MA / MACD / RSI / KDJ / BOLL
- **持仓分析**：概览 / 盈亏 / 行业集中度
- **交互**：CLI 多轮对话 + 单次查询

```bash
uv run trademind strategies          # 查看固定买卖规则
uv run trademind signals             # 全持仓策略决策清单
uv run trademind signals 518880      # 单票决策
```
