"""HTTP client for the read-only Windows MT5 bridge."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import config


class BridgeError(RuntimeError):
    pass


def get_json(path):
    if not config.MT5_BRIDGE_URL or not config.MT5_BRIDGE_TOKEN:
        raise BridgeError("MT5 bridge is not configured.")
    request = Request(
        config.MT5_BRIDGE_URL.rstrip("/") + path,
        headers={"X-Bridge-Token": config.MT5_BRIDGE_TOKEN},
    )
    try:
        with urlopen(request, timeout=8) as response:
            return json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise BridgeError(f"Bridge returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise BridgeError(f"Bridge is unreachable: {exc.reason}") from exc


def account_text():
    body = get_json("/account")
    if not body.get("ok"):
        raise BridgeError(str(body.get("error", "account request failed")))
    return (
        f"Account {body['login']} on {body['server']}\n"
        f"Balance {body['balance']:.2f} {body['currency']}\n"
        f"Equity {body['equity']:.2f}\n"
        f"Free margin {body['margin_free']:.2f}\n"
        f"Open profit {body['profit']:.2f}"
    )


def price_text(symbol):
    body = get_json("/price?symbol=" + symbol.upper())
    if not body.get("ok"):
        raise BridgeError(str(body.get("error", "price request failed")))
    return f"{body['symbol']}: bid {body['bid']} ask {body['ask']}"


def positions_text():
    body = get_json("/positions")
    if not body.get("ok"):
        raise BridgeError(str(body.get("error", "positions request failed")))
    rows = body["positions"]
    if not rows:
        return "No open positions."
    lines = [
        f"{row['ticket']} {row['symbol']} {row['type']} {row['volume']} "
        f"open {row['price_open']} now {row['price_current']} profit {row['profit']}"
        for row in rows[:20]
    ]
    return f"{body['count']} open position(s)\n" + "\n".join(lines)
