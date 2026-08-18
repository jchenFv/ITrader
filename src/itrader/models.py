from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
from typing import Any


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


@dataclass(frozen=True, slots=True)
class ResearchSource:
    title: str
    url: str
    published_at: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ResearchSource":
        return cls(
            title=str(payload.get("title", "")),
            url=str(payload.get("url", "")),
            published_at=str(payload.get("published_at", "")),
        )


@dataclass(frozen=True, slots=True)
class IndustryAnalysis:
    industry: str
    outlook: str
    score: float
    thesis: str
    catalysts: tuple[str, ...]
    risks: tuple[str, ...]
    sources: tuple[ResearchSource, ...]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "IndustryAnalysis":
        return cls(
            industry=str(payload.get("industry", "")),
            outlook=str(payload.get("outlook", "neutral")),
            score=float(payload.get("score", 0.0)),
            thesis=str(payload.get("thesis", "")),
            catalysts=tuple(str(item) for item in payload.get("catalysts", [])),
            risks=tuple(str(item) for item in payload.get("risks", [])),
            sources=tuple(
                ResearchSource.from_dict(item) for item in payload.get("sources", [])
            ),
        )


@dataclass(frozen=True, slots=True)
class StockRecommendation:
    symbol: str
    action: str
    confidence: float
    horizon: str
    industry: str
    thesis: str
    evidence: tuple[str, ...]
    risks: tuple[str, ...]
    source_urls: tuple[str, ...]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StockRecommendation":
        return cls(
            symbol=str(payload.get("symbol", "")).upper(),
            action=str(payload.get("action", "HOLD")).upper(),
            confidence=float(payload.get("confidence", 0.0)),
            horizon=str(payload.get("horizon", "weeks")),
            industry=str(payload.get("industry", "")),
            thesis=str(payload.get("thesis", "")),
            evidence=tuple(str(item) for item in payload.get("evidence", [])),
            risks=tuple(str(item) for item in payload.get("risks", [])),
            source_urls=tuple(str(item) for item in payload.get("source_urls", [])),
        )


@dataclass(frozen=True, slots=True)
class ResearchReport:
    generated_at: datetime
    model: str
    market_summary: str
    industry_views: tuple[IndustryAnalysis, ...]
    recommendations: tuple[StockRecommendation, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "model": self.model,
            "market_summary": self.market_summary,
            "industry_views": [asdict(item) for item in self.industry_views],
            "recommendations": [asdict(item) for item in self.recommendations],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ResearchReport":
        return cls(
            generated_at=datetime.fromisoformat(str(payload["generated_at"])),
            model=str(payload.get("model", "unknown")),
            market_summary=str(payload.get("market_summary", "")),
            industry_views=tuple(
                IndustryAnalysis.from_dict(item)
                for item in payload.get("industry_views", [])
            ),
            recommendations=tuple(
                StockRecommendation.from_dict(item)
                for item in payload.get("recommendations", [])
            ),
        )

    def render_text(self) -> str:
        lines = [
            f"模型：{self.model}",
            f"生成时间：{self.generated_at.astimezone().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "市场摘要",
            self.market_summary,
        ]
        if self.industry_views:
            lines.extend(("", "行业观点"))
        for view in self.industry_views:
            lines.extend(
                (
                    "",
                    f"[{view.outlook.upper()} {view.score:+.2f}] {view.industry}",
                    view.thesis,
                    "催化剂：" + "；".join(view.catalysts),
                    "风险：" + "；".join(view.risks),
                )
            )
            for source in view.sources:
                lines.append(f"来源：{source.title} · {source.published_at}\n{source.url}")
        if self.recommendations:
            lines.extend(("", "股票建议"))
        for item in self.recommendations:
            lines.extend(
                (
                    "",
                    f"{item.action} {item.symbol} · 置信度 {item.confidence:.0%} · {item.horizon}",
                    f"行业：{item.industry}",
                    item.thesis,
                    "依据：" + "；".join(item.evidence),
                    "风险：" + "；".join(item.risks),
                )
            )
            lines.extend(f"来源：{url}" for url in item.source_urls)
        return "\n".join(lines)
