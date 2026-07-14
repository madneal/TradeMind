"""固定策略参数与规则说明。

所有买卖信号均由规则引擎生成，阈值集中在此文件，便于统一调整。
"""

from __future__ import annotations

# ── 技术面阈值 ──
RSI_OVERSOLD = 30.0          # RSI14 低于此 → 超卖（偏买入）
RSI_OVERBOUGHT = 70.0        # RSI14 高于此 → 超买（偏卖出）
BOLL_TOUCH_RATIO = 0.15      # 价格距上下轨 / 带宽 的接近比例
TECH_BUY_SCORE = 2           # 技术子策略净分 ≥ 此 → 技术面买入
TECH_SELL_SCORE = -2         # 技术子策略净分 ≤ 此 → 技术面卖出

# ── 持仓纪律阈值 ──
MAX_SINGLE_WEIGHT = 30.0     # 单票市值占比超过 → 建议减仓
HARD_SINGLE_WEIGHT = 40.0    # 单票超过 → 强烈减仓
MAX_THEME_WEIGHT = 45.0      # 黄金链等主题合计超过 → 禁止加仓
DEEP_LOSS_PCT = -40.0        # 浮亏超过 → 反弹减仓优先，禁止摊薄
ST_MAX_WEIGHT = 5.0          # ST 仓位超过 → 减仓
ST_DAY_DROP = -8.0           # ST 单日跌幅超过 → 纪律减仓
MIN_CASH_HINT = 5.0          # 建议保留现金比例（结构提示）

# ── 成本纪律（用户原则）──
# 浮亏时不主动卖出/减仓「锁定亏损」；仅当基本面破坏时允许破例。
NO_LOSS_EXIT = True
# 基本面破坏判定：F0/F1 红灯，或 ST/*ST（见 engine）

# ── 经营业绩过滤 F0 / F1 ──
# F0：合规/警示（一票否决买入）
# F1：质量门槛（技术买入时的加仓资格）
OCF_TO_PROFIT_YELLOW = 0.3   # 经营现金流/净利润 < 此 → 黄灯（禁加仓）
# 净利润>0 且经营现金流<0 → 红灯（禁买入/加仓）
RECEIVABLE_VS_REVENUE_YOY_GAP = 25.0  # 应收增速 - 营收增速 > 此百分点 → 黄灯
GROSS_MARGIN_DROP_PP = 8.0   # 毛利率同比下降超过 N 个百分点 → 黄灯
# 场内基金代码前缀：跳过财务过滤
ETF_CODE_PREFIXES = ("11", "12", "15", "16", "17", "18", "50", "51", "52", "56", "58")

# 黄金链相关代码前缀/名单（用于主题集中度）
GOLD_THEME_CODES = frozenset({
    "518880",  # 黄金 ETF
    "159562",  # 黄金股 ETF
    "518850",
    "518800",
})
GOLD_THEME_NAME_KEYWORDS = ("黄金", "白银", "有色")

# ── 策略目录（给人看的固定清单）──
STRATEGY_CATALOG = [
    {
        "id": "S1_MA_TREND",
        "name": "均线趋势",
        "buy": "MA5>MA10>MA20 且 收盘价>MA20（多头排列）",
        "sell": "MA5<MA10<MA20 且 收盘价<MA20（空头排列）",
        "hold": "均线缠绕或价格与均线方向不一致",
    },
    {
        "id": "S2_MACD",
        "name": "MACD 动能",
        "buy": "DIF>DEA 且 HIST>0（多头动能）",
        "sell": "DIF<DEA 且 HIST<0（空头动能）",
        "hold": "动能不明或零轴附近反复",
    },
    {
        "id": "S3_RSI",
        "name": "RSI 超买超卖",
        "buy": f"RSI14 < {RSI_OVERSOLD:.0f}（超卖）",
        "sell": f"RSI14 > {RSI_OVERBOUGHT:.0f}（超买）",
        "hold": "RSI 处于中间区间",
    },
    {
        "id": "S4_BOLL",
        "name": "布林带位置",
        "buy": "价格贴近下轨（均值回归偏多）",
        "sell": "价格贴近上轨（均值回归偏空）",
        "hold": "价格在中轨附近",
    },
    {
        "id": "S5_COMPOSITE",
        "name": "技术面合成",
        "buy": f"S1~S4 净分 ≥ {TECH_BUY_SCORE} → 技术面「买入」",
        "sell": f"S1~S4 净分 ≤ {TECH_SELL_SCORE} → 技术面「卖出」",
        "hold": "其余 → 技术面「观望」",
    },
    {
        "id": "F0_COMPLIANCE",
        "name": "合规与警示（一票否决）",
        "buy": "非 ST/*ST/退市整理 且无强制否决标签 → 允许进入后续规则",
        "sell": "ST/*ST 仓位超限或单日暴跌 → 优先减仓；名称含退市风险 → 禁止买入",
        "hold": "ETF/指数基金跳过本层",
    },
    {
        "id": "F1_QUALITY",
        "name": "业绩质量过滤",
        "buy": "技术买入时：经营现金流健康、应收/营收不过分背离、毛利率无骤降 → 允许建仓/加仓",
        "sell": f"红灯：净利>0且经营现金流<0 → 禁止买入/加仓；黄灯：现金流/净利<{OCF_TO_PROFIT_YELLOW} 或应收增速远快于营收 → 禁止加仓",
        "hold": "财务数据缺失 → 不否决、降低置信度；ETF 跳过",
    },
    {
        "id": "P1_WEIGHT",
        "name": "单票仓位纪律",
        "buy": f"未持有或仓位 < {MAX_SINGLE_WEIGHT:.0f}% 且技术面买入时，允许小仓建仓/加仓",
        "sell": f"仓位 > {MAX_SINGLE_WEIGHT:.0f}% 减仓；> {HARD_SINGLE_WEIGHT:.0f}% 强烈减仓",
        "hold": "仓位适中",
    },
    {
        "id": "P2_ST",
        "name": "ST 纪律",
        "buy": "禁止新建/加仓 ST",
        "sell": f"ST 仓位 > {ST_MAX_WEIGHT:.0f}% 或 单日跌幅 < {ST_DAY_DROP:.0f}% → 减仓/清仓优先",
        "hold": "无 ST 或仓位极小",
    },
    {
        "id": "P3_DEEP_LOSS",
        "name": "深套纪律",
        "buy": "禁止对浮亏超过阈值的标的摊薄补仓",
        "sell": f"浮亏 < {DEEP_LOSS_PCT:.0f}% → 仅允许反弹减仓，不要求立刻市价砍仓",
        "hold": "浮亏未达深套线",
    },
    {
        "id": "P4_THEME",
        "name": "主题集中度（黄金链）",
        "buy": f"黄金相关主题合计 < {MAX_THEME_WEIGHT:.0f}% 时才允许加黄金方向",
        "sell": f"黄金相关主题合计 ≥ {MAX_THEME_WEIGHT:.0f}% → 停止加仓，反弹优先减波动更大的黄金股",
        "hold": "主题占比可控",
    },
    {
        "id": "P5_NO_LOSS_EXIT",
        "name": "成本纪律（不亏本了结）",
        "buy": "不适用（本规则约束卖出侧）",
        "sell": "仅当基本面破坏（F0/F1 红灯或 ST）时，允许在浮亏中卖出/减仓",
        "hold": "浮亏且基本面未破坏 → 即使技术卖出/仓位偏高，也不主动锁定亏损，改为观望待成本附近或转盈再议",
    },
    {
        "id": "D1_DECISION",
        "name": "最终决策合成",
        "buy": "技术面买入 + F0/F1 与持仓纪律均允许 → 「买入/加仓」",
        "sell": "技术面卖出 或 纪律减仓，且（已盈利 或 基本面破坏）→ 「卖出/减仓」",
        "hold": "信号冲突、财务限制，或 浮亏且基本面未破坏 → 「观望/持有」",
    },
    {
        "id": "E1_EXECUTION",
        "name": "执行计划（数量与价格）",
        "buy": "加仓约现有仓 15% 或新建 1 手；T+1 开盘限价（现价上浮约 0.5%）",
        "sell": "按原因定比例：ST/基本面破坏可浮亏减；技术卖出默认等不亏再执行；T+1 开盘分批",
        "hold": "观望不挂单；浮亏持有待修复",
    },
]
