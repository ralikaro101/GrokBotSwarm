import discord
from discord import app_commands

import config
from agents import AGENTS, answer


intents = discord.Intents.default()
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)


@bot.event
async def on_ready():
    await tree.sync()
    print(f"GrokBotSwarm online as {bot.user}")


@tree.command(name="status", description="Show swarm health")
async def status(interaction: discord.Interaction):
    await interaction.response.send_message(
        f"Online. {len(AGENTS)} agents loaded. MT5 execution is not connected."
    )


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
