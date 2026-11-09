"""MT5 bridge for the logged-in Windows terminal.

Orders are demo-only, require a stop, and are capped by MT5_MAX_VOLUME.
"""

import json
import os
from math import floor
from datetime import datetime, time, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import MetaTrader5 as mt5
from dotenv import load_dotenv

load_dotenv()

HOST = os.getenv("MT5_BIND_HOST", "127.0.0.1")
PORT = int(os.getenv("MT5_BRIDGE_PORT", "8765"))
TOKEN = os.getenv("MT5_BRIDGE_TOKEN", "").strip()
SYMBOLS = [item.strip().upper() for item in os.getenv("MT5_SYMBOLS", "EURUSD").split(",") if item.strip()]
MAX_VOLUME = float(os.getenv("MT5_MAX_VOLUME", "0.01"))
NEWS_BLOCKS = {item.strip().upper() for item in os.getenv("MT5_NEWS_BLOCKS", "").split(",") if item.strip()}


def spread_limits():
    limits = {"*": float(os.getenv("MT5_MAX_SPREAD", "0.002"))}
    raw = os.getenv("MT5_MAX_SPREADS", "")
    for item in raw.split(","):
        if not item.strip() or ":" not in item:
            continue
        symbol, value = item.split(":", 1)
        try:
            limits[symbol.strip().upper()] = float(value)
        except ValueError:
            continue
    return limits


def payload(ok, **data):
    body = {"ok": ok}
    body.update(data)
    return body


def account_view():
    info = mt5.account_info()
    if info is None:
        return payload(False, error=str(mt5.last_error()))
    if "demo" not in info.server.lower():
        return payload(False, error="Refusing order bridge because this is not a demo server.")
    return payload(
        True,
        login=info.login,
        server=info.server,
        currency=info.currency,
        balance=info.balance,
        equity=info.equity,
        margin=info.margin,
        margin_free=info.margin_free,
        profit=info.profit,
    )


def daily_drawdown_view(account):
    """Return today's New York-session P/L and whether new entries are locked."""
    timezone_name = os.getenv("MT5_DAILY_DRAWDOWN_TIMEZONE", "America/New_York").strip()
    try:
        local_timezone = ZoneInfo(timezone_name)
    except Exception:
        local_timezone = timezone.utc
    now = datetime.now(local_timezone)
    start_local = datetime.combine(now.date(), time.min, tzinfo=local_timezone)
    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = now.astimezone(timezone.utc).replace(tzinfo=None)
    realized = 0.0
    deals = mt5.history_deals_get(start_utc, end_utc)
    if deals:
        for deal in deals:
            if deal.entry == mt5.DEAL_ENTRY_OUT:
                realized += float(deal.profit) + float(deal.commission) + float(deal.swap)
    start_balance = float(account["balance"]) - realized
    current_pnl = realized + float(account["profit"])
    drawdown_percent = (
        max(0.0, -current_pnl / start_balance * 100)
        if start_balance > 0
        else 0.0
    )
    limit_percent = max(
        0.0, float(os.getenv("MT5_MAX_DAILY_DRAWDOWN_PERCENT", "2.8"))
    )
    return {
        "timezone": timezone_name,
        "start": start_local.isoformat(),
        "realized_profit": round(realized, 2),
        "floating_profit": round(float(account["profit"]), 2),
        "daily_profit": round(current_pnl, 2),
        "drawdown_percent": round(drawdown_percent, 3),
        "limit_percent": limit_percent,
        "trading_locked": limit_percent > 0 and drawdown_percent >= limit_percent,
    }


def tick_for(symbol):
    info = mt5.symbol_info(symbol)
    if info is None or not info.visible:
        mt5.symbol_select(symbol, True)
    return mt5.symbol_info(symbol), mt5.symbol_info_tick(symbol)


def average(symbol):
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, 30)
    if rates is None or len(rates) < 30:
        return None, None
    closes = [float(bar["close"]) for bar in rates]
    return sum(closes[-8:]) / 8, sum(closes) / len(closes)


def price_view(symbol):
    info, tick = tick_for(symbol)
    if info is None or tick is None:
        return payload(False, error=str(mt5.last_error()), symbol=symbol)
    fast, slow = average(symbol)
    point = info.point or 0.0001
    distance = point * 150
    return payload(
        True,
        symbol=symbol,
        bid=tick.bid,
        ask=tick.ask,
        digits=info.digits,
        time=tick.time,
        fast=fast,
        slow=slow,
        stop_buy=round(tick.ask - distance, info.digits),
        stop_sell=round(tick.bid + distance, info.digits),
    )



def research_view(symbol):
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 1, 240)
    if rates is None or len(rates) < 80:
        return payload(False, error="Not enough history.", symbol=symbol)
    closes = [float(bar["close"]) for bar in rates]
    returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
    split = 180
    training = returns[:split]
    testing = returns[split:]
    threshold = sorted(abs(value) for value in training)[int(len(training) * 0.7)]
    correct = 0
    acted = 0
    for index, move in enumerate(testing, start=split):
        signal = closes[index] - closes[index - 8]
        if abs(signal) / closes[index] < threshold:
            continue
        acted += 1
        predicted = 1 if signal > 0 else -1
        actual = 1 if move > 0 else -1
        correct += predicted == actual
    accuracy = correct / acted if acted else 0
    return payload(True, symbol=symbol, samples=len(testing), acted=acted, accuracy=round(accuracy, 3), threshold=threshold)


def candles_view(symbol, count):
    count = max(32, min(int(count), 512))
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 1, count)
    if rates is None or len(rates) < 32:
        return payload(False, error="Not enough M5 candle history.", symbol=symbol)
    candles = [
        {
            "time": int(bar["time"]),
            "open": float(bar["open"]),
            "high": float(bar["high"]),
            "low": float(bar["low"]),
            "close": float(bar["close"]),
            "volume": float(bar["tick_volume"]),
        }
        for bar in rates
    ]
    return payload(True, symbol=symbol, timeframe="M5", candles=candles)



def risk_view():
    account = account_view()
    if not account["ok"]:
        return account
    positions = positions_view()
    if not positions["ok"]:
        return positions
    max_positions = int(os.getenv("MT5_MAX_POSITIONS", "3"))
    max_daily_loss = float(os.getenv("MT5_MAX_DAILY_LOSS", "10"))
    max_spreads = spread_limits()
    daily_drawdown = daily_drawdown_view(account)
    return payload(
        True,
        open_positions=positions["count"],
        max_positions=max_positions,
        daily_profit=account["profit"],
        max_daily_loss=max_daily_loss,
        daily_drawdown=daily_drawdown,
        trading_locked=daily_drawdown["trading_locked"],
        max_spread=max_spreads["*"],
        max_spreads={key: value for key, value in max_spreads.items() if key != "*"},
    )


def performance_view():
    from datetime import datetime, timedelta

    end = datetime.now()
    window_days = max(1, int(os.getenv("MT5_PERFORMANCE_WINDOW_DAYS", "7")))
    min_trades = max(1, int(os.getenv("MT5_PERFORMANCE_MIN_TRADES", "5")))
    loss_threshold = max(1, int(os.getenv("MT5_PERFORMANCE_LOSS_THRESHOLD", "3")))
    cooldown_hours = max(0.0, float(os.getenv("MT5_PERFORMANCE_COOLDOWN_HOURS", "12")))
    start = end - timedelta(days=window_days)
    deals = mt5.history_deals_get(start, end)
    totals = {}
    if deals:
        for deal in deals:
            if deal.entry != mt5.DEAL_ENTRY_OUT:
                continue
            item = totals.setdefault(
                deal.symbol,
                {
                    "wins": 0,
                    "losses": 0,
                    "trades": 0,
                    "profit": 0.0,
                    "latest_loss": None,
                },
            )
            item["trades"] += 1
            item["profit"] += float(deal.profit)
            if deal.profit >= 0:
                item["wins"] += 1
            else:
                item["losses"] += 1
                item["latest_loss"] = max(item["latest_loss"] or 0, int(deal.time))

    cooldown_seconds = cooldown_hours * 3600
    for item in totals.values():
        in_loss_cooldown = (
            item["trades"] >= min_trades
            and item["losses"] >= loss_threshold
            and item["profit"] < 0
            and item["latest_loss"] is not None
            and (end.timestamp() - item["latest_loss"]) < cooldown_seconds
        )
        item["disabled"] = in_loss_cooldown
        if in_loss_cooldown:
            item["cooldown_remaining_hours"] = round(
                max(0.0, cooldown_seconds - (end.timestamp() - item["latest_loss"])) / 3600,
                2,
            )
        item.pop("latest_loss", None)
    return payload(True, symbols=totals)


def history_view(days):
    end = datetime.now()
    start = end - timedelta(days=max(1, min(int(days), 365)))
    configured_magic = os.getenv("MT5_TRADE_HISTORY_MAGIC", "260615").strip()
    magic = int(configured_magic) if configured_magic else None
    deals = mt5.history_deals_get(start, end)
    trades = []
    if deals:
        for deal in deals:
            if deal.entry != mt5.DEAL_ENTRY_OUT:
                continue
            if magic is not None and deal.magic != magic:
                continue
            trades.append(
                {
                    "exit_deal": int(deal.ticket),
                    "position_id": int(deal.position_id),
                    "closed_at": datetime.fromtimestamp(int(deal.time)).isoformat(),
                    "symbol": deal.symbol,
                    # A sell exit closes a buy position, and vice versa.
                    "side": "buy" if deal.type == mt5.DEAL_TYPE_SELL else "sell",
                    "volume": float(deal.volume),
                    "profit": float(deal.profit),
                    "commission": float(deal.commission),
                    "swap": float(deal.swap),
                    "net_profit": round(
                        float(deal.profit)
                        + float(deal.commission)
                        + float(deal.swap),
                        8,
                    ),
                    "magic": int(deal.magic),
                }
            )
    return payload(True, trades=trades)


def watch_view():
    prices = []
    errors = []
    for symbol in SYMBOLS:
        body = price_view(symbol)
        if body["ok"]:
            prices.append(body)
        else:
            errors.append({"symbol": symbol, "error": body["error"]})
    return payload(True, prices=prices, errors=errors)


def positions_view():
    rows = mt5.positions_get()
    if rows is None:
        return payload(False, error=str(mt5.last_error()))
    positions = [
        {
            "ticket": row.ticket,
            "symbol": row.symbol,
            "type": "buy" if row.type == mt5.POSITION_TYPE_BUY else "sell",
            "volume": row.volume,
            "price_open": row.price_open,
            "price_current": row.price_current,
            "profit": row.profit,
        }
        for row in rows
    ]
    return payload(True, count=len(positions), positions=positions)


def normalize_volume(symbol, volume):
    info = mt5.symbol_info(symbol)
    if info is None:
        return None, "Symbol is not available."
    ceiling = max(info.volume_min, min(info.volume_max, MAX_VOLUME))
    if volume < info.volume_min or volume > ceiling:
        return None, f"Volume must be between {info.volume_min} and {ceiling}."
    steps = round((volume - info.volume_min) / info.volume_step)
    normalized = round(info.volume_min + steps * info.volume_step, 8)
    if abs(normalized - volume) > info.volume_step / 10:
        return None, f"Volume does not match the {info.volume_step} lot step."
    return normalized, ""


def volume_for_risk(symbol, side, price, stop, risk_percent, equity):
    """Calculate a broker-valid volume whose stop loss risks no more than the target."""
    if risk_percent <= 0:
        return None, "Risk percent must be greater than zero."
    info = mt5.symbol_info(symbol)
    if info is None:
        return None, "Symbol is not available."
    trade_type = mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL
    one_lot_loss = mt5.order_calc_profit(
        trade_type, symbol, 1.0, price, stop
    )
    if one_lot_loss is None or one_lot_loss >= 0:
        return None, f"Could not calculate stop-loss risk: {mt5.last_error()}."
    target_loss = equity * risk_percent / 100
    raw_volume = target_loss / abs(one_lot_loss)
    ceiling = max(info.volume_min, min(info.volume_max, MAX_VOLUME))
    raw_volume = min(raw_volume, ceiling)
    if raw_volume < info.volume_min:
        return None, (
            f"Risk target {target_loss:.2f} is below the minimum-volume "
            f"risk for {symbol}."
        )
    steps = floor((raw_volume - info.volume_min) / info.volume_step)
    volume = round(info.volume_min + steps * info.volume_step, 8)
    return normalize_volume(symbol, volume)


def order_view(data):
    account = account_view()
    if not account["ok"]:
        return account
    daily_drawdown = daily_drawdown_view(account)
    if daily_drawdown["trading_locked"]:
        return payload(
            False,
            error=(
                "New trades are locked for the current New York day: "
                f"daily drawdown {daily_drawdown['drawdown_percent']:.3f}% "
                f"reached the {daily_drawdown['limit_percent']:.3f}% limit."
            ),
            daily_drawdown=daily_drawdown,
        )
    if str(data.get("confirmation", "")).upper() != "DEMO":
        return payload(False, error="Confirmation must be DEMO.")
    side = str(data.get("side", "")).lower()
    symbol = str(data.get("symbol", "")).upper()
    if side not in {"buy", "sell"} or symbol not in SYMBOLS:
        return payload(False, error="Order must use buy or sell and a watched symbol.")
    try:
        stop = float(data.get("stop"))
    except (TypeError, ValueError):
        return payload(False, error="Stop must be a number.")
    info, tick = tick_for(symbol)
    if info is None or tick is None:
        return payload(False, error=str(mt5.last_error()))
    price = tick.ask if side == "buy" else tick.bid
    if side == "buy" and stop >= price:
        return payload(False, error="Buy stop must be below the ask.")
    if side == "sell" and stop <= price:
        return payload(False, error="Sell stop must be above the bid.")
    risk_percent = data.get("risk_percent")
    if risk_percent is not None:
        try:
            volume, error = volume_for_risk(
                symbol, side, price, stop, float(risk_percent), account["equity"]
            )
        except (TypeError, ValueError):
            return payload(False, error="Risk percent must be a number.")
    else:
        try:
            volume = float(data.get("volume"))
        except (TypeError, ValueError):
            return payload(False, error="Volume must be a number.")
        volume, error = normalize_volume(symbol, volume)
    if error:
        return payload(False, error=error)
    trade_type = mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": trade_type,
        "price": price,
        "sl": round(stop, info.digits),
        "deviation": 20,
        "magic": 260615,
        "comment": "grok demo",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        message = "order rejected" if result is None else result.comment
        return payload(False, error=message, detail=str(mt5.last_error()))
    return payload(True, ticket=result.order, side=side, symbol=symbol, volume=volume, price=result.price, stop=request["sl"])



def modify_view(data):
    if str(data.get("confirmation", "")).upper() != "DEMO":
        return payload(False, error="Confirmation must be DEMO.")
    try:
        ticket = int(data.get("ticket"))
        stop = float(data.get("stop"))
    except (TypeError, ValueError):
        return payload(False, error="Ticket and stop must be numbers.")
    rows = mt5.positions_get(ticket=ticket)
    if not rows:
        return payload(False, error="Position was not found.")
    position = rows[0]
    info = mt5.symbol_info(position.symbol)
    if info is None:
        return payload(False, error="Symbol information was not available.")
    tick = mt5.symbol_info_tick(position.symbol)
    if tick is None:
        return payload(False, error="Current price was not available.")
    stops_level = getattr(info, "trade_stops_level", 0) * info.point
    if position.type == mt5.POSITION_TYPE_BUY:
        if stop >= tick.bid:
            return payload(False, error="Buy stop must be below the current bid.")
        if stops_level and tick.bid - stop < stops_level:
            return payload(False, error=f"Buy stop is inside the broker minimum distance ({stops_level}).")
    else:
        if stop <= tick.ask:
            return payload(False, error="Sell stop must be above the current ask.")
        if stops_level and stop - tick.ask < stops_level:
            return payload(False, error=f"Sell stop is inside the broker minimum distance ({stops_level}).")
    request = {"action": mt5.TRADE_ACTION_SLTP, "position": ticket, "symbol": position.symbol, "sl": round(stop, info.digits), "tp": position.tp}
    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        if result is None:
            return payload(False, error="stop update rejected", detail=str(mt5.last_error()))
        return payload(
            False,
            error=f"stop update rejected: {result.comment}",
            retcode=result.retcode,
            detail=str(mt5.last_error()),
        )
    return payload(True, ticket=ticket, stop=request["sl"])


def close_view(data):
    account = account_view()
    if not account["ok"]:
        return account
    if str(data.get("confirmation", "")).upper() != "DEMO":
        return payload(False, error="Confirmation must be DEMO.")
    try:
        ticket = int(data.get("ticket"))
    except (TypeError, ValueError):
        return payload(False, error="Ticket must be a number.")
    rows = mt5.positions_get(ticket=ticket)
    if not rows:
        return payload(False, error="Position was not found.")
    position = rows[0]
    info, tick = tick_for(position.symbol)
    if info is None or tick is None:
        return payload(False, error=str(mt5.last_error()))
    closing_buy = position.type == mt5.POSITION_TYPE_BUY
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "position": ticket,
        "symbol": position.symbol,
        "volume": position.volume,
        "type": mt5.ORDER_TYPE_SELL if closing_buy else mt5.ORDER_TYPE_BUY,
        "price": tick.bid if closing_buy else tick.ask,
        "deviation": 20,
        "magic": 260615,
        "comment": "grok demo close",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        message = "close rejected" if result is None else result.comment
        return payload(False, error=message)
    return payload(True, ticket=ticket)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))

    def send_json(self, code, body):
        raw = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def authorized(self):
        return bool(TOKEN) and self.headers.get("X-Bridge-Token", "") == TOKEN

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 10000:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        if not self.authorized():
            self.send_json(401, payload(False, error="unauthorized"))
            return
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        symbol = query.get("symbol", [SYMBOLS[0]])[0].upper()
        try:
            count = int(query.get("count", [400])[0])
        except ValueError:
            count = 400
        try:
            history_days = int(query.get("days", [90])[0])
        except ValueError:
            history_days = 90
        routes = {
            "/health": lambda: payload(True, terminal=mt5.terminal_info() is not None),
            "/account": account_view,
            "/watch": watch_view,
            "/research": lambda: research_view(symbol),
            "/candles": lambda: candles_view(symbol, count),
            "/price": lambda: price_view(symbol),
            "/positions": positions_view,
            "/risk": risk_view,
            "/performance": performance_view,
            "/history": lambda: history_view(history_days),
            "/news": lambda: payload(True, blocks=sorted(NEWS_BLOCKS)),
        }
        if path not in routes:
            self.send_json(404, payload(False, error="not found"))
            return
        body = routes[path]()
        self.send_json(200 if body["ok"] else 503, body)

    def do_POST(self):
        if not self.authorized():
            self.send_json(401, payload(False, error="unauthorized"))
            return
        try:
            data = self.read_json()
        except (json.JSONDecodeError, UnicodeError):
            self.send_json(400, payload(False, error="Invalid JSON."))
            return
        path = self.path.split("?", 1)[0]
        if path == "/order":
            body = order_view(data)
        elif path == "/modify":
            body = modify_view(data)
        elif path == "/close":
            body = close_view(data)
        else:
            body = payload(False, error="not found")
        self.send_json(200 if body["ok"] else 400, body)


def main():
    if not TOKEN:
        raise SystemExit("Set MT5_BRIDGE_TOKEN before starting the bridge.")
    if not mt5.initialize():
        raise SystemExit(f"MT5 initialize failed: {mt5.last_error()}")
    for symbol in SYMBOLS:
        mt5.symbol_select(symbol, True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"MT5 bridge listening on {HOST}:{PORT}; watching {', '.join(SYMBOLS)}")
    try:
        server.serve_forever()
    finally:
        server.server_close()
        mt5.shutdown()


if __name__ == "__main__":
    main()
