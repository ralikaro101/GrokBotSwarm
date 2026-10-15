# GrokBotSwarm

Discord control plane for a six-agent trading swarm. This machine holds the code. MetaTrader 5 stays on the Windows host; this service does not place orders.

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python main.py
```

Put the Discord bot token in `.env` as `DISCORD_TOKEN`.

## Commands

- `!status` swarm health
- `!agents` the six agents
- `!ask <agent> <question>` one agent answers
- `!brief` all six agents answer

Agents: `market`, `risk`, `execution`, `news`, `journal`, `coordinator`.
