"""Deterministic demo decision shared by the swarm.

This is intentionally small: moving-average trend, fixed risk limits, and
manual news blocks. It does not promise profitability.
"""

import journal
import mt5_client


def decide(row, positions, blocks):
    symbol = row["symbol"]
    if any(block in symbol for block in blocks):
        return "hold", f"{symbol}: news block is active."
    if any(item["symbol"] == symbol for item in positions):
        return "hold", f"{symbol}: a position is already open."
    fast = row.get("fast")
    slow = row.get("slow")
    if fast is None or slow is None or fast == slow:
        return "hold", f"{symbol}: trend is not clear."
    evidence = mt5_client.research(symbol)
    journal.record("research", "learn", f"accuracy {evidence['accuracy']} over {evidence['acted']} signals", symbol)
    if evidence["acted"] < 10 or evidence["accuracy"] < 0.55:
        return "hold", f"{symbol}: research accuracy {evidence['accuracy']} is below 0.55."
    side = "buy" if fast > slow else "sell"
    stop = row["stop_buy"] if side == "buy" else row["stop_sell"]
    return side, f"{symbol}: {side}; fast {fast:.5f}, slow {slow:.5f}, stop {stop}."


def run_cycle():
    rows = mt5_client.watch_rows()
    positions = mt5_client.positions_rows()
    blocks = mt5_client.news_blocks()
    decisions = []
    for row in rows:
        side, reason = decide(row, positions, blocks)
        journal.record("coordinator", side, reason, row["symbol"])
        if side == "hold":
            decisions.append(reason)
            continue
        stop = row["stop_buy"] if side == "buy" else row["stop_sell"]
        try:
            result = mt5_client.order_text(side, row["symbol"], 0.01, stop, "DEMO")
        except mt5_client.BridgeError as exc:
            result = f"{row['symbol']}: order rejected: {exc}"
        journal.record("execution", side, result, row["symbol"])
        decisions.append(result)
    return "\n".join(decisions) or "No symbols are being watched."