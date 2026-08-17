# ITrader

ITrader 的第一阶段原型：自动读取美国科技行业新闻和股票行情，以透明、可测试的规则生成交易信号，并在本地模拟账户中执行买卖。它不会连接真实券商账户，也不会发送真实订单。

## 当前闭环

1. `GoogleNewsRssProvider` 搜索最近的美国科技股新闻。
2. `YahooFinanceMarketData` 获取关注列表的最新公开行情。
3. `NewsMomentumStrategy` 识别公司、计算带时间衰减的标题情绪分数，并检查止损/止盈。
4. `TradingAgent` 应用单次交易、单股仓位、最低现金比例等限制。
5. `SimulatedBroker` 按滑点和手续费模拟成交，维护现金、持仓和交易流水。
6. 状态以 JSON 原子写入本地；同一条新闻不会重复触发交易。

默认关注：AAPL、MSFT、NVDA、AMZN、GOOGL、META、TSLA、AMD、AVGO。

> 这是策略工程原型，不构成投资建议。公开新闻与行情源可能延迟或临时不可用；在加入真实券商之前还必须完善交易时段、公司行动、数据质量和合规控制。

## 运行

要求 Python 3.11+，运行核心和测试都不需要安装第三方包。

```powershell
# 离线、确定性的买入演示
$env:PYTHONPATH = "src"
python -m itrader demo --initial-cash 100000

# 单次读取实时公开数据，并将模拟账户保存在 var/paper-state.json
python -m itrader run --once --initial-cash 100000

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
| 新闻买入阈值 | `0.75` |
| 新闻卖出阈值 | `-0.75` |
| 单股最大仓位 | 账户权益的 `20%` |
| 单次最大买入 | 账户权益的 `10%` |
| 最低现金保留 | 账户权益的 `10%` |
| 止损 | 成本价下方 `8%` |
| 止盈 | 成本价上方 `20%` |
| 新闻分数半衰期 | `12` 小时 |
| 模拟滑点 | `2 bps` |

当前卖出信号会清空该股票持仓；当前版本只做多、不融资、不卖空。规则集中在 `RiskConfig`，便于后续配置化和策略对比。

## 测试

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

测试使用固定新闻和固定价格，不访问网络，覆盖模拟成交、拒单、新闻衰减、止损、风险定仓、新闻去重和状态恢复。

## 下一阶段接口

`NewsProvider`、`MarketDataProvider` 和 `SimulatedBroker` 已分离。后续可以在不改策略的前提下接入有授权的数据源，把模拟券商替换为真实券商适配器，并增加：

- 正规新闻/行情 API 与数据缓存、限流、重试；
- 美股交易日历、盘前盘后策略和限价单；
- 财报、宏观事件、价格/成交量等多因子信号；
- 回测、基准对比、最大回撤和策略参数审计；
- 人工审批、熔断、幂等订单和实盘前 shadow mode。
