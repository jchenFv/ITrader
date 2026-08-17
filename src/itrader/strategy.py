from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import math
import re
from typing import Iterable, Mapping

from .models import NewsArticle, PortfolioSnapshot, Quote, Side, TradeIntent


DEFAULT_WATCHLIST: dict[str, tuple[str, ...]] = {
    "AAPL": ("apple", "iphone", "ipad", "macbook"),
    "MSFT": ("microsoft", "azure", "windows", "openai"),
    "NVDA": ("nvidia", "geforce", "cuda"),
    "AMZN": ("amazon", "aws"),
    "GOOGL": ("google", "alphabet", "gemini"),
    "META": ("meta", "facebook", "instagram", "whatsapp"),
    "TSLA": ("tesla", "elon musk"),
    "AMD": ("amd", "advanced micro devices", "ryzen"),
    "AVGO": ("broadcom", "vmware"),
}

POSITIVE_TERMS: dict[str, float] = {
    "beat": 1.0,
    "beats": 1.0,
    "surge": 1.2,
    "record": 0.9,
    "upgrade": 1.1,
    "growth": 0.7,
    "profit": 0.8,
    "launch": 0.4,
    "partnership": 0.6,
    "approval": 0.8,
    "breakthrough": 1.0,
    "strong demand": 1.0,
    "raises guidance": 1.4,
}

NEGATIVE_TERMS: dict[str, float] = {
    "miss": -1.0,
    "misses": -1.0,
    "plunge": -1.3,
    "downgrade": -1.1,
    "lawsuit": -0.7,
    "investigation": -0.8,
    "recall": -1.0,
    "layoff": -0.6,
    "decline": -0.7,
    "weak demand": -1.0,
    "cuts guidance": -1.4,
    "data breach": -1.2,
    "ban": -1.0,
}


@dataclass(frozen=True, slots=True)
class RiskConfig:
    buy_threshold: float = 0.75
    sell_threshold: float = -0.75
    max_position_fraction: float = 0.20
    max_trade_fraction: float = 0.10
    min_cash_fraction: float = 0.10
    stop_loss_fraction: float = 0.08
    take_profit_fraction: float = 0.20
    news_half_life_hours: float = 12.0

    def __post_init__(self) -> None:
        fractions = (
            self.max_position_fraction,
            self.max_trade_fraction,
            self.min_cash_fraction,
            self.stop_loss_fraction,
            self.take_profit_fraction,
        )
        if any(value < 0 or value > 1 for value in fractions):
            raise ValueError("risk fractions must be between 0 and 1")
        if self.news_half_life_hours <= 0:
            raise ValueError("news_half_life_hours must be positive")


class NewsMomentumStrategy:
    """Transparent headline scoring plus position-level exits."""

    def __init__(
        self,
        *,
        watchlist: Mapping[str, tuple[str, ...]] | None = None,
        risk: RiskConfig | None = None,
    ) -> None:
        self.watchlist = dict(watchlist or DEFAULT_WATCHLIST)
        self.risk = risk or RiskConfig()

    def evaluate(
        self,
        articles: Iterable[NewsArticle],
        quotes: Mapping[str, Quote],
        portfolio: PortfolioSnapshot,
        *,
        now: datetime | None = None,
    ) -> list[TradeIntent]:
        now = now or datetime.now(timezone.utc)
        scores: dict[str, float] = defaultdict(float)
        evidence: dict[str, list[str]] = defaultdict(list)

        for article in articles:
            text = f"{article.title} {article.summary}".lower()
            sentiment = self._sentiment(text)
            if sentiment == 0:
                continue
            age_hours = max(0.0, (now - article.published_at).total_seconds() / 3600)
            weight = math.pow(0.5, age_hours / self.risk.news_half_life_hours)
            for symbol, aliases in self.watchlist.items():
                if self._mentions(text, symbol, aliases):
                    scores[symbol] += sentiment * weight
                    evidence[symbol].append(article.title)

        intents: list[TradeIntent] = []
        for symbol, position in portfolio.positions.items():
            quote = quotes.get(symbol)
            if not quote:
                continue
            return_fraction = quote.price / position.average_cost - 1
            if return_fraction <= -self.risk.stop_loss_fraction:
                intents.append(
                    TradeIntent(symbol, Side.SELL, -10.0, f"stop loss ({return_fraction:.1%})")
                )
            elif return_fraction >= self.risk.take_profit_fraction:
                intents.append(
                    TradeIntent(symbol, Side.SELL, -9.0, f"take profit ({return_fraction:.1%})")
                )

        exiting = {intent.symbol for intent in intents}
        for symbol, score in scores.items():
            if symbol not in quotes or symbol in exiting:
                continue
            headline = evidence[symbol][0][:100]
            if score >= self.risk.buy_threshold:
                intents.append(
                    TradeIntent(symbol, Side.BUY, score, f"positive news score {score:.2f}: {headline}")
                )
            elif score <= self.risk.sell_threshold and symbol in portfolio.positions:
                intents.append(
                    TradeIntent(symbol, Side.SELL, score, f"negative news score {score:.2f}: {headline}")
                )

        return sorted(intents, key=lambda intent: (intent.side != Side.SELL, -abs(intent.score)))

    @staticmethod
    def _sentiment(text: str) -> float:
        score = 0.0
        for term, weight in POSITIVE_TERMS.items():
            if term in text:
                score += weight
        for term, weight in NEGATIVE_TERMS.items():
            if term in text:
                score += weight
        return score

    @staticmethod
    def _mentions(text: str, symbol: str, aliases: tuple[str, ...]) -> bool:
        terms = (*aliases, f"${symbol.lower()}")
        return any(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text) for term in terms)

