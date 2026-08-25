# ITrader

ITrader 是一个新闻驱动的美国科技股模拟交易原型。它可以让 LLM 主动搜索近期新闻、分析行业价值并生成结构化交易参考，再由本地风控和模拟券商决定是否成交。它不会连接真实券商账户，也不会发送真实订单。

## 当前 Agent 架构

Agent 现在分成两个权限明确的部分：

- **LLM 研究员**：通过 OpenAI Responses API 的 Web Search 主动检索约 72 小时内的材料，分析行业供需、竞争、监管、催化剂和风险，输出行业观点、来源以及 `BUY`/`SELL`/`HOLD` 建议。
- **本地执行器**：验证股票是否在关注列表、是否有本轮有效报价、置信度是否达标，并强制执行现金、仓位、止损、止盈和禁止卖空规则。LLM 没有直接下单权限。

LLM 输出采用严格 JSON Schema。网页和 RSS 内容会被明确视为不可信证据，不能改变系统任务、输出格式或风控政策。原来的关键词策略仍作为可选基线和 `auto` 模式的故障回退。

## 当前闭环

1. RSS 收集器提供一组待核实的种子标题；失败时 LLM 仍能独立搜索。
2. LLM 使用 Web Search 主动查找近期公司、行业和监管材料。
3. LLM 形成带来源、置信度、时间跨度和风险说明的结构化研究报告。
4. `YahooFinanceMarketData` 获取关注列表的最新公开行情。
5. `TradingAgent` 和本地风控筛选候选信号并计算允许的交易规模。
6. `SimulatedBroker` 按滑点和手续费模拟成交，维护现金、持仓和交易流水。
7. 状态以 JSON 原子写入本地，包括最近行情、研究报告和交易历史。

默认关注：AAPL、MSFT、NVDA、AMZN、GOOGL、META、TSLA、AMD、AVGO。

> 这是策略工程原型，不构成投资建议。公开新闻与行情源可能延迟或临时不可用；在加入真实券商之前还必须完善交易时段、公司行动、数据质量和合规控制。

## 运行

要求 Python 3.11+，运行核心和测试都不需要安装第三方包。LLM 模式需要 OpenAI API key；key 只从环境变量读取，不会写入状态文件。

### 配置 LLM

```powershell
$env:OPENAI_API_KEY = "你的 API key"
$env:PYTHONPATH = "src"

# 严格 LLM 模式：API 失败则停止本轮
python -m itrader gui --strategy llm --llm-model gpt-5.6-terra
```

策略模式：

| 模式 | 行为 |
|---|---|
| `auto` | 默认；有 API key 时使用 LLM，LLM 请求失败则回退规则策略；没有 key 时使用规则策略 |
| `llm` | 强制 LLM 研究；缺少 key 或 API 失败时不生成新交易 |
| `rules` | 仅使用原来的确定性关键词策略，适合离线测试和基准比较 |

`--llm-confidence 0.70` 控制候选交易的最低置信度；`--openai-api-base` 可配置 Responses API 地址。每次 LLM 研究会产生模型 token 和 Web Search 工具费用，建议先用手动周期测试，再开启自动运行。

### 桌面 GUI（推荐）

```powershell
$env:PYTHONPATH = "src"
python -m itrader gui --initial-cash 100000 --strategy auto
```

GUI 与命令行默认共用 `var/paper-state.json`，可以查看：

- 可用现金、持仓市值、账户权益和累计盈亏；
- 股票、股数、平均成本、最新价格、未实现盈亏和收益率；
- 每一笔历史成交的时间、方向、价格、费用和决策原因；
- 每轮抓取的新闻数量、行情数量、成交和跳过信号数量。
- 最近一份 LLM 行业研究，包括催化剂、风险、来源和逐股建议。

点击“运行一轮模拟”会在后台抓取新闻、LLM 研究和行情；“查看 LLM 研究”用于阅读完整报告。开启“自动”后按照 `--interval` 周期运行。所有按钮都只操作本地模拟账户，窗口中的“纯模拟”标志用于明确区分实盘。

### 命令行

```powershell
# 离线、确定性的买入演示
$env:PYTHONPATH = "src"
python -m itrader demo --initial-cash 100000

# 单次读取实时公开数据，并将模拟账户保存在 var/paper-state.json
python -m itrader run --once --initial-cash 100000 --strategy auto

# 每 5 分钟循环；Ctrl+C 安全停止
python -m itrader run --interval 300 --initial-cash 100000
```

也可以安装为开发包后使用 `itrader demo` / `itrader run`：

```powershell
python -m pip install -e .
```

已有状态文件时，`--initial-cash` 会被忽略，程序会恢复原现金、持仓、流水和已处理新闻 ID。若要开始新的模拟实验，请给 `--state` 传入另一个文件路径。

## 策略与风控默认值

| 规则 | 默认值 |
|---|---:|
| LLM 候选交易置信度 | `70%` |
| 单股最大仓位 | 账户权益的 `20%` |
| 单次最大买入 | 账户权益的 `10%` |
| 最低现金保留 | 账户权益的 `10%` |
| 止损 | 成本价下方 `8%` |
| 止盈 | 成本价上方 `20%` |
| 模拟滑点 | `2 bps` |

当前卖出信号会清空该股票持仓；当前版本只做多、不融资、不卖空。止损和止盈属于本地规则，即使 LLM 建议相反也不能覆盖。规则模式仍保留新闻阈值和 12 小时分数半衰期。

## 测试

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

测试使用固定新闻、固定价格和模拟 LLM 响应，不访问网络，覆盖 API 请求结构、Web Search 启用、结构化输出、置信度过滤、重复建议、LLM 故障回退、模拟成交、止损、风险定仓和状态恢复。

## 下一阶段接口

`NewsProvider`、`MarketDataProvider` 和 `SimulatedBroker` 已分离。后续可以在不改策略的前提下接入有授权的数据源，把模拟券商替换为真实券商适配器，并增加：

- 正规新闻/行情 API 与数据缓存、限流、重试；
- 美股交易日历、盘前盘后策略和限价单；
- 财报、宏观事件、价格/成交量等多因子信号；
- 回测、基准对比、最大回撤和策略参数审计；
- 人工审批、熔断、幂等订单和实盘前 shadow mode。
