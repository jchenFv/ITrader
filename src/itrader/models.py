from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True, slots=True)
class NewsArticle:
    title: str
    summary: str = ""
    source: str = "unknown"
    url: str = ""
    published_at: datetime = datetime.min.replace(tzinfo=timezone.utc)

    @property
    def article_id(self) -> str:
        raw = f"{self.source}|{self.url}|{self.title}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:20]


@dataclass(frozen=True, slots=True)
class Quote:
    symbol: str
    price: float
    as_of: datetime


@dataclass(slots=True)
class Position:
    symbol: str
    quantity: int
    average_cost: float

    def market_value(self, price: float) -> float:
        return self.quantity * price


@dataclass(frozen=True, slots=True)
class Trade:
    timestamp: datetime
    symbol: str
    side: Side
    quantity: int
    requested_price: float
    fill_price: float
    commission: float
    reason: str

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["timestamp"] = self.timestamp.isoformat()
        payload["side"] = self.side.value
        return payload


@dataclass(frozen=True, slots=True)
class TradeIntent:
    symbol: str
    side: Side
    score: float
    reason: str


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    cash: float
    positions_value: float
    equity: float
    positions: dict[str, Position]

