"""HTTP client for the Windows MT5 bridge."""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import config


class BridgeError(RuntimeError):
    pass


def request_json(path, method="GET", data=None):
    if not config.MT5_BRIDGE_URL or not config.MT5_BRIDGE_TOKEN:
        raise BridgeError("MT5 bridge is not configured.")
    body = None if data is None else json.dumps(data).encode("utf-8")
    request = Request(
        config.MT5_BRIDGE_URL.rstrip("/") + path,
        data=body,
        method=method,
        headers={
            "X-Bridge-Token": config.MT5_BRIDGE_TOKEN,
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=8) as response:
            return json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise BridgeError(f"Bridge returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise BridgeError(f"Bridge is unreachable: {exc.reason}") from exc


def require_ok(body, fallback):
    if not body.get("ok"):
        raise BridgeError(str(body.get("error", fallback)))
    return body


def account_text():
    body = require_ok(request_json("/account"), "account request failed")
    return (
        f"Account {body['login']} on {body['server']}\n"
        f"Balance {body['balance']:.2f} {body['currency']}\n"
        f"Equity {body['equity']:.2f}\n"
        f"Free margin {body['margin_free']:.2f}\n"
        f"Open profit {body['profit']:.2f}"
    )


def watch_rows():
    return require_ok(request_json("/watch"), "watch request failed")["prices"]


def price_text(symbol):
    query = urlencode({"symbol": symbol.upper()})
    body = require_ok(request_json("/price?" + query), "price request failed")
    return f"{body['symbol']}: bid {body['bid']} ask {body['ask']}"


def watch_text():
    rows = watch_rows()
    if not rows:
        return "No symbols are being watched."
    return "\n".join(f"{row['symbol']}: bid {row['bid']} ask {row['ask']}" for row in rows)


def positions_rows():
    return require_ok(request_json("/positions"), "positions request failed")["positions"]


def positions_text():
    body = require_ok(request_json("/positions"), "positions request failed")
    rows = body["positions"]
    if not rows:
        return "No open positions."
    lines = [
        f"{row['ticket']} {row['symbol']} {row['type']} {row['volume']} "
        f"open {row['price_open']} now {row['price_current']} profit {row['profit']}"
        for row in rows[:20]
    ]
    return f"{body['count']} open position(s)\n" + "\n".join(lines)


def order_text(side, symbol, volume, stop, confirmation):
    body = require_ok(
        request_json(
            "/order",
            "POST",
            {
                "side": side,
                "symbol": symbol.upper(),
                "volume": volume,
                "stop": stop,
                "confirmation": confirmation,
            },
        ),
        "order failed",
    )
    return (
        f"Demo order sent: {body['side']} {body['volume']} {body['symbol']} "
        f"at {body['price']} stop {body['stop']} ticket {body['ticket']}"
    )


def close_text(ticket, confirmation):
    body = require_ok(
        request_json("/close", "POST", {"ticket": ticket, "confirmation": confirmation}),
        "close failed",
    )
    return f"Close request sent for ticket {body['ticket']}."