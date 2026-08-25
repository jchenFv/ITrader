from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import queue
import re
import threading
import tkinter as tk
from tkinter import messagebox, ttk
import webbrowser

from .agent import CycleReport, TradingAgent
from .broker import SimulatedBroker
from .llm_strategy import DEFAULT_API_BASE, DEFAULT_LLM_MODEL, build_strategy
from .models import Side, Trade
from .providers import BestEffortNewsProvider, GoogleNewsRssProvider, YahooFinanceMarketData


BG = "#08111f"
PANEL = "#111d2e"
PANEL_ALT = "#152338"
BORDER = "#26364d"
TEXT = "#e7eef8"
MUTED = "#8fa2ba"
ACCENT = "#49a8ff"
GREEN = "#35d07f"
RED = "#ff6577"
AMBER = "#f5b942"


@dataclass(frozen=True, slots=True)
class PositionRow:
    symbol: str
    quantity: int
    average_cost: float
    last_price: float
    market_value: float
    unrealized_pnl: float
    unrealized_percent: float


def build_position_rows(
    broker: SimulatedBroker, prices: dict[str, float]
) -> list[PositionRow]:
    rows: list[PositionRow] = []
    for symbol, position in sorted(broker.positions.items()):
        last_price = prices.get(symbol, position.average_cost)
        market_value = last_price * position.quantity
        unrealized_pnl = (last_price - position.average_cost) * position.quantity
        unrealized_percent = last_price / position.average_cost - 1
        rows.append(
            PositionRow(
                symbol=symbol,
                quantity=position.quantity,
                average_cost=position.average_cost,
                last_price=last_price,
                market_value=market_value,
                unrealized_pnl=unrealized_pnl,
                unrealized_percent=unrealized_percent,
            )
        )
    return rows


def _money(value: float, *, signed: bool = False) -> str:
    sign = "+" if signed and value > 0 else ""
    return f"{sign}${value:,.2f}"


def _percent(value: float) -> str:
    return f"{value:+.2%}"


def _short_time(value: datetime) -> str:
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def create_live_agent(
    *,
    initial_cash: float,
    state_path: Path,
    news_query: str,
    strategy_mode: str = "auto",
    llm_model: str = DEFAULT_LLM_MODEL,
    llm_confidence: float = 0.70,
    api_base: str = DEFAULT_API_BASE,
) -> TradingAgent:
    strategy = build_strategy(
        strategy_mode,
        model=llm_model,
        api_base=api_base,
        confidence_threshold=llm_confidence,
    )
    rss = GoogleNewsRssProvider(query=news_query)
    news = BestEffortNewsProvider(rss) if getattr(strategy, "uses_web_research", False) else rss
    market = YahooFinanceMarketData()
    if state_path.exists():
        return TradingAgent.load(
            state_path,
            news_provider=news,
            market_data=market,
            strategy=strategy,
        )
    agent = TradingAgent(
        broker=SimulatedBroker(initial_cash),
        news_provider=news,
        market_data=market,
        strategy=strategy,
        state_path=state_path,
    )
    agent.save_state()
    return agent


class TradingDashboard(tk.Tk):
    def __init__(self, agent: TradingAgent, *, interval_seconds: int = 300) -> None:
        super().__init__()
        self.agent = agent
        self.interval_seconds = max(5, interval_seconds)
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.auto_after_id: str | None = None

        self.title("ITrader · Paper Trading Dashboard")
        self.geometry("1240x820")
        self.minsize(980, 680)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.cash_var = tk.StringVar()
        self.holdings_var = tk.StringVar()
        self.equity_var = tk.StringVar()
        self.pnl_var = tk.StringVar()
        self.status_var = tk.StringVar(value="就绪 · 等待运行模拟周期")
        self.news_var = tk.StringVar(value="本次会话尚未运行")
        self.strategy_var = tk.StringVar(value=f"策略 · {self.agent.strategy.name}")
        self.auto_var = tk.BooleanVar(value=False)

        self._configure_styles()
        self._build_layout()
        self._refresh_account()
        self.after(150, self._drain_events)

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "Treeview",
            background=PANEL,
            fieldbackground=PANEL,
            foreground=TEXT,
            rowheight=30,
            borderwidth=0,
            font=("Segoe UI", 10),
        )
        style.map("Treeview", background=[("selected", "#214469")])
        style.configure(
            "Treeview.Heading",
            background=PANEL_ALT,
            foreground=MUTED,
            relief="flat",
            borderwidth=0,
            font=("Segoe UI Semibold", 9),
        )
        style.map("Treeview.Heading", background=[("active", "#1d304a")])
        style.configure(
            "Primary.TButton",
            background=ACCENT,
            foreground="#04101d",
            padding=(18, 10),
            borderwidth=0,
            font=("Segoe UI Semibold", 10),
        )
        style.map(
            "Primary.TButton",
            background=[("active", "#72bbff"), ("disabled", "#31506d")],
            foreground=[("disabled", MUTED)],
        )
        style.configure(
            "TCheckbutton",
            background=BG,
            foreground=TEXT,
            font=("Segoe UI", 10),
        )
        style.map("TCheckbutton", background=[("active", BG)])
        style.configure(
            "Secondary.TButton",
            background=PANEL_ALT,
            foreground=TEXT,
            padding=(12, 9),
            borderwidth=0,
            font=("Segoe UI", 9),
        )
        style.map("Secondary.TButton", background=[("active", "#214469")])

    def _build_layout(self) -> None:
        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True, padx=24, pady=20)

        header = tk.Frame(outer, bg=BG)
        header.pack(fill="x", pady=(0, 18))
        title_box = tk.Frame(header, bg=BG)
        title_box.pack(side="left")
        tk.Label(
            title_box,
            text="ITRADER",
            bg=BG,
            fg=TEXT,
            font=("Segoe UI Semibold", 22),
        ).pack(anchor="w")
        tk.Label(
            title_box,
            text="新闻驱动的美股模拟交易",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 9),
        ).pack(anchor="w")

        controls = tk.Frame(header, bg=BG)
        controls.pack(side="right")
        paper_badge = tk.Label(
            controls,
            text="●  纯模拟",
            bg="#173426",
            fg=GREEN,
            padx=12,
            pady=8,
            font=("Segoe UI Semibold", 9),
        )
        paper_badge.pack(side="left", padx=(0, 14))
        tk.Label(
            controls,
            textvariable=self.strategy_var,
            bg=PANEL_ALT,
            fg=ACCENT,
            padx=10,
            pady=8,
            font=("Segoe UI", 9),
        ).pack(side="left", padx=(0, 10))
        self.research_button = ttk.Button(
            controls,
            text="查看 LLM 研究",
            style="Secondary.TButton",
            command=self._show_research,
        )
        self.research_button.pack(side="left", padx=(0, 10))
        ttk.Checkbutton(
            controls,
            text=f"自动 {self.interval_seconds} 秒",
            variable=self.auto_var,
            command=self._toggle_auto,
        ).pack(side="left", padx=(0, 14))
        self.run_button = ttk.Button(
            controls,
            text="运行一轮模拟",
            style="Primary.TButton",
            command=self.run_cycle,
        )
        self.run_button.pack(side="left")

        cards = tk.Frame(outer, bg=BG)
        cards.pack(fill="x", pady=(0, 18))
        for index in range(4):
            cards.grid_columnconfigure(index, weight=1, uniform="card")
        self._card(cards, 0, "可用现金", self.cash_var, ACCENT)
        self._card(cards, 1, "持仓市值", self.holdings_var, TEXT)
        self._card(cards, 2, "账户权益", self.equity_var, TEXT)
        self.pnl_value_label = self._card(cards, 3, "累计盈亏", self.pnl_var, GREEN)

        holdings_panel = self._panel(outer, "当前持仓", "按照最近一次保存的行情计价")
        holdings_panel.pack(fill="both", expand=True, pady=(0, 16))
        self.positions_tree = self._positions_table(holdings_panel)

        trades_panel = self._panel(outer, "历史成交", "最新成交优先")
        trades_panel.pack(fill="both", expand=True)
        self.trades_tree = self._trades_table(trades_panel)

        footer = tk.Frame(outer, bg=BG)
        footer.pack(fill="x", pady=(12, 0))
        self.status_dot = tk.Label(footer, text="●", bg=BG, fg=MUTED, font=("Segoe UI", 10))
        self.status_dot.pack(side="left")
        tk.Label(
            footer,
            textvariable=self.status_var,
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 9),
        ).pack(side="left", padx=(6, 0))
        tk.Label(
            footer,
            textvariable=self.news_var,
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 9),
        ).pack(side="right")

    def _card(
        self, parent: tk.Widget, column: int, label: str, variable: tk.StringVar, color: str
    ) -> tk.Label:
        frame = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        frame.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 6, 6))
        tk.Label(
            frame,
            text=label,
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI Semibold", 9),
        ).pack(anchor="w", padx=16, pady=(14, 5))
        value_label = tk.Label(
            frame,
            textvariable=variable,
            bg=PANEL,
            fg=color,
            font=("Segoe UI Semibold", 20),
        )
        value_label.pack(anchor="w", padx=16, pady=(0, 15))
        return value_label

    @staticmethod
    def _panel(parent: tk.Widget, title: str, subtitle: str) -> tk.Frame:
        frame = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        heading = tk.Frame(frame, bg=PANEL)
        heading.pack(fill="x", padx=16, pady=(12, 8))
        tk.Label(
            heading,
            text=title,
            bg=PANEL,
            fg=TEXT,
            font=("Segoe UI Semibold", 12),
        ).pack(side="left")
        tk.Label(
            heading,
            text=subtitle,
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 9),
        ).pack(side="right")
        return frame

    def _positions_table(self, parent: tk.Widget) -> ttk.Treeview:
        columns = ("symbol", "qty", "avg", "last", "value", "pnl", "percent")
        tree = ttk.Treeview(parent, columns=columns, show="headings", height=6)
        headings = {
            "symbol": "股票",
            "qty": "股数",
            "avg": "平均成本",
            "last": "最新价格",
            "value": "持仓市值",
            "pnl": "未实现盈亏",
            "percent": "收益率",
        }
        widths = {"symbol": 100, "qty": 90, "avg": 110, "last": 110, "value": 140, "pnl": 140, "percent": 100}
        for column in columns:
            tree.heading(column, text=headings[column])
            tree.column(column, width=widths[column], anchor="e" if column != "symbol" else "w")
        tree.tag_configure("profit", foreground=GREEN)
        tree.tag_configure("loss", foreground=RED)
        tree.pack(fill="both", expand=True, padx=1, pady=(0, 1))
        return tree

    def _trades_table(self, parent: tk.Widget) -> ttk.Treeview:
        columns = ("time", "side", "symbol", "qty", "price", "commission", "reason")
        tree = ttk.Treeview(parent, columns=columns, show="headings", height=7)
        headings = {
            "time": "时间",
            "side": "方向",
            "symbol": "股票",
            "qty": "股数",
            "price": "成交价",
            "commission": "费用",
            "reason": "决策原因",
        }
        widths = {"time": 155, "side": 70, "symbol": 80, "qty": 75, "price": 100, "commission": 75, "reason": 500}
        for column in columns:
            tree.heading(column, text=headings[column])
            anchor = "w" if column in ("time", "side", "symbol", "reason") else "e"
            tree.column(column, width=widths[column], anchor=anchor, stretch=column == "reason")
        tree.tag_configure("buy", foreground=GREEN)
        tree.tag_configure("sell", foreground=RED)
        tree.pack(fill="both", expand=True, padx=1, pady=(0, 1))
        return tree

    def _refresh_account(self) -> None:
        prices = self.agent.last_prices
        snapshot = self.agent.broker.snapshot(prices)
        pnl = snapshot.equity - self.agent.broker.initial_cash
        self.cash_var.set(_money(snapshot.cash))
        self.holdings_var.set(_money(snapshot.positions_value))
        self.equity_var.set(_money(snapshot.equity))
        self.pnl_var.set(_money(pnl, signed=True))
        self.pnl_value_label.configure(fg=GREEN if pnl >= 0 else RED)
        self.strategy_var.set(f"策略 · {self.agent.strategy.name}")
        self.research_button.configure(
            state="normal" if self.agent.last_research else "disabled"
        )

        self.positions_tree.delete(*self.positions_tree.get_children())
        rows = build_position_rows(self.agent.broker, prices)
        for row in rows:
            tag = "profit" if row.unrealized_pnl >= 0 else "loss"
            self.positions_tree.insert(
                "",
                "end",
                values=(
                    row.symbol,
                    f"{row.quantity:,}",
                    _money(row.average_cost),
                    _money(row.last_price),
                    _money(row.market_value),
                    _money(row.unrealized_pnl, signed=True),
                    _percent(row.unrealized_percent),
                ),
                tags=(tag,),
            )
        if not rows:
            self.positions_tree.insert("", "end", values=("暂无持仓", "", "", "", "", "", ""))

        self.trades_tree.delete(*self.trades_tree.get_children())
        for trade in reversed(self.agent.broker.trades):
            self._insert_trade(trade)
        if not self.agent.broker.trades:
            self.trades_tree.insert("", "end", values=("暂无成交", "", "", "", "", "", ""))

    def _insert_trade(self, trade: Trade) -> None:
        tag = "buy" if trade.side == Side.BUY else "sell"
        self.trades_tree.insert(
            "",
            "end",
            values=(
                _short_time(trade.timestamp),
                trade.side.value,
                trade.symbol,
                f"{trade.quantity:,}",
                _money(trade.fill_price),
                _money(trade.commission),
                trade.reason,
            ),
            tags=(tag,),
        )

    def _show_research(self) -> None:
        report = self.agent.last_research
        if report is None:
            messagebox.showinfo("LLM 行业研究", "尚无 LLM 研究报告。", parent=self)
            return
        dialog = tk.Toplevel(self)
        dialog.title("ITrader · LLM 行业研究")
        dialog.geometry("900x700")
        dialog.minsize(680, 480)
        dialog.configure(bg=BG)
        text = tk.Text(
            dialog,
            bg=PANEL,
            fg=TEXT,
            insertbackground=TEXT,
            selectbackground="#214469",
            relief="flat",
            wrap="word",
            padx=20,
            pady=18,
            font=("Segoe UI", 10),
        )
        scrollbar = ttk.Scrollbar(dialog, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True, padx=16, pady=16)
        rendered = report.render_text()
        text.insert("1.0", rendered)
        text.tag_configure("research_url", foreground=ACCENT, underline=True)
        for match in re.finditer(r"https?://[^\s]+", rendered):
            start = f"1.0+{match.start()}c"
            end = f"1.0+{match.end()}c"
            text.tag_add("research_url", start, end)
            url = match.group(0)
            tag_name = f"url_{match.start()}"
            text.tag_add(tag_name, start, end)
            text.tag_bind(
                tag_name,
                "<Button-1>",
                lambda _event, target=url: webbrowser.open_new_tab(target),
            )
        text.configure(state="disabled")

    def run_cycle(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        self.run_button.configure(state="disabled", text="正在获取数据…")
        self.status_dot.configure(fg=AMBER)
        self.status_var.set("正在后台获取新闻和行情")
        self.worker = threading.Thread(target=self._cycle_worker, daemon=True)
        self.worker.start()

    def _cycle_worker(self) -> None:
        try:
            self.events.put(("report", self.agent.run_cycle()))
        except Exception as exc:
            self.events.put(("error", exc))

    def _drain_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "report":
                    self._cycle_finished(payload)  # type: ignore[arg-type]
                else:
                    self._cycle_failed(payload)  # type: ignore[arg-type]
        except queue.Empty:
            pass
        self.after(150, self._drain_events)

    def _cycle_finished(self, report: CycleReport) -> None:
        self._refresh_account()
        self.run_button.configure(state="normal", text="运行一轮模拟")
        self.status_dot.configure(fg=GREEN)
        self.status_var.set(
            f"更新于 {_short_time(report.timestamp)} · {len(report.trades)} 笔成交 · 权益 {_money(report.equity)}"
        )
        self.news_var.set(
            f"新闻 {report.new_articles}/{report.articles_seen} 条新增 · 行情 {report.quotes_received} 只 · {report.strategy_name}"
        )
        if report.rejected:
            self.status_var.set(self.status_var.get() + f" · 跳过 {len(report.rejected)} 个信号")
        if report.news_error:
            self.status_dot.configure(fg=AMBER)
            self.status_var.set(self.status_var.get() + " · RSS 新闻源失败，已继续运行")
            self.news_var.set(self.news_var.get() + f" · RSS 警告：{report.news_error}")
        if report.strategy_error:
            self.status_dot.configure(fg=AMBER)
            self.status_var.set(self.status_var.get() + " · LLM 失败，已使用规则回退")
        self._schedule_auto()

    def _cycle_failed(self, error: BaseException) -> None:
        self.run_button.configure(state="normal", text="运行一轮模拟")
        self.status_dot.configure(fg=RED)
        self.status_var.set(f"本轮失败 · {error}")
        self._schedule_auto()
        messagebox.showerror("ITrader 数据错误", str(error), parent=self)

    def _toggle_auto(self) -> None:
        if self.auto_var.get():
            self.status_var.set(f"自动模拟已开启 · 每 {self.interval_seconds} 秒运行")
            self.run_cycle()
        else:
            if self.auto_after_id:
                self.after_cancel(self.auto_after_id)
                self.auto_after_id = None
            self.status_var.set("自动模拟已关闭")

    def _schedule_auto(self) -> None:
        if self.auto_after_id:
            self.after_cancel(self.auto_after_id)
            self.auto_after_id = None
        if self.auto_var.get():
            self.auto_after_id = self.after(self.interval_seconds * 1000, self.run_cycle)

    def _on_close(self) -> None:
        if self.auto_after_id:
            self.after_cancel(self.auto_after_id)
        self.destroy()


def launch_gui(
    *,
    initial_cash: float = 100_000,
    state_path: Path = Path("var/paper-state.json"),
    interval_seconds: int = 300,
    news_query: str = "US technology stocks when:1d",
    strategy_mode: str = "auto",
    llm_model: str = DEFAULT_LLM_MODEL,
    llm_confidence: float = 0.70,
    api_base: str = DEFAULT_API_BASE,
) -> None:
    agent = create_live_agent(
        initial_cash=initial_cash,
        state_path=state_path,
        news_query=news_query,
        strategy_mode=strategy_mode,
        llm_model=llm_model,
        llm_confidence=llm_confidence,
        api_base=api_base,
    )
    app = TradingDashboard(agent, interval_seconds=interval_seconds)
    app.mainloop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ITrader paper-trading desktop dashboard")
    parser.add_argument("--initial-cash", type=float, default=100_000)
    parser.add_argument("--state", type=Path, default=Path("var/paper-state.json"))
    parser.add_argument("--interval", type=int, default=300)
    parser.add_argument("--news-query", default="US technology stocks when:1d")
    parser.add_argument("--strategy", choices=("auto", "llm", "rules"), default="auto")
    parser.add_argument(
        "--llm-model", default=os.getenv("ITRADER_LLM_MODEL", DEFAULT_LLM_MODEL)
    )
    parser.add_argument("--llm-confidence", type=float, default=0.70)
    parser.add_argument(
        "--openai-api-base", default=os.getenv("OPENAI_BASE_URL", DEFAULT_API_BASE)
    )
    args = parser.parse_args(argv)
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
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
