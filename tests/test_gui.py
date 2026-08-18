import unittest

from itrader.broker import SimulatedBroker
from itrader.gui import build_position_rows
from itrader.models import Side


class DashboardViewModelTests(unittest.TestCase):
    def test_position_rows_calculate_unrealized_performance(self) -> None:
        broker = SimulatedBroker(10_000, slippage_bps=0)
        broker.submit_market_order("NVDA", Side.BUY, 10, 100, reason="seed")
        rows = build_position_rows(broker, {"NVDA": 125})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].market_value, 1_250)
        self.assertEqual(rows[0].unrealized_pnl, 250)
        self.assertEqual(rows[0].unrealized_percent, 0.25)

    def test_position_rows_fall_back_to_cost_when_quote_is_absent(self) -> None:
        broker = SimulatedBroker(10_000, slippage_bps=0)
        broker.submit_market_order("NVDA", Side.BUY, 10, 100, reason="seed")
        row = build_position_rows(broker, {})[0]
        self.assertEqual(row.last_price, 100)
        self.assertEqual(row.unrealized_pnl, 0)


if __name__ == "__main__":
    unittest.main()
