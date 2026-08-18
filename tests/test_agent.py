import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from itrader.agent import TradingAgent
from itrader.broker import SimulatedBroker
from itrader.models import NewsArticle, ResearchReport, Side
from itrader.providers import StaticMarketDataProvider, StaticNewsProvider
from itrader.strategy import NewsMomentumStrategy


class TradingAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.article = NewsArticle(
            "Nvidia beats estimates with record growth",
            source="test",
            url="test://one",
            published_at=self.now,
        )

    def _agent(self, state_path: Path | None = None) -> TradingAgent:
        return TradingAgent(
            broker=SimulatedBroker(10_000, slippage_bps=0),
            news_provider=StaticNewsProvider([self.article]),
            market_data=StaticMarketDataProvider({"NVDA": 100}),
            strategy=NewsMomentumStrategy(watchlist={"NVDA": ("nvidia",)}),
            state_path=state_path,
        )

    def test_cycle_executes_risk_sized_buy_only_once(self) -> None:
        agent = self._agent()
        first = agent.run_cycle(now=self.now)
        second = agent.run_cycle(now=self.now)
        self.assertEqual(len(first.trades), 1)
        self.assertEqual(first.trades[0].side, Side.BUY)
        self.assertEqual(first.trades[0].quantity, 10)  # 10% of equity
        self.assertEqual(len(second.trades), 0)  # headline was already processed

    def test_negative_news_liquidates_existing_position(self) -> None:
        agent = self._agent()
        agent.run_cycle(now=self.now)
        bad_news = NewsArticle(
            "Nvidia plunges as weak demand forces company to cut guidance",
            source="test",
            url="test://two",
            published_at=self.now + timedelta(minutes=5),
        )
        agent.news_provider = StaticNewsProvider([bad_news])
        agent.market_data = StaticMarketDataProvider({"NVDA": 98})
        report = agent.run_cycle(now=self.now + timedelta(minutes=5))
        self.assertEqual(len(report.trades), 1)
        self.assertEqual(report.trades[0].side, Side.SELL)
        self.assertNotIn("NVDA", agent.broker.positions)

    def test_partial_quotes_use_cached_prices_for_valuation_and_risk_sizing(self) -> None:
        broker = SimulatedBroker(10_000, slippage_bps=0)
        broker.submit_market_order("NVDA", Side.BUY, 10, 100, reason="seed")
        apple_news = NewsArticle(
            "Apple beats estimates with record growth",
            source="test",
            url="test://apple-positive",
            published_at=self.now,
        )
        agent = TradingAgent(
            broker=broker,
            news_provider=StaticNewsProvider([apple_news]),
            # This cycle has an AAPL quote but is missing the existing NVDA holding.
            market_data=StaticMarketDataProvider({"AAPL": 100}),
            strategy=NewsMomentumStrategy(
                watchlist={"NVDA": ("nvidia",), "AAPL": ("apple",)}
            ),
        )
        agent.last_prices = {"NVDA": 200}

        report = agent.run_cycle(now=self.now)

        self.assertEqual(report.prices, {"NVDA": 200, "AAPL": 100})
        self.assertEqual(report.trades[0].symbol, "AAPL")
        self.assertEqual(report.trades[0].quantity, 11)  # 10% of $11,000 equity
        self.assertEqual(report.equity, 11_000)
        self.assertEqual(broker.snapshot(report.prices).equity, report.equity)

    def test_state_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            agent = self._agent(path)
            agent.run_cycle(now=self.now)
            agent.last_research = ResearchReport(
                generated_at=self.now,
                model="test-model",
                market_summary="test summary",
                industry_views=(),
                recommendations=(),
            )
            agent.save_state()
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 1)

            loaded = TradingAgent.load(
                path,
                news_provider=StaticNewsProvider([self.article]),
                market_data=StaticMarketDataProvider({"NVDA": 100}),
                strategy=NewsMomentumStrategy(watchlist={"NVDA": ("nvidia",)}),
            )
            self.assertEqual(loaded.broker.positions["NVDA"].quantity, 10)
            self.assertEqual(loaded.last_research.model, "test-model")
            self.assertEqual(len(loaded.run_cycle(now=self.now).trades), 0)


if __name__ == "__main__":
    unittest.main()
