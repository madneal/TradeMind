# TradeMind

**A 股个人交易研究 Agent** —— 客观数据底稿 + 固定纪律规则 + 可选 LLM 解读。

- **只做 A 股**（含沪深京场内 ETF）
- **决策以规则为准**（`decide_*` / F0·F1 / 持仓纪律 / 强势分），LLM 负责组织与解释
- **底稿先行**：行情、财务质量、市场情绪先由 Python 算好 JSON，禁止模型臆造缺失字段
- 研究框架借鉴 [Vibe-Research](https://github.com/simonlin1212/Vibe-Research)，**保留买卖规则出口**（不做成「只研究不决策」）

> 规则信号与管道结论 **不构成投资建议**。

---

## 快速开始

```bash
# 1. 安装
uv sync

# 2. 配置 LLM（对话 chat 需要；review / buy / signals 等可无 Key）
cp .env.example .env
# 编辑 .env：XAI_API_KEY=...（默认 xAI Grok）

# 3. 持仓（个人文件，已 gitignore）
# 编辑 holdings.toml：positions + cash + total_deposits（累计净入金）
# 现金口径：cash = Σ(各户总资产 − 持仓表市值合计)，含逆回购

# 4. 常用
uv run trademind review              # 每日复盘
uv run trademind signals             # 持仓买卖清单
uv run trademind buy 300274          # 新开仓管道
uv run trademind chat "持仓怎么操作"  # 多轮 Agent（需 API Key）
```

---

## 能力总览

| 层 | 能力 |
|----|------|
| **行情** | 实时报价、日 K、MA/MACD/RSI/KDJ/BOLL |
| **市场** | 指数、同花顺强势题材、板块主力资金、涨停/炸板情绪 |
| **财务** | F0 合规/ST；F1 经营现金流 vs 净利、应收、毛利 |
| **强势** | 10 分制（MA20 / 多头 / 回撤 / RS / 量价），≥7 且无否决可按强者策略 |
| **决策** | 技术合成 + 经营过滤 + 仓位/ST/深套/主题纪律 → 买/加/卖/减/观望 |
| **管道** | 买入评估、多空辩论（验证清单 + 规则收尾）、反思清单 |
| **组合** | 持仓/盈亏/主题暴露、每日复盘、HTML 报告、本地服务 |
| **账本** | 自选股、已清仓记录 |
| **接入** | CLI · ReAct chat · MCP · Grok skill（无 Key 本地脚本） |

---

## CLI 命令

### 市场与复盘

```bash
uv run trademind review              # 指数/情绪/板块/热点 + 持仓 + 纪律 → notes/market/
uv run trademind review -f           # 额外扫描持仓 F0/F1（较慢）
uv run trademind review --no-print   # 只写文件
uv run trademind scan-strong         # 当日强势池 ∩ 强势分 ∩ F0/F1
uv run trademind scan-strong --min-score 7 --top 12
```

### 个股研究与决策

```bash
uv run trademind buy 600519          # 底稿 → 强势 → F1 → decide → 知识库提醒 → 反思框架
uv run trademind debate 600418       # 多方/空方要点 + 主持验证清单 + 规则收尾
uv run trademind signals             # 全持仓固定策略清单
uv run trademind signals 518880      # 单票
uv run trademind strategies          # 规则目录
uv run trademind backtest 518880     # 单票技术规则回测
uv run trademind backtest            # 持仓分票回测
```

### 持仓与报告

```bash
uv run trademind portfolio list
uv run trademind portfolio add 600519 100 1500.5
uv run trademind portfolio remove 600519
uv run trademind portfolio sync-ths          # 历史成交 Lscj 辅助（非实时持仓主源）
uv run trademind report                      # HTML：资产 KPI + 市场 + 纪律 + 信号
uv run trademind report --no-signals         # 更快
uv run trademind report --no-market          # 不拉市场
uv run trademind serve                       # 本地报告服务（默认 :8765）
```

### 自选 / 清仓账本

```bash
uv run trademind watch add 600519,000858,300274
uv run trademind watch list
uv run trademind watch remove 000858
uv run trademind closed add 000887 600 16.808 17.02 -n "清仓中鼎"
uv run trademind closed list
```

### 对话 Agent（需 API Key）

```bash
uv run trademind chat
uv run trademind chat "分析一下持仓风险"
```

---

## Agent 工具（23）

导入 `tools` 即注册，供 `chat` / MCP 共用。

| 类别 | 工具名 |
|------|--------|
| 行情 | `get_quote` · `get_kline` · `calc_indicators` |
| 持仓 | `get_portfolio` · `analyze_pnl` · `analyze_portfolio_risk` |
| 市场 | `get_indices` · `get_hot_stocks` · `get_board_fund_flow` · `get_limit_sentiment` · `daily_review` |
| 研究 | `get_announcements` · `build_stock_dossier` · `score_strong` · `buy_pipeline` · `debate_code` · `scan_strong_stocks` |
| 决策 | `list_strategies` · `decide_code` · `decide_portfolio` |
| 其它 | `reflect_analysis` · `list_watchlist` · `list_closed_positions` |

**管道约定**

1. 问「能不能买 / 建仓」→ 优先 `buy_pipeline`（或等价 CLI `trademind buy`）
2. 问「该买还是卖 / 调仓」→ 必须先 `decide_code` / `decide_portfolio`
3. 工具返回 `error` / `missing` 的字段 **禁止编造**
4. F0/F1 红灯、ST、强势否决 **不得被叙事覆盖**

---

## 固定策略摘要

详见 `uv run trademind strategies` 与 `strategy/rules.py`。

| 编号 | 内容 |
|------|------|
| S1–S4 / S5 | 均线 · MACD · RSI · 布林 → 技术净分合成 |
| F0 | ST / 退市类名称 → 禁止买入加仓 |
| F1 | 净利>0 且经营现金流<0 等 → 红灯；现金流质量/应收/毛利 → 黄灯 |
| P1–P6 | 仓位、ST、深套禁摊平、黄金主题、主题单票成本≤总资产 5% 等 |
| P5 | 允许按纪律浮亏减/清（成本不是唯一锚） |
| 强势分 | ≥7 且无「破 MA20 / 放量长阴」否决 → 可按强者策略讨论 |

个人知识库（可选，gitignore）：`notes/knowledge/`  
含 `avoid-checklist` · `strong-stock` · `stop-loss` · `failures/` 等。Grok skill 在买卖时机场景会自动对照。

---

## 数据与本地文件

| 路径 | 说明 |
|------|------|
| `holdings.toml` | 持仓 + `cash`（**勿提交**） |
| `watchlist.toml` | 自选 |
| `closed.toml` | 已清仓 |
| `notes/market/` | 每日复盘 Markdown（`latest-ashare.md`） |
| `notes/reports/` | HTML 报告（`portfolio_latest.html`） |
| `notes/knowledge/` | 个人原则与失败库 |
| `trademind.db` | 行情/财务缓存 |

**现金口径（两户统一）**

```text
cash = Σ(账户总资产 − 该户持仓表「市值」之和)
```

`total_deposits` 是累计净入金成本，仅在新增入金或出金时调整。报告中的
“累计收益”按 `总资产 − total_deposits` 计算，与持仓成本口径的“浮盈亏”并列展示。

持仓表只有股票/ETF；逆回购等不在表内、但在总资产里，差额全部计入现金。  
不要用「总资产 − 左侧总市值」——左侧总市值可能已含逆回购，会漏算现金。

**数据源**

- 行情：新浪 / 腾讯 / mootdx（K 线）
- 财务：东财三表（F1，有缓存）
- 市场：同花顺热点、东财板块资金与涨停池（`data/em_http.py` 限流）

---

## MCP

把同一套工具挂到 Claude Code 等客户端：

```bash
claude mcp add trademind -- \
  uv run --directory /绝对路径/TradeMind python mcp_server.py
```

---

## 目录结构

```text
TradeMind/
├── agent/           # ReAct 循环 + system prompts
├── strategy/        # 规则引擎、执行计划、强势分、扫描、管道、回测
├── data/            # 行情、行业、东财限流、市场研究源、同花顺本地
├── tools/           # function-calling 工具注册
├── report/          # HTML 报告 + 本地 serve
├── portfolio.py     # 持仓读写
├── watchlist.py     # 自选
├── closed_ledger.py # 清仓账本
├── mcp_server.py    # MCP stdio
├── cli.py           # trademind 入口
└── notes/           # 复盘 / 报告 / 知识库（个人）
```

---

## 与 Vibe-Research 的关系

| 借鉴 | 本项目自有 |
|------|------------|
| 底稿先行、市场复盘信息架构 | 固定买卖规则 + 执行计划 |
| 多空验证清单、反思框架 | F0/F1、强势分、知识库纪律 |
| 工具裁剪与东财限流 | holdings 现金口径、双账户合并 |
| MCP 出口 | CLI 管道 `buy` / `debate` / `scan-strong` |

**明确不做：** 港美股数据层、自动下单、目标价/荐股排名。

---

## 配置

| 变量 | 含义 | 默认 |
|------|------|------|
| `XAI_API_KEY` | LLM Key | （chat 必填） |
| `XAI_MODEL` | 模型名 | `grok-4.5` |
| `XAI_BASE_URL` | API Base | `https://api.x.ai/v1` |
| `TRADEMIND_HOLDINGS_PATH` | 持仓文件 | `holdings.toml` |
| `TRADEMIND_DB_PATH` | 缓存库 | `trademind.db` |

兼容 OpenAI 协议的网关可改 `XAI_BASE_URL` + Key。

---

## 免责声明

本项目仅供学习与个人研究。行情与财务可能延迟或缺失；策略与管道输出为规则信号，**不构成投资建议**。市场有风险，决策自负。
