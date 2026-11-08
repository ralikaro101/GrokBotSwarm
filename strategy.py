"""Deterministic demo decision shared by the swarm.

This is intentionally small: moving-average trend, fixed risk limits, and
manual news blocks. It does not promise profitability.
"""

import os
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import journal
import kronos_research
import mt5_client


def weekend_close_active(now=None):
    """Return whether the configured Friday weekend cutoff has been reached."""
    timezone_name = os.getenv("SWARM_WEEKEND_TIMEZONE", "UTC").strip() or "UTC"
    try:
        local_timezone = ZoneInfo(timezone_name)
    except Exception:
        local_timezone = timezone.utc
    current = now or datetime.now(local_timezone)
    if current.tzinfo is None:
        current = current.replace(tzinfo=local_timezone)
    else:
        current = current.astimezone(local_timezone)
    try:
        cutoff = time(
            hour=int(os.getenv("SWARM_WEEKEND_CLOSE_FRIDAY_HOUR", "20")),
            minute=int(os.getenv("SWARM_WEEKEND_CLOSE_FRIDAY_MINUTE", "0")),
        )
    except ValueError:
        cutoff = time(20, 0)
    return current.weekday() == 4 and current.time() >= cutoff or current.weekday() in {5, 6}


def manage_positions(rows):
    actions = []
    by_symbol = {row["symbol"]: row for row in rows}
    for position in mt5_client.positions_rows():
        if weekend_close_active():
            try:
                result = mt5_client.close_text(position["ticket"], "DEMO")
            except mt5_client.BridgeError as exc:
                result = f"{position['symbol']}: weekend close failed: {exc}"
            journal.record("trade-manager", "weekend-close", result, position["symbol"])
            actions.append(result)
            continue
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
            try:
                result = mt5_client.modify_stop(position["ticket"], entry)
            except mt5_client.BridgeError as exc:
                result = (
                    f"{position['symbol']}: break-even stop not moved: {exc}"
                )
            journal.record("trade-manager", "break-even", result, position["symbol"])
            actions.append(result)
    return actions


def order_volume(symbol):
    default = float(os.getenv("SWARM_ORDER_VOLUME", "0.01"))
    for item in os.getenv("SWARM_ORDER_VOLUMES", "").split(","):
        if ":" not in item:
            continue
        name, value = item.split(":", 1)
        if name.strip().upper() != symbol.upper():
            continue
        try:
            return float(value)
        except ValueError:
            break
    return default


def order_risk_percent():
    try:
        return max(0.0, float(os.getenv("SWARM_RISK_PERCENT", "0")))
    except ValueError:
        return 0.0


def decide(row, positions, blocks, limits, performance, kronos_direction=None):
    symbol = row["symbol"]
    if weekend_close_active():
        return "hold", f"{symbol}: weekend trading cutoff is active."
    if any(block in symbol for block in blocks):
        return "hold", f"{symbol}: news block is active."
    if any(item["symbol"] == symbol for item in positions):
        return "hold", f"{symbol}: a position is already open."
    if len(positions) >= limits["max_positions"]:
        return "hold", f"{symbol}: position cap {limits['max_positions']} is reached."
    if limits["daily_profit"] <= -limits["max_daily_loss"]:
        return "hold", f"{symbol}: daily loss limit is reached."
    if limits.get("trading_locked", False):
        drawdown = limits.get("daily_drawdown", {})
        return "hold", (
            f"{symbol}: New York daily drawdown lock is active "
            f"({drawdown.get('drawdown_percent', '?')}%)."
        )
    spread = row["ask"] - row["bid"]
    max_spread = limits.get("max_spreads", {}).get(
        symbol, limits["max_spread"]
    )
    if spread > max_spread:
        return "hold", (
            f"{symbol}: spread {spread:.5f} exceeds limit {max_spread:.5f}."
        )
    stats = performance.get(symbol, {})
    if stats.get("disabled", False):
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
    if kronos_research.mode() == "gate":
        if kronos_direction is None:
            return "hold", f"{symbol}: Kronos forecast unavailable; trade blocked."
        if kronos_direction != side:
            return (
                "hold",
                f"{symbol}: Kronos forecast {kronos_direction} disagrees with "
                f"strategy {side}.",
            )
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
        kronos_direction = None
        if kronos_research.enabled():
            try:
                forecast = kronos_research.forecast(row["symbol"])
                kronos_direction = forecast["direction"]
                journal.record(
                    "kronos",
                    forecast["direction"],
                    (
                        f"M5 close {forecast['last_close']:.5f} -> "
                        f"{forecast['predicted_close']:.5f} "
                        f"({forecast['change']:+.5f}); mode={kronos_research.mode()}."
                    ),
                    row["symbol"],
                )
                decisions.append(
                    f"{row['symbol']}: Kronos {kronos_research.mode()} forecast "
                    f"{forecast['direction']}."
                )
            except Exception as exc:
                message = f"{row['symbol']}: Kronos unavailable: {exc}"
                journal.record("kronos", "unavailable", message, row["symbol"])
                decisions.append(message)
        side, reason = decide(
            row, positions, blocks, limits, performance, kronos_direction
        )
        journal.record("coordinator", side, reason, row["symbol"])
        if side == "hold":
            decisions.append(reason)
            continue
        stop = row["stop_buy"] if side == "buy" else row["stop_sell"]
        try:
            risk_percent = order_risk_percent()
            result = mt5_client.order_text(
                side,
                row["symbol"],
                None if risk_percent else order_volume(row["symbol"]),
                stop,
                "DEMO",
                risk_percent=risk_percent or None,
            )
        except mt5_client.BridgeError as exc:
            result = f"{row['symbol']}: order rejected: {exc}"
        journal.record("execution", side, result, row["symbol"])
        decisions.append(result)
    return "\n".join(decisions) or "No symbols are being watched."
