"""Read-only MT5 bridge.

Run this on the Windows machine where the IC Markets terminal is logged in.
It never sends orders.
"""

import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json

import MetaTrader5 as mt5
from dotenv import load_dotenv

load_dotenv()

HOST = os.getenv("MT5_BIND_HOST", "127.0.0.1")
PORT = int(os.getenv("MT5_BRIDGE_PORT", "8765"))
TOKEN = os.getenv("MT5_BRIDGE_TOKEN", "").strip()
SYMBOL = os.getenv("MT5_SYMBOL", "EURUSD")


def payload(ok, **data):
    body = {"ok": ok}
    body.update(data)
    return body


def account_view():
    info = mt5.account_info()
    if info is None:
        return payload(False, error=mt5.last_error())
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


def price_view(symbol):
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        mt5.symbol_select(symbol, True)
        tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return payload(False, error=mt5.last_error(), symbol=symbol)
    return payload(True, symbol=symbol, bid=tick.bid, ask=tick.ask, time=tick.time)


def positions_view():
    rows = mt5.positions_get()
    if rows is None:
        return payload(False, error=mt5.last_error())
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

    def do_GET(self):
        if not self.authorized():
            self.send_json(401, payload(False, error="unauthorized"))
            return
        path = self.path.split("?", 1)[0]
        if path == "/health":
            self.send_json(200, payload(True, terminal=mt5.terminal_info() is not None))
            return
        if path == "/account":
            body = account_view()
            self.send_json(200 if body["ok"] else 503, body)
            return
        if path == "/price":
            symbol = SYMBOL
            if "?" in self.path and "symbol=" in self.path:
                symbol = self.path.split("symbol=", 1)[1].split("&", 1)[0].upper()
            body = price_view(symbol)
            self.send_json(200 if body["ok"] else 404, body)
            return
        if path == "/positions":
            body = positions_view()
            self.send_json(200 if body["ok"] else 503, body)
            return
        self.send_json(404, payload(False, error="not found"))


def main():
    if not TOKEN:
        raise SystemExit("Set MT5_BRIDGE_TOKEN before starting the bridge.")
    if not mt5.initialize():
        raise SystemExit(f"MT5 initialize failed: {mt5.last_error()}")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"MT5 bridge listening on {HOST}:{PORT}")
    try:
        server.serve_forever()
    finally:
        server.server_close()
        mt5.shutdown()


if __name__ == "__main__":
    main()
