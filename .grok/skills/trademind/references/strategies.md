# TradeMind 内置分析策略

## 固定买卖策略（strategy/，优先用于决策）

| ID | 名称 | 买入 | 卖出 |
|----|------|------|------|
| S1 | 均线趋势 | MA5>MA10>MA20 且价>MA20 | 空头排列且价<MA20 |
| S2 | MACD | DIF>DEA 且 HIST>0 | DIF<DEA 且 HIST<0 |
| S3 | RSI | RSI14<30 | RSI14>70 |
| S4 | 布林带 | 贴近下轨 | 贴近上轨 |
| S5 | 技术合成 | 净分≥2 → 买入 | 净分≤-2 → 卖出 |
| F0 | 合规警示 | 非 ST/退市风险才可买 | ST 超限/暴跌减仓 |
| F1 | 业绩质量 | 现金流健康才可买/加 | 净利>0且OCF<0 红灯禁买；应收/毛利异常黄灯禁加 |
| P1 | 单票仓位 | 仓位<30% 且技术买可加 | >30% 减仓，>40% 强烈减仓 |
| P2 | ST 纪律 | 禁止加仓 ST | 仓位>5% 或单日跌>8% 减仓 |
| P3 | 深套 | 禁止摊薄 | 浮亏≤-40% 仅反弹减仓 |
| P4 | 黄金主题 | 主题<45% 才可加 | ≥45% 停止加仓 |
| D1 | 最终决策 | 技术买+F0/F1+纪律允许 | 技术卖或纪律强制 |

ETF/场内基金跳过 F0/F1 财务层。
CLI：
- `uv run trademind strategies` 查看规则
- `uv run trademind signals` 全持仓决策
- `uv run trademind signals 518880` 单票决策

## 持仓组合（tools/portfolio.py）

| 工具 | 作用 |
|------|------|
| get_portfolio | 实时价、涨跌幅、市值、仓位占比 |
| analyze_pnl | 单票/组合浮盈亏、收益率排序 |
| analyze_portfolio_risk | 行业分布、HHI、单票/单行业过重告警 |

## 行情 / 指标

- get_quote / get_kline
- calc_indicators：MA / MACD / RSI / KDJ / BOLL

## 持仓文件

- 路径：项目根 `holdings.toml`（已 gitignore）
- 字段：code / shares / cost_price
