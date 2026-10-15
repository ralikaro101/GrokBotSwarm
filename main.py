import discord
from discord import app_commands

import config
from agents import AGENTS, answer
import journal
import mt5_client


intents = discord.Intents.default()
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)


@bot.event
async def on_ready():
    await tree.sync()
    print(f"GrokBotSwarm online as {bot.user}")


@tree.command(name="status", description="Show swarm health")
async def status(interaction: discord.Interaction):
    connected = "configured" if config.MT5_BRIDGE_URL else "not configured"
    await interaction.response.send_message(
        f"Online. {len(AGENTS)} agents loaded. MT5 bridge is {connected}."
    )


async def bridge_reply(interaction, producer):
    await interaction.response.defer(thinking=True)
    try:
        text = producer()
    except Exception as exc:
        text = str(exc)
    await interaction.followup.send(text[:1900])


@tree.command(name="account", description="Show the connected MT5 demo account")
async def account(interaction: discord.Interaction):
    await bridge_reply(interaction, mt5_client.account_text)


@tree.command(name="price", description="Show a live MT5 price")
@app_commands.describe(symbol="Symbol, for example EURUSD")
async def price(interaction: discord.Interaction, symbol: str = "EURUSD"):
    await bridge_reply(interaction, lambda: mt5_client.price_text(symbol))


@tree.command(name="positions", description="Show open MT5 positions")
async def positions(interaction: discord.Interaction):
    await bridge_reply(interaction, mt5_client.positions_text)



@tree.command(name="watch", description="Show all watched market prices")
async def watch(interaction: discord.Interaction):
    await bridge_reply(interaction, mt5_client.watch_text)


@tree.command(name="buy", description="Place a guarded demo buy order")
@app_commands.describe(symbol="Watched symbol", volume="Lot size", stop="Stop-loss price", confirmation="Type DEMO")
async def buy(interaction: discord.Interaction, symbol: str, volume: float, stop: float, confirmation: str):
    await bridge_reply(interaction, lambda: place("buy", symbol, volume, stop, confirmation))


@tree.command(name="sell", description="Place a guarded demo sell order")
@app_commands.describe(symbol="Watched symbol", volume="Lot size", stop="Stop-loss price", confirmation="Type DEMO")
async def sell(interaction: discord.Interaction, symbol: str, volume: float, stop: float, confirmation: str):
    await bridge_reply(interaction, lambda: place("sell", symbol, volume, stop, confirmation))


@tree.command(name="close", description="Close one demo position")
@app_commands.describe(ticket="Position ticket", confirmation="Type DEMO")
async def close(interaction: discord.Interaction, ticket: int, confirmation: str):
    await bridge_reply(interaction, lambda: close_position(ticket, confirmation))


@tree.command(name="note", description="Record a shared note for every agent")
@app_commands.describe(text="Note to store in the shared journal")
async def note(interaction: discord.Interaction, text: str):
    journal.record("operator", "note", text)
    await interaction.response.send_message("Note recorded.")


def place(side, symbol, volume, stop, confirmation):
    result = mt5_client.order_text(side, symbol, volume, stop, confirmation)
    journal.record("execution", side, result, symbol)
    return result


def close_position(ticket, confirmation):
    result = mt5_client.close_text(ticket, confirmation)
    journal.record("execution", "close", result)
    return result

@tree.command(name="agents", description="List the six agents")
async def agents_cmd(interaction: discord.Interaction):
    lines = [f"{key}: {item['role']}" for key, item in AGENTS.items()]
    await interaction.response.send_message("\n".join(lines))


@tree.command(name="ask", description="Ask one agent")
@app_commands.describe(agent="Agent name", question="Question for that agent")
async def ask(interaction: discord.Interaction, agent: str, question: str):
    key = agent.lower()
    if key not in AGENTS:
        names = ", ".join(AGENTS)
        await interaction.response.send_message(f"Unknown agent. Use one of: {names}")
        return
    await interaction.response.send_message(answer(key, question)[:1900])


@tree.command(name="brief", description="Ask all six agents")
@app_commands.describe(question="Question for the swarm")
async def brief(interaction: discord.Interaction, question: str = "Status check"):
    lines = [answer(key, question) for key in AGENTS]
    await interaction.response.send_message("\n".join(lines)[:1900])


def main():
    if not config.DISCORD_TOKEN:
        raise SystemExit("Set DISCORD_TOKEN in .env before starting.")
    bot.run(config.DISCORD_TOKEN)


if __name__ == "__main__":
    main()
