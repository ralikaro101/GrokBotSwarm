import os
import unittest
from unittest.mock import patch

import strategy


class EntryDirectionTests(unittest.TestCase):
    def setUp(self):
        os.environ["SWARM_KRONOS_REQUIRED"] = "off"
        self.row = {
            "symbol": "EURUSD",
            "bid": 1.1,
            "ask": 1.1001,
            "fast": 1.09,
            "slow": 1.10,
            "ema_touch": True,
            "macd_direction": "buy",
            "stop_buy": 1.08,
            "stop_sell": 1.12,
        }
        self.limits = {
            "max_positions": 3,
            "daily_profit": 0,
            "max_daily_loss": 100,
            "max_spread": 1,
            "max_spreads": {},
        }

    def test_ema_sell_is_blocked_when_macd_is_bullish(self):
        with patch.object(
            strategy.mt5_client, "research", return_value={"accuracy": 0.8, "acted": 20}
        ), patch.object(strategy.journal, "record"):
            side, reason = strategy.decide(
                self.row, [], [], self.limits, {}, {}, None, None
            )

        self.assertEqual(side, "hold")
        self.assertIn("MACD direction buy disagrees", reason)

    def test_ema_sell_requires_bearish_macd(self):
        self.row["macd_direction"] = "sell"
        with patch.object(
            strategy.mt5_client, "research", return_value={"accuracy": 0.8, "acted": 20}
        ), patch.object(strategy.journal, "record"):
            side, _ = strategy.decide(
                self.row, [], [], self.limits, {}, {}, None, None
            )

        self.assertEqual(side, "sell")


if __name__ == "__main__":
    unittest.main()
