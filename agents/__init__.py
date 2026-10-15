"""Six swarm agents sharing one SQLite journal."""

import journal
import mt5_client

AGENTS = {
    "market": {"name": "Market", "role": "Reads prices for every watched symbol."},
    "risk": {"name": "Risk", "role": "Rejects orders without a stop or above the size limit."},
    "execution": {"name": "Execution", "role": "Sends an approved demo order to MT5."},
    "news": {"name": "News", "role": "Records event warnings supplied by the operator."},
    "research": {"name": "Research", "role": "Tests recent price behavior and shares evidence with the swarm."},
    "journal": {"name": "Journal", "role": "Reads the shared record of agent activity."},
    "coordinator": {"name": "Coordinator", "role": "Combines prices, risk, and journal state."},
}


def snapshot():
    prices = mt5_client.watch_rows()
    positions = mt5_client.positions_rows()
    return prices, positions, journal.recent_text(5)


def answer(agent_id, question):
    text = question.strip() or "Status check"
    try:
        prices, positions, history = snapshot()
    except mt5_client.BridgeError as exc:
        journal.record(agent_id, "bridge-error", str(exc))
        return f"{AGENTS[agent_id]['name']}: bridge unavailable: {exc}"

    symbols = ", ".join(f"{row['symbol']} {row['bid']}/{row['ask']}" for row in prices) or "none"
    exposure = ", ".join(f"{row['symbol']} {row['type']} {row['volume']}" for row in positions) or "flat"
    if agent_id == "market":
        result = f"Watching {symbols}."
    elif agent_id == "risk":
        result = f"Open exposure: {exposure}. No order is allowed without a stop and the word DEMO."
    elif agent_id == "execution":
        result = "Execution is idle. Use /buy or /sell with symbol, volume, stop, and DEMO."
    elif agent_id == "news":
        result = "No news feed is connected. Record warnings manually with /note."
    elif agent_id == "research":
        parts = []
        for row in prices:
            evidence = mt5_client.research(row["symbol"])
            parts.append(f"{row['symbol']} accuracy {evidence['accuracy']} on {evidence['acted']} signals")
        result = "; ".join(parts) or "No research data."
    elif agent_id == "journal":
        result = history
    else:
        result = f"Prices: {symbols}. Exposure: {exposure}. Recent decisions: {history}"
    journal.record(agent_id, "answer", f"{text} | {result}")
    return f"{AGENTS[agent_id]['name']}: {result}"