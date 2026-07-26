---
name: trademind
description: >
  Analyze A-share holdings and individual stocks with TradeMind local tools —
  no XAI_API_KEY required. Use Grok Build as the LLM: run portfolio/quote/kline/
  indicator/signals scripts, then interpret in Chinese. When the user asks whether
  to BUY a new stock or asks for BUY/SELL TIMING, ALWAYS auto-load the personal
  knowledge base (avoid-checklist + failures + decision-template + strong-stock)
  before concluding.
  Triggers: "分析持仓", "能不能买", "该不该买", "买入时机", "卖出时机", "现在能买吗",
  "适合建仓吗", "加仓", "减仓时机", "TradeMind", "trademind", "/trademind",
  "失败库", "复盘入库".
metadata:
  short-description: "TradeMind 分析；新股买入/买卖时机自动对照知识库"
---

# TradeMind（Grok 直连分析）

在 **Grok Build 会话内**完成分析：本地 Python 拉行情/算指标，**由当前 Grok 解读**。  
**不要**调用 `uv run trademind chat`（那条路径需要 `XAI_API_KEY` / API credits）。

## 项目路径

默认项目根：`/Users/neal/project/TradeMind`  
若工作区已是 TradeMind，用当前根目录。

持仓文件：`<root>/holdings.toml`（个人数据，已 gitignore）。  
知识库：`<root>/notes/knowledge/`（个人，已 gitignore）。

---

## 知识库自动对照（仅决策场景，勿等用户手动叫）

**范围收窄：不是「凡分析个股都读库」，而是「新股要不要买」+「买卖时机判断」时自动读。**  
用户不必再说「查失败库」——在上述场景默认就做。

### 何时自动触发（是）

| 用户意图（示例说法） | 自动读知识库 |
|----------------------|--------------|
| **新标的要不要买 / 适合建仓吗**（「能不能买」「值得买吗」「看看这只新票」且含决策意味） | **是** |
| **买入时机**（「现在能进吗」「等回调再买」「追高吗」） | **是** |
| **卖出/减仓时机**（「该卖吗」「反弹出一点吗」「破位走吗」） | **是** |
| **已有持仓加仓时机**（「还能加吗」「摊平一点」） | **是** |

### 何时不自动读库（否）

| 用户意图 | 读知识库 |
|----------|----------|
| 纯持仓全景、盈亏表、报告服务 | 否 |
| 只查现价 / K 线 / 指标、无买卖决策 | 否 |
| 改 holdings、同步、技术排障 | 否 |
| 用户明确只要行情不要建议 | 否 |

边界：用户说「分析一下 XX」——若语境是**研究后决定买不买/何时买卖** → 读库；若只是**看看走势/持仓里这只怎样**且无决策句 → 可不读库，但一旦回复进入「建议买/卖/等」就必须先读库。

### 自动读取顺序（决策场景）

输出买卖相关结论前，**用 Read 实际打开**：

1. `notes/knowledge/principles/avoid-checklist.md`  
2. `notes/knowledge/failures/INDEX.md`  
3. INDEX 命中同代码或同类主题 → 读对应 `failures/*.md`  
4. **新股买入 / 建仓 / 加仓** → 再读 `decision-template.md`，检查退出条件是否写清  
5. **新股买入 / 建仓 / 是否按强者跟** → 再读 `principles/strong-stock.md`，按评分表判断是否 ≥7 分、有无否决项  

### 回复中的「知识库对照」节（仅决策场景必出）

放在行情 + 策略信号之后，聚焦**买/卖/等**：

1. **时机结论标签**：偏「可考虑试错建仓 / 等待更优买点 / 不宜追 / 反弹减仓窗 / 持有观望」等（非绝对保证）  
2. **命中应避免 ID**（A1 无退出、B4 摊平、B5 超卖当买点…）：是否踩雷  
3. **历史案例**一句话（有则引用，无则「暂无该代码案例」）  
4. **决策约束**：禁止 / 慎做 / 可做 ≤3 条；新开仓缺退出条件 → 提醒先补模板再下单  

### 自动入库（失败复盘）

主动提议入库（用户确认或说「直接入库」后写）：

- 复盘买错、总结教训  
- 浮亏很深且在讨论「下次怎么避免」  

动作：`failures/_template.md` → 更新 `INDEX.md` → 必要时追加 `avoid-checklist.md`。

---

## 工作流

### 0. 新股买入 / 买卖时机（决策管道，自动带知识库）

```text
1) 读知识库：avoid-checklist + failures/INDEX [+ 案例] [+ 买入/加仓则 decision-template + strong-stock]
2) quote + indicators + signals <code>
3) 可选 kline --days 60/90
4) 输出：事实 → 策略信号 → 买卖时机判断 → 知识库对照（含强势打分若适用）→ 情景（等/试/减）
```

```bash
cd /Users/neal/project/TradeMind
uv run python .grok/skills/trademind/scripts/analyze.py --mode quote --code <CODE>
uv run python .grok/skills/trademind/scripts/analyze.py --mode indicators --code <CODE> --indicators MA,MACD,RSI,KDJ,BOLL
uv run trademind signals <CODE>
# 可选：
uv run python .grok/skills/trademind/scripts/analyze.py --mode kline --code <CODE> --days 90
```

### 1. 持仓全景（默认不读知识库）

```bash
cd /Users/neal/project/TradeMind && uv run python .grok/skills/trademind/scripts/analyze.py --mode portfolio
```

得到 JSON：`overview` / `pnl` / `risk`。  
仅当用户接着问「这只能加/该卖吗」时，再走决策管道并读库。

### 1b. 固定策略买卖清单

```bash
cd /Users/neal/project/TradeMind && uv run trademind signals
# 单票：
uv run trademind signals 518880
```

规则说明：`uv run trademind strategies`。  
若用户要的是**时机/买卖决策**（而非只看表格），叠加知识库对照。

### 1c. HTML 报告

```bash
cd /Users/neal/project/TradeMind && uv run trademind report
uv run trademind report --no-signals
uv run trademind report -o /tmp/holdings.html
```

默认写入 `notes/reports/portfolio_时间戳.html`。

### 2–4. 行情 / K 线 / 指标

见上文管道命令；亦可单独：

```bash
uv run python .grok/skills/trademind/scripts/analyze.py --mode quote --code 518880
uv run python .grok/skills/trademind/scripts/analyze.py --mode kline --code 600418 --days 60
uv run python .grok/skills/trademind/scripts/analyze.py --mode indicators --code 518880 --indicators MA,MACD,RSI,KDJ,BOLL
```

### 5. 组合管理

```bash
uv run trademind portfolio list
uv run trademind portfolio add <code> <shares> <cost>
uv run trademind portfolio remove <code>
uv run trademind portfolio sync-ths
uv run trademind portfolio sync-ths --probe
```

也可直接编辑 `holdings.toml`。**双账户合并时禁止用单页截图覆盖另一户**（知识库 D1）。

策略说明见 `references/strategies.md`。

### 6. 知识库路径速查

| 文件 | 用途 |
|------|------|
| `notes/knowledge/README.md` | 总览 |
| `notes/knowledge/principles/avoid-checklist.md` | 应避免行为（**买入/时机决策时必读**） |
| `notes/knowledge/principles/decision-template.md` | 新开仓/加仓决策填空 |
| `notes/knowledge/principles/strong-stock.md` | 强势股打分定义（**建仓/强者跟随时必读**） |
| `notes/knowledge/principles/stop-loss.md` | 止损纪律 |
| `notes/knowledge/principles/winner-mindset.md` | 赢家思维（心态） |
| `notes/knowledge/failures/INDEX.md` | 案例索引（**买入/时机决策时必读**） |
| `notes/knowledge/failures/_template.md` | 新失败案例模板 |
| `notes/knowledge/failures/*.md` | 单案全文 |

---

## 解读规范

1. **只基于工具 JSON**；决策场景再叠加**已读知识库文件**，不编造清单条文。  
2. `price=0` 或 name 为空 → 标明「行情缺失」。  
3. **买卖时机 / 新股买入**输出结构：  
   - 事实（价、均线、量能）  
   - 策略信号（买/卖/观望）  
   - **买卖时机判断**（现在 / 等回踩 / 不宜）  
   - **知识库对照**（决策场景强制）  
   - 免责：非投资建议  
4. 纯持仓/行情可不写知识库节。  
5. **禁止**绝对买卖保证。  
6. 用中文，表格优先。

## 与 API 模式的关系

| 方式 | 命令 | 是否需要 XAI_API_KEY |
|------|------|----------------------|
| **本 skill（推荐，无 API）** | `scripts/analyze.py` +（决策时）知识库 + Grok 解读 | 否 |
| CLI Agent | `uv run trademind chat "..."` | 是 |

## 触发后立刻做

**分析持仓 / `/trademind`（非买卖决策）：**

1. `cd` 到 TradeMind → `--mode portfolio` → 结构化输出（**不强制读库**）

**新股要不要买 / 买入或卖出时机：**

1. `cd` 到 TradeMind  
2. **先读知识库**（avoid + INDEX [+ 案例] [+ 买入则 template]）  
3. quote + indicators + signals  
4. 输出含 **买卖时机判断** + **知识库对照**  
