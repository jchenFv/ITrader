from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import logging
import os
from pathlib import Path
import time

from .agent import CycleReport, TradingAgent
from .broker import SimulatedBroker
from .models import NewsArticle
from .providers import (
    BestEffortNewsProvider,
    GoogleNewsRssProvider,
    ProviderError,
    StaticMarketDataProvider,
    StaticNewsProvider,
    YahooFinanceMarketData,
)
from .llm_strategy import (
    DEFAULT_API_BASE,
    DEFAULT_LLM_MODEL,
    ResearchError,
    build_strategy,
)
from .strategy import NewsMomentumStrategy


LOG = logging.getLogger("itrader")


def _add_strategy_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--strategy",
        choices=("auto", "llm", "rules"),
        default="auto",
        help="auto uses LLM when OPENAI_API_KEY is set; llm requires it",
    )
    parser.add_argument(
        "--llm-model",
        default=os.getenv("ITRADER_LLM_MODEL", DEFAULT_LLM_MODEL),
    )
    parser.add_argument(
        "--llm-confidence",
        type=float,
        default=0.70,
        help="minimum LLM confidence for a candidate trade",
    )
    parser.add_argument(
        "--openai-api-base",
        default=os.getenv("OPENAI_BASE_URL", DEFAULT_API_BASE),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="News-driven US tech paper-trading agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="use live public news and market data")
    run.add_argument("--initial-cash", type=float, default=100_000)
    run.add_argument("--state", type=Path, default=Path("var/paper-state.json"))
    run.add_argument("--interval", type=int, default=300, help="poll interval in seconds")
    run.add_argument("--once", action="store_true", help="run exactly one cycle")
    run.add_argument("--news-query", default="US technology stocks when:1d")
    _add_strategy_arguments(run)

    demo = subparsers.add_parser("demo", help="run a deterministic offline demonstration")
    demo.add_argument("--initial-cash", type=float, default=100_000)

    gui = subparsers.add_parser("gui", help="open the paper-trading desktop dashboard")
    gui.add_argument("--initial-cash", type=float, default=100_000)
    gui.add_argument("--state", type=Path, default=Path("var/paper-state.json"))
    gui.add_argument("--interval", type=int, default=300, help="auto-refresh interval in seconds")
    gui.add_argument("--news-query", default="US technology stocks when:1d")
    _add_strategy_arguments(gui)
    return parser


def _print_report(report: CycleReport) -> None:
    print(
        f"[{report.timestamp.isoformat()}] news={report.new_articles}/{report.articles_seen} "
        f"quotes={report.quotes_received} trades={len(report.trades)} "
        f"cash=${report.cash:,.2f} equity=${report.equity:,.2f} "
        f"strategy={report.strategy_name}"
    )
    for trade in report.trades:
        print(
            f"  {trade.side} {trade.quantity} {trade.symbol} @ ${trade.fill_price:,.2f} "
            f"| {trade.reason}"
        )
    for rejection in report.rejected:
        print(f"  SKIP {rejection}")
    if report.news_error:
        print(f"  NEWS WARNING {report.news_error}")
    if report.strategy_error:
        print(f"  FALLBACK {report.strategy_error}")
    if report.research:
        print(f"  RESEARCH {report.research.market_summary[:240]}")


def _live_agent(args: argparse.Namespace) -> TradingAgent:
    strategy = build_strategy(
        args.strategy,
        model=args.llm_model,
        api_base=args.openai_api_base,
        confidence_threshold=args.llm_confidence,
    )
    rss = GoogleNewsRssProvider(query=args.news_query)
    news = BestEffortNewsProvider(rss) if getattr(strategy, "uses_web_research", False) else rss
    market = YahooFinanceMarketData()
    if args.state.exists():
        return TradingAgent.load(
            args.state, news_provider=news, market_data=market, strategy=strategy
        )
    return TradingAgent(
        broker=SimulatedBroker(args.initial_cash),
        news_provider=news,
        market_data=market,
        strategy=strategy,
        state_path=args.state,
    )


def _run_live(args: argparse.Namespace) -> int:
    try:
        agent = _live_agent(args)
    except ValueError as exc:
        LOG.error("configuration error: %s", exc)
        return 2
    while True:
        try:
            _print_report(agent.run_cycle())
        except (ProviderError, ResearchError) as exc:
            LOG.error("data provider error: %s", exc)
            if args.once:
                return 2
        except KeyboardInterrupt:
            print("Stopped. Paper-trading state has been preserved.")
            return 0
        if args.once:
            return 0
        time.sleep(max(5, args.interval))


def _run_demo(args: argparse.Namespace) -> int:
    now = datetime.now(timezone.utc)
    article = NewsArticle(
        title="Nvidia beats expectations on record AI growth and raises guidance",
        source="ITrader demo feed",
        url="demo://nvidia-positive",
        published_at=now,
    )
    agent = TradingAgent(
        broker=SimulatedBroker(args.initial_cash),
        news_provider=StaticNewsProvider([article]),
        market_data=StaticMarketDataProvider({"NVDA": 100.0}),
        strategy=NewsMomentumStrategy(watchlist={"NVDA": ("nvidia",)}),
    )
    _print_report(agent.run_cycle(now=now))

    # A distinct later headline demonstrates the sell path without invoking stop loss.
    bad_news = NewsArticle(
        title="Nvidia plunges as weak demand forces company to cut guidance",
        source="ITrader demo feed",
        url="demo://nvidia-negative",
        published_at=now + timedelta(minutes=5),
    )
    agent.news_provider = StaticNewsProvider([bad_news])
    agent.market_data = StaticMarketDataProvider({"NVDA": 98.0})
    _print_report(agent.run_cycle(now=now + timedelta(minutes=5)))
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parser().parse_args(argv)
    if args.command == "demo":
        return _run_demo(args)
    if args.command == "gui":
        from .gui import launch_gui

        try:
            launch_gui(
                initial_cash=args.initial_cash,
                state_path=args.state,
                interval_seconds=args.interval,
                news_query=args.news_query,
                strategy_mode=args.strategy,
                llm_model=args.llm_model,
                llm_confidence=args.llm_confidence,
                api_base=args.openai_api_base,
            )
        except ValueError as exc:
            LOG.error("configuration error: %s", exc)
            return 2
        return 0
    return _run_live(args)


if __name__ == "__main__":
    raise SystemExit(main())
