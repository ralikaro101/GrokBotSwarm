"""Six read-only swarm agents. They advise. They do not send MT5 orders."""

AGENTS = {
    "market": {
        "name": "Market",
        "role": "Reads price context and says whether conditions are tradable.",
    },
    "risk": {
        "name": "Risk",
        "role": "Checks size, stop distance, and whether a trade should be skipped.",
    },
    "execution": {
        "name": "Execution",
        "role": "Turns an approved idea into an order plan. Does not send it.",
    },
    "news": {
        "name": "News",
        "role": "Flags scheduled events that can invalidate a setup.",
    },
    "journal": {
        "name": "Journal",
        "role": "Records the decision and the reason it was allowed or blocked.",
    },
    "coordinator": {
        "name": "Coordinator",
        "role": "Collects the other agents and gives one decision.",
    },
}


def answer(agent_id: str, question: str) -> str:
    agent = AGENTS[agent_id]
    text = question.strip() or "No question supplied."
    if agent_id == "coordinator":
        return (
            f"{agent['name']}: hold. Market, risk, execution, news, and journal "
            f"have not been wired to live MT5 data. Question: {text}"
        )
    return f"{agent['name']}: no live feed yet. I can only acknowledge: {text}"
