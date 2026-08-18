import json
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from itrader.broker import SimulatedBroker
from itrader.llm_strategy import (
    FallbackStrategy,
    LLMResearchStrategy,
    OpenAIResponsesResearchClient,
    ResearchError,
    ResearchRequest,
    build_strategy,
)
from itrader.models import (
    IndustryAnalysis,
    NewsArticle,
    Quote,
    ResearchReport,
    ResearchSource,
    Side,
    StockRecommendation,
)
from itrader.strategy import NewsMomentumStrategy


NOW = datetime(2026, 8, 18, tzinfo=timezone.utc)


def recommendation(
    symbol: str,
    action: str,
    confidence: float,
    thesis: str = "Improving industry economics support future cash flow.",
) -> StockRecommendation:
    return StockRecommendation(
        symbol=symbol,
        action=action,
        confidence=confidence,
        horizon="weeks",
        industry="semiconductors",
        thesis=thesis,
        evidence=("Verified capacity and demand evidence",),
        risks=("Valuation compression",),
        source_urls=("https://example.com/source",),
    )


def report(*items: StockRecommendation) -> ResearchReport:
    return ResearchReport(
        generated_at=NOW,
        model="test-model",
        market_summary="AI infrastructure demand remains selective.",
        industry_views=(
            IndustryAnalysis(
                industry="semiconductors",
                outlook="bullish",
                score=0.6,
                thesis="Supply and demand are improving.",
                catalysts=("New product cycle",),
                risks=("Export controls",),
                sources=(
                    ResearchSource(
                        "Primary source", "https://example.com/source", "2026-08-18"
                    ),
                ),
            ),
        ),
        recommendations=tuple(items),
    )


class FakeResearchClient:
    model = "test-model"

    def __init__(self, result: ResearchReport | Exception) -> None:
        self.result = result
        self.requests: list[ResearchRequest] = []

    def research(self, request: ResearchRequest) -> ResearchReport:
        self.requests.append(request)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class LLMResearchStrategyTests(unittest.TestCase):
    def test_llm_industry_research_creates_bounded_candidate_intent(self) -> None:
        client = FakeResearchClient(report(recommendation("NVDA", "BUY", 0.84)))
        strategy = LLMResearchStrategy(
            client, watchlist={"NVDA": ("nvidia",)}, confidence_threshold=0.70
        )
        quote = Quote("NVDA", 120, NOW)
        portfolio = SimulatedBroker(10_000).snapshot({"NVDA": 120})

        intents = strategy.evaluate([], {"NVDA": quote}, portfolio, now=NOW)

        self.assertEqual(len(intents), 1)
        self.assertEqual(intents[0].side, Side.BUY)
        self.assertIn("LLM BUY 84%", intents[0].reason)
        self.assertEqual(client.requests[0].watchlist, ("NVDA",))
        self.assertIs(strategy.last_research, client.result)

    def test_low_confidence_hold_and_unquoted_symbols_do_not_trade(self) -> None:
        client = FakeResearchClient(
            report(
                recommendation("NVDA", "BUY", 0.50),
                recommendation("AAPL", "HOLD", 0.95),
                recommendation("MSFT", "BUY", 0.95),
            )
        )
        strategy = LLMResearchStrategy(
            client,
            watchlist={
                "NVDA": ("nvidia",),
                "AAPL": ("apple",),
                "MSFT": ("microsoft",),
            },
        )
        quotes = {
            "NVDA": Quote("NVDA", 120, NOW),
            "AAPL": Quote("AAPL", 200, NOW),
        }
        portfolio = SimulatedBroker(10_000).snapshot({})
        self.assertEqual(strategy.evaluate([], quotes, portfolio, now=NOW), [])

    def test_local_stop_loss_overrides_llm_buy(self) -> None:
        broker = SimulatedBroker(10_000, slippage_bps=0)
        broker.submit_market_order("NVDA", Side.BUY, 10, 100, reason="seed")
        client = FakeResearchClient(report(recommendation("NVDA", "BUY", 0.99)))
        strategy = LLMResearchStrategy(client, watchlist={"NVDA": ("nvidia",)})
        quote = Quote("NVDA", 90, NOW)

        intents = strategy.evaluate(
            [], {"NVDA": quote}, broker.snapshot({"NVDA": 90}), now=NOW
        )

        self.assertEqual(len(intents), 1)
        self.assertEqual(intents[0].side, Side.SELL)
        self.assertIn("stop loss", intents[0].reason)

    def test_duplicate_symbol_recommendations_cannot_create_multiple_orders(self) -> None:
        client = FakeResearchClient(
            report(
                recommendation("NVDA", "BUY", 0.90),
                recommendation("NVDA", "BUY", 0.95),
            )
        )
        strategy = LLMResearchStrategy(client, watchlist={"NVDA": ("nvidia",)})
        quote = Quote("NVDA", 100, NOW)
        portfolio = SimulatedBroker(10_000).snapshot({})

        intents = strategy.evaluate([], {"NVDA": quote}, portfolio, now=NOW)

        self.assertEqual(len(intents), 1)

    def test_hybrid_falls_back_to_rules_when_llm_fails(self) -> None:
        primary = LLMResearchStrategy(
            FakeResearchClient(ResearchError("temporary failure")),
            watchlist={"NVDA": ("nvidia",)},
        )
        fallback = NewsMomentumStrategy(watchlist={"NVDA": ("nvidia",)})
        strategy = FallbackStrategy(primary, fallback)
        article = NewsArticle(
            "Nvidia beats estimates with record growth", published_at=NOW
        )
        quote = Quote("NVDA", 100, NOW)
        portfolio = SimulatedBroker(10_000).snapshot({})

        intents = strategy.evaluate([article], {"NVDA": quote}, portfolio, now=NOW)

        self.assertEqual(intents[0].side, Side.BUY)
        self.assertEqual(strategy.last_error, "temporary failure")


class OpenAIResponsesResearchClientTests(unittest.TestCase):
    def test_request_uses_web_search_and_strict_structured_output(self) -> None:
        captured: dict[str, object] = {}
        result = {
            "market_summary": "Selective demand.",
            "industry_views": [],
            "recommendations": [],
        }

        def transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
            captured.update(
                url=url,
                headers=headers,
                payload=json.loads(body),
                timeout=timeout,
            )
            return json.dumps(
                {
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {"type": "output_text", "text": json.dumps(result)}
                            ],
                        }
                    ]
                }
            ).encode()

        client = OpenAIResponsesResearchClient(
            "secret-test-key", model="test-model", transport=transport
        )
        portfolio = SimulatedBroker(10_000).snapshot({})
        research = client.research(
            ResearchRequest(
                now=NOW,
                watchlist=("NVDA",),
                quotes={"NVDA": Quote("NVDA", 100, NOW)},
                portfolio=portfolio,
                seed_articles=(),
            )
        )

        payload = captured["payload"]
        self.assertEqual(payload["tools"], [{"type": "web_search", "search_context_size": "medium"}])
        self.assertEqual(payload["tool_choice"], "required")
        self.assertEqual(payload["include"], ["web_search_call.action.sources"])
        self.assertTrue(payload["text"]["format"]["strict"])
        self.assertEqual(payload["text"]["format"]["type"], "json_schema")
        self.assertNotIn("secret-test-key", json.dumps(payload))
        self.assertEqual(research.market_summary, "Selective demand.")

    def test_strategy_factory_requires_key_only_in_strict_llm_mode(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            automatic = build_strategy("auto")
            self.assertTrue(automatic.name.startswith("rules"))
            with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY"):
                build_strategy("llm")


if __name__ == "__main__":
    unittest.main()
