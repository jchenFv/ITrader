import unittest

from itrader.broker import OrderRejected, SimulatedBroker
from itrader.models import Side


class SimulatedBrokerTests(unittest.TestCase):
    def test_buy_and_sell_updates_cash_position_and_ledger(self) -> None:
        broker = SimulatedBroker(1_000, commission=1, slippage_bps=0)
        broker.submit_market_order("AAPL", Side.BUY, 5, 100, reason="test buy")
        self.assertEqual(broker.positions["AAPL"].quantity, 5)
        self.assertEqual(broker.cash, 499)

        broker.submit_market_order("AAPL", Side.SELL, 2, 110, reason="test sell")
        self.assertEqual(broker.positions["AAPL"].quantity, 3)
        self.assertEqual(broker.cash, 718)
        self.assertEqual(len(broker.trades), 2)

    def test_rejects_overspending_and_short_selling(self) -> None:
        broker = SimulatedBroker(100)
        with self.assertRaises(OrderRejected):
            broker.submit_market_order("AAPL", Side.BUY, 2, 100, reason="too large")
        with self.assertRaises(OrderRejected):
            broker.submit_market_order("AAPL", Side.SELL, 1, 100, reason="no shares")


if __name__ == "__main__":
    unittest.main()

