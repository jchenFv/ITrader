from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from typing import Sequence

from .broker import OrderRejected, SimulatedBroker
from .models import NewsArticle, Quote, Side, Trade
from .providers import MarketDataProvider, NewsProvider
from .strategy import NewsMomentumStrategy


@dataclass(frozen=True, slots=True)
class CycleReport:
    timestamp: datetime
    articles_seen: int
    new_articles: int
    quotes_received: int
    trades: tuple[Trade, ...]
    rejected: tuple[str, ...]
    cash: float
    equity: float


class TradingAgent:
    def __init__(
        self,
        *,
        broker: SimulatedBroker,
        news_provider: NewsProvider,
        market_data: MarketDataProvider,
        strategy: NewsMomentumStrategy,
        state_path: Path | None = None,
    ) -> None:
        self.broker = broker
        self.news_provider = news_provider
        self.market_data = market_data
        self.strategy = strategy
        self.state_path = state_path
        self.processed_article_ids: set[str] = set()

    def run_cycle(self, *, now: datetime | None = None) -> CycleReport:
        now = now or datetime.now(timezone.utc)
        articles = self.news_provider.fetch()
        new_articles = [
            article for article in articles if article.article_id not in self.processed_article_ids
        ]
        quotes = self.market_data.get_quotes(list(self.strategy.watchlist))
        prices = {symbol: quote.price for symbol, quote in quotes.items()}
        before = self.broker.snapshot(prices)
        intents = self.strategy.evaluate(new_articles, quotes, before, now=now)

        executed: list[Trade] = []
        rejected: list[str] = []
        for intent in intents:
            quote = quotes.get(intent.symbol)
            if quote is None:
                rejected.append(f"{intent.symbol}: quote unavailable")
                continue
            quantity = self._size_order(intent.symbol, intent.side, quote, prices)
            if quantity <= 0:
                rejected.append(f"{intent.symbol} {intent.side}: risk limits produced zero shares")
                continue
            try:
                executed.append(
                    self.broker.submit_market_order(
                        intent.symbol,
                        intent.side,
                        quantity,
                        quote.price,
                        reason=intent.reason,
                        timestamp=now,
                    )
                )
            except OrderRejected as exc:
                rejected.append(f"{intent.symbol} {intent.side}: {exc}")

        self.processed_article_ids.update(article.article_id for article in new_articles)
        if self.state_path:
            self.save_state()
        after = self.broker.snapshot(prices)
        return CycleReport(
            timestamp=now,
            articles_seen=len(articles),
            new_articles=len(new_articles),
            quotes_received=len(quotes),
            trades=tuple(executed),
            rejected=tuple(rejected),
            cash=after.cash,
            equity=after.equity,
        )

    def _size_order(self, symbol: str, side: Side, quote: Quote, prices: dict[str, float]) -> int:
        position = self.broker.positions.get(symbol)
        if side == Side.SELL:
            return position.quantity if position else 0

        snapshot = self.broker.snapshot(prices)
        current_value = position.market_value(quote.price) if position else 0.0
        max_position_value = snapshot.equity * self.strategy.risk.max_position_fraction
        trade_budget = min(
            snapshot.equity * self.strategy.risk.max_trade_fraction,
            max(0.0, max_position_value - current_value),
            max(0.0, snapshot.cash - snapshot.equity * self.strategy.risk.min_cash_fraction),
        )
        estimated_unit_cost = quote.price * (1 + self.broker.slippage_bps / 10_000)
        return max(0, int((trade_budget - self.broker.commission) // estimated_unit_cost))

    def save_state(self) -> None:
        if not self.state_path:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "broker": self.broker.to_dict(),
            "processed_article_ids": sorted(self.processed_article_ids),
        }
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.state_path.parent,
            prefix=f".{self.state_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            temp_path = Path(handle.name)
        temp_path.replace(self.state_path)

    @classmethod
    def load(
        cls,
        state_path: Path,
        *,
        news_provider: NewsProvider,
        market_data: MarketDataProvider,
        strategy: NewsMomentumStrategy,
    ) -> "TradingAgent":
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != 1:
            raise ValueError("unsupported state schema")
        agent = cls(
            broker=SimulatedBroker.from_dict(payload["broker"]),
            news_provider=news_provider,
            market_data=market_data,
            strategy=strategy,
            state_path=state_path,
        )
        agent.processed_article_ids = set(payload.get("processed_article_ids", []))
        return agent

