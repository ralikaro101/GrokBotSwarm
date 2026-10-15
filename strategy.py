"""Deterministic demo decision shared by the swarm.

This is intentionally small: moving-average trend, fixed risk limits, and
manual news blocks. It does not promise profitability.
"""

import journal
import mt5_client


def manage_positions(rows):
    actions = []
    by_symbol = {row["symbol"]: row for row in rows}
    for position in mt5_client.positions_rows():
        row = by_symbol.get(position["symbol"])
        if row is None:
            continue
        fast, slow = row.get("fast"), row.get("slow")
        if fast is None or slow is None:
            continue
        reversed_buy = position["type"] == "buy" and fast < slow
        reversed_sell = position["type"] == "sell" and fast > slow
        if reversed_buy or reversed_sell:
            result = mt5_client.close_text(position["ticket"], "DEMO")
            journal.record("trade-manager", "close", result, position["symbol"])
            actions.append(result)
            continue
        entry = position["price_open"]
        current = position["price_current"]
        profitable = (position["type"] == "buy" and current > entry) or (position["type"] == "sell" and current < entry)
        if profitable:
            result = mt5_client.modify_stop(position["ticket"], entry)
            journal.record("trade-manager", "break-even", result, position["symbol"])
            actions.append(result)
    return actions


def decide(row, positions, blocks, limits, performance):
    symbol = row["symbol"]
    if any(block in symbol for block in blocks):
        return "hold", f"{symbol}: news block is active."
    if any(item["symbol"] == symbol for item in positions):
        return "hold", f"{symbol}: a position is already open."
    if len(positions) >= limits["max_positions"]:
        return "hold", f"{symbol}: position cap {limits['max_positions']} is reached."
    if limits["daily_profit"] <= -limits["max_daily_loss"]:
        return "hold", f"{symbol}: daily loss limit is reached."
    spread = row["ask"] - row["bid"]
    if spread > limits["max_spread"]:
        return "hold", f"{symbol}: spread {spread:.5f} is too wide."
    stats = performance.get(symbol, {})
    if stats.get("losses", 0) >= 3 and stats.get("profit", 0) < 0:
        return "hold", f"{symbol}: performance agent disabled it after losses."
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
    limits = mt5_client.risk()
    performance = mt5_client.performance()
    decisions = manage_positions(rows)
    positions = mt5_client.positions_rows()
    for row in rows:
        side, reason = decide(row, positions, blocks, limits, performance)
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