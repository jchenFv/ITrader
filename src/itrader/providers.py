from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
from typing import Protocol, Sequence
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from .models import NewsArticle, Quote


DEFAULT_USER_AGENT = "ITrader/0.1 (+local paper-trading research)"


class ProviderError(RuntimeError):
    pass


class NewsProvider(Protocol):
    def fetch(self) -> list[NewsArticle]: ...


class MarketDataProvider(Protocol):
    def get_quotes(self, symbols: Sequence[str]) -> dict[str, Quote]: ...


class BestEffortNewsProvider:
    """Return no seed headlines when RSS fails so web-research strategies can continue."""

    def __init__(self, provider: NewsProvider) -> None:
        self.provider = provider
        self.last_error: str | None = None

    def fetch(self) -> list[NewsArticle]:
        try:
            articles = self.provider.fetch()
            self.last_error = None
            return articles
        except ProviderError as exc:
            self.last_error = str(exc)
            return []


def _get(url: str, timeout: float) -> bytes:
    request = Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read()
    except Exception as exc:  # urllib raises several transport-specific exceptions
        raise ProviderError(f"request failed for {url}: {exc}") from exc


class GoogleNewsRssProvider:
    """Fetch recent headlines through Google News' public RSS search feed."""

    def __init__(
        self,
        query: str = "US technology stocks when:1d",
        *,
        limit: int = 50,
        timeout: float = 10.0,
    ) -> None:
        self.query = query
        self.limit = limit
        self.timeout = timeout

    def fetch(self) -> list[NewsArticle]:
        url = (
            "https://news.google.com/rss/search?q="
            f"{quote_plus(self.query)}&hl=en-US&gl=US&ceid=US:en"
        )
        try:
            root = ET.fromstring(_get(url, self.timeout))
        except ET.ParseError as exc:
            raise ProviderError(f"invalid news RSS response: {exc}") from exc

        articles: list[NewsArticle] = []
        for item in root.findall("./channel/item")[: self.limit]:
            title = (item.findtext("title") or "").strip()
            source = (item.findtext("source") or "Google News").strip()
            published_text = item.findtext("pubDate") or ""
            try:
                published_at = parsedate_to_datetime(published_text)
            except (TypeError, ValueError):
                published_at = datetime.now(timezone.utc)
            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=timezone.utc)
            if title:
                articles.append(
                    NewsArticle(
                        title=title,
                        source=source,
                        url=(item.findtext("link") or "").strip(),
                        published_at=published_at,
                    )
                )
        return articles


class YahooFinanceMarketData:
    """Read delayed/real-time quote metadata from Yahoo Finance chart responses."""

    def __init__(self, *, timeout: float = 10.0) -> None:
        self.timeout = timeout

    def get_quotes(self, symbols: Sequence[str]) -> dict[str, Quote]:
        quotes: dict[str, Quote] = {}
        failures: list[str] = []
        for raw_symbol in symbols:
            symbol = raw_symbol.upper()
            url = (
                "https://query1.finance.yahoo.com/v8/finance/chart/"
                f"{quote_plus(symbol)}?interval=1m&range=1d"
            )
            try:
                payload = json.loads(_get(url, self.timeout))
                result = payload["chart"]["result"][0]
                meta = result["meta"]
                price = meta.get("regularMarketPrice")
                if price is None:
                    closes = result["indicators"]["quote"][0]["close"]
                    price = next(value for value in reversed(closes) if value is not None)
                timestamp = meta.get("regularMarketTime")
                as_of = (
                    datetime.fromtimestamp(timestamp, tz=timezone.utc)
                    if timestamp
                    else datetime.now(timezone.utc)
                )
                quotes[symbol] = Quote(symbol, float(price), as_of)
            except Exception as exc:
                failures.append(f"{symbol}: {exc}")
        if not quotes:
            raise ProviderError("all quote requests failed: " + "; ".join(failures))
        return quotes


class StaticNewsProvider:
    def __init__(self, articles: Sequence[NewsArticle]) -> None:
        self.articles = list(articles)

    def fetch(self) -> list[NewsArticle]:
        return list(self.articles)


class StaticMarketDataProvider:
    def __init__(self, prices: dict[str, float]) -> None:
        self.prices = {symbol.upper(): price for symbol, price in prices.items()}

    def get_quotes(self, symbols: Sequence[str]) -> dict[str, Quote]:
        now = datetime.now(timezone.utc)
        return {
            symbol.upper(): Quote(symbol.upper(), self.prices[symbol.upper()], now)
            for symbol in symbols
            if symbol.upper() in self.prices
        }
