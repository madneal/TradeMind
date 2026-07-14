# TradeMind 内置分析策略

## 持仓组合（tools/portfolio.py）

| 工具 | 作用 |
|------|------|
| get_portfolio | 实时价、涨跌幅、市值、仓位占比 |
| analyze_pnl | 单票/组合浮盈亏、收益率排序 |
| analyze_portfolio_risk | 行业分布、HHI、单票/单行业过重告警 |

风险阈值：
- 单票 > 40%
- 行业 HHI > 2500
- 持仓 < 3 只
- 单一行业 > 50%

## 行情（tools/market.py）

- get_quote：实时快照
- get_kline：历史日 K

## 技术指标（tools/indicators.py）

MA / MACD / RSI / KDJ / BOLL

## 持仓文件

- 路径：项目根 `holdings.toml`（已 gitignore）
- 字段：code / shares / cost_price
