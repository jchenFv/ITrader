import unittest
from datetime import datetime, timedelta, timezone

from itrader.broker import SimulatedBroker
from itrader.models import NewsArticle, Quote, Side
from itrader.strategy import NewsMomentumStrategy, RiskConfig


class NewsMomentumStrategyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.strategy = NewsMomentumStrategy(watchlist={"NVDA": ("nvidia",)})
        self.quote = Quote("NVDA", 100, self.now)

    def test_positive_company_news_creates_buy_intent(self) -> None:
        article = NewsArticle(
            "Nvidia beats estimates with record growth",
            published_at=self.now,
        )
        portfolio = SimulatedBroker(10_000).snapshot({"NVDA": 100})
        intents = self.strategy.evaluate(
            [article], {"NVDA": self.quote}, portfolio, now=self.now
        )
        self.assertEqual([(item.symbol, item.side) for item in intents], [("NVDA", Side.BUY)])

    def test_old_news_decays_below_threshold(self) -> None:
        article = NewsArticle("Nvidia beats estimates", published_at=self.now - timedelta(days=3))
        portfolio = SimulatedBroker(10_000).snapshot({"NVDA": 100})
        intents = self.strategy.evaluate(
            [article], {"NVDA": self.quote}, portfolio, now=self.now
        )
        self.assertEqual(intents, [])

    def test_stop_loss_overrides_news(self) -> None:
        broker = SimulatedBroker(10_000, slippage_bps=0)
        broker.submit_market_order("NVDA", Side.BUY, 10, 100, reason="seed", timestamp=self.now)
        quote = Quote("NVDA", 90, self.now)
        portfolio = broker.snapshot({"NVDA": 90})
        intents = self.strategy.evaluate([], {"NVDA": quote}, portfolio, now=self.now)
        self.assertEqual(intents[0].side, Side.SELL)
        self.assertIn("stop loss", intents[0].reason)


if __name__ == "__main__":
    unittest.main()

