---
name: trademind
description: >
  Analyze A-share holdings with TradeMind local tools — no XAI_API_KEY required.
  Use Grok Build itself as the LLM: run portfolio/quote/kline/indicator scripts,
  then interpret results in Chinese. Triggers: "分析持仓", "分析我的持仓",
  "持仓盈亏", "持仓风险", "TradeMind", "trademind", "portfolio analysis",
  "用 skill 分析股票", "/trademind".
metadata:
  short-description: "TradeMind 持仓分析（无 API，Grok 直解）"
---

# TradeMind（Grok 直连分析）

在 **Grok Build 会话内**完成分析：本地 Python 拉行情/算指标，**由当前 Grok 解读**。  
**不要**调用 `uv run trademind chat`（那条路径需要 `XAI_API_KEY` / API credits）。

## 项目路径

默认项目根：`/Users/neal/project/TradeMind`  
若工作区已是 TradeMind，用当前根目录。

持仓文件：`<root>/holdings.toml`（个人数据，已 gitignore）。

## 工作流

### 1. 持仓全景（默认）

在项目根执行：

```bash
cd /Users/neal/project/TradeMind && uv run python .grok/skills/trademind/scripts/analyze.py --mode portfolio
```

得到 JSON：`overview` / `pnl` / `risk`。

### 2. 单票行情

```bash
cd /Users/neal/project/TradeMind && uv run python .grok/skills/trademind/scripts/analyze.py --mode quote --code 518880
```

### 3. K 线

```bash
cd /Users/neal/project/TradeMind && uv run python .grok/skills/trademind/scripts/analyze.py --mode kline --code 600418 --days 60
```

### 4. 技术指标

```bash
cd /Users/neal/project/TradeMind && uv run python .grok/skills/trademind/scripts/analyze.py --mode indicators --code 518880 --indicators MA,MACD,RSI,KDJ,BOLL
```

### 5. 组合管理（可选）

```bash
uv run trademind portfolio list
uv run trademind portfolio add <code> <shares> <cost>
uv run trademind portfolio remove <code>
```

也可直接编辑 `holdings.toml`。

策略说明见 `references/strategies.md`。

## 解读规范

1. **只基于工具 JSON**，不编造价格或盈亏。
2. `price=0` 或 name 为空 → 标明「行情缺失」，可用用户截图/成本推算，并说明依据。
3. 输出结构建议：
   - 组合摘要（总市值、总成本、总浮盈亏；注明数据缺口）
   - 仓位 Top / 拖累 Top
   - 行业与集中度（HHI、告警）
   - 单票亮点/风险（ST、单票过重、深套）
   - 可选：对 1–3 只重点票再拉 quote/indicators
4. **禁止**绝对买卖建议；用偏多/偏空/震荡、结构风险、分散建议等表述。
5. 用中文，表格优先。
6. 提醒：非实时投顾意见，注意时效与数据源降级。

## 与 API 模式的关系

| 方式 | 命令 | 是否需要 XAI_API_KEY |
|------|------|----------------------|
| **本 skill（推荐，无 API）** | 跑 `scripts/analyze.py` + Grok 解读 | 否 |
| CLI Agent | `uv run trademind chat "..."` | 是（console.x.ai credits） |

SuperGrok 是聊天订阅，**不能**替代 `api.x.ai` 的开发者额度。  
在 Grok Build 里用本 skill，等于用当前会话当「大脑」，本地工具当「手脚」。

## 触发后立刻做

用户说分析持仓 / 运行 `/trademind` 时：

1. `cd` 到 TradeMind 根目录  
2. 跑 `--mode portfolio`  
3. 如有重点代码，按需补 quote/indicators  
4. 输出结构化中文分析  
