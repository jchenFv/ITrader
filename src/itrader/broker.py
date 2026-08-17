from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping

from .models import PortfolioSnapshot, Position, Side, Trade


class OrderRejected(ValueError):
    """Raised when the simulated broker cannot fill an order."""


class SimulatedBroker:
    """Long-only market-order simulator with commission and slippage."""

    def __init__(
        self,
        initial_cash: float,
        *,
        commission: float = 0.0,
        slippage_bps: float = 2.0,
    ) -> None:
        if initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        if commission < 0 or slippage_bps < 0:
            raise ValueError("commission and slippage_bps cannot be negative")
        self.initial_cash = round(float(initial_cash), 2)
        self.cash = self.initial_cash
        self.commission = float(commission)
        self.slippage_bps = float(slippage_bps)
        self.positions: dict[str, Position] = {}
        self.trades: list[Trade] = []

    def submit_market_order(
        self,
        symbol: str,
        side: Side,
        quantity: int,
        market_price: float,
        *,
        reason: str,
        timestamp: datetime | None = None,
    ) -> Trade:
        symbol = symbol.upper()
        if quantity <= 0:
            raise OrderRejected("quantity must be a positive whole number")
        if market_price <= 0:
            raise OrderRejected("market_price must be positive")

        slip = self.slippage_bps / 10_000
        fill_price = market_price * (1 + slip if side == Side.BUY else 1 - slip)
        fill_price = round(fill_price, 4)

        if side == Side.BUY:
            total = fill_price * quantity + self.commission
            if total > self.cash + 1e-9:
                raise OrderRejected(f"insufficient cash: need {total:.2f}, have {self.cash:.2f}")
            old = self.positions.get(symbol)
            old_qty = old.quantity if old else 0
            old_cost = old.average_cost if old else 0.0
            new_qty = old_qty + quantity
            average_cost = ((old_qty * old_cost) + (quantity * fill_price)) / new_qty
            self.positions[symbol] = Position(symbol, new_qty, round(average_cost, 4))
            self.cash -= total
        elif side == Side.SELL:
            position = self.positions.get(symbol)
            if position is None or position.quantity < quantity:
                available = position.quantity if position else 0
                raise OrderRejected(f"insufficient shares: need {quantity}, have {available}")
            self.cash += fill_price * quantity - self.commission
            remaining = position.quantity - quantity
            if remaining:
                position.quantity = remaining
            else:
                del self.positions[symbol]
        else:
            raise OrderRejected(f"unsupported side: {side}")

        self.cash = round(self.cash, 4)
        trade = Trade(
            timestamp=timestamp or datetime.now(timezone.utc),
            symbol=symbol,
            side=side,
            quantity=quantity,
            requested_price=round(market_price, 4),
            fill_price=fill_price,
            commission=self.commission,
            reason=reason,
        )
        self.trades.append(trade)
        return trade

    def snapshot(self, prices: Mapping[str, float]) -> PortfolioSnapshot:
        positions_value = sum(
            position.market_value(prices.get(symbol, position.average_cost))
            for symbol, position in self.positions.items()
        )
        return PortfolioSnapshot(
            cash=round(self.cash, 2),
            positions_value=round(positions_value, 2),
            equity=round(self.cash + positions_value, 2),
            positions={
                symbol: Position(p.symbol, p.quantity, p.average_cost)
                for symbol, p in self.positions.items()
            },
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "initial_cash": self.initial_cash,
            "cash": self.cash,
            "commission": self.commission,
            "slippage_bps": self.slippage_bps,
            "positions": {
                symbol: {
                    "symbol": p.symbol,
                    "quantity": p.quantity,
                    "average_cost": p.average_cost,
                }
                for symbol, p in self.positions.items()
            },
            "trades": [trade.to_dict() for trade in self.trades],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "SimulatedBroker":
        broker = cls(
            float(payload["initial_cash"]),
            commission=float(payload.get("commission", 0.0)),
            slippage_bps=float(payload.get("slippage_bps", 2.0)),
        )
        broker.cash = float(payload["cash"])
        broker.positions = {
            symbol: Position(
                symbol=str(item["symbol"]),
                quantity=int(item["quantity"]),
                average_cost=float(item["average_cost"]),
            )
            for symbol, item in dict(payload.get("positions", {})).items()
        }
        broker.trades = [
            Trade(
                timestamp=datetime.fromisoformat(str(item["timestamp"])),
                symbol=str(item["symbol"]),
                side=Side(str(item["side"])),
                quantity=int(item["quantity"]),
                requested_price=float(item["requested_price"]),
                fill_price=float(item["fill_price"]),
                commission=float(item["commission"]),
                reason=str(item["reason"]),
            )
            for item in list(payload.get("trades", []))
        ]
        return broker

