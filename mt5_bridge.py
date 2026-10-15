"""MT5 bridge for the logged-in Windows terminal.

Orders are demo-only, require a stop, and are capped by MT5_MAX_VOLUME.
"""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import MetaTrader5 as mt5
from dotenv import load_dotenv

load_dotenv()

HOST = os.getenv("MT5_BIND_HOST", "127.0.0.1")
PORT = int(os.getenv("MT5_BRIDGE_PORT", "8765"))
TOKEN = os.getenv("MT5_BRIDGE_TOKEN", "").strip()
SYMBOLS = [item.strip().upper() for item in os.getenv("MT5_SYMBOLS", "EURUSD").split(",") if item.strip()]
MAX_VOLUME = float(os.getenv("MT5_MAX_VOLUME", "0.01"))
NEWS_BLOCKS = {item.strip().upper() for item in os.getenv("MT5_NEWS_BLOCKS", "").split(",") if item.strip()}


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
    if volume < info.volume_min or volume > min(info.volume_max, MAX_VOLUME):
        return None, f"Volume must be between {info.volume_min} and {min(info.volume_max, MAX_VOLUME)}."
    steps = round((volume - info.volume_min) / info.volume_step)
    normalized = round(info.volume_min + steps * info.volume_step, 8)
    if abs(normalized - volume) > info.volume_step / 10:
        return None, f"Volume does not match the {info.volume_step} lot step."
    return normalized, ""


def order_view(data):
    account = account_view()
    if not account["ok"]:
        return account
    if str(data.get("confirmation", "")).upper() != "DEMO":
        return payload(False, error="Confirmation must be DEMO.")
    side = str(data.get("side", "")).lower()
    symbol = str(data.get("symbol", "")).upper()
    if side not in {"buy", "sell"} or symbol not in SYMBOLS:
        return payload(False, error="Order must use buy or sell and a watched symbol.")
    try:
        volume = float(data.get("volume"))
        stop = float(data.get("stop"))
    except (TypeError, ValueError):
        return payload(False, error="Volume and stop must be numbers.")
    volume, error = normalize_volume(symbol, volume)
    if error:
        return payload(False, error=error)
    info, tick = tick_for(symbol)
    if info is None or tick is None:
        return payload(False, error=str(mt5.last_error()))
    price = tick.ask if side == "buy" else tick.bid
    if side == "buy" and stop >= price:
        return payload(False, error="Buy stop must be below the ask.")
    if side == "sell" and stop <= price:
        return payload(False, error="Sell stop must be above the bid.")
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
        path = self.path.split("?", 1)[0]
        symbol = SYMBOLS[0]
        if "symbol=" in self.path:
            symbol = self.path.split("symbol=", 1)[1].split("&", 1)[0].upper()
        routes = {
            "/health": lambda: payload(True, terminal=mt5.terminal_info() is not None),
            "/account": account_view,
            "/watch": watch_view,
            "/research": lambda: research_view(symbol),
            "/price": lambda: price_view(symbol),
            "/positions": positions_view,
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