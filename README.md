# GrokBotSwarm

Discord control plane for a six-agent **demo-trading** swarm. MetaTrader 5 stays
on the Windows host. Orders are sent only through the local MT5 bridge, which
rejects non-demo accounts.

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python main.py
```

Configure `.env`:

```ini
DISCORD_TOKEN=...
MT5_BRIDGE_URL=http://127.0.0.1:8765
MT5_BRIDGE_TOKEN=the-same-secret-used-by-the-bridge
SWARM_AUTO=on
SWARM_CYCLE_SECONDS=300
```

Start the bridge on the MT5 Windows host in a separate terminal:

```powershell
$env:MT5_BRIDGE_TOKEN = "the-same-secret-used-by-the-bot"
python mt5_bridge.py
```

With `SWARM_AUTO=on`, the bot starts a cycle immediately after Discord connects
and repeats it every `SWARM_CYCLE_SECONDS`. The `/scheduler on DEMO` command
also starts it for the current process, but does not persist after a restart.

## Commands

- `/status` swarm health
- `/scheduler on DEMO` enable the current process
- `/auto DEMO` run one decision cycle now
- `/watch`, `/positions`, `/account` inspect MT5

Agents: `market`, `risk`, `execution`, `news`, `journal`, `coordinator`.

The bridge evaluates each symbol's closed trades over a configurable rolling
window (7 days by default). A symbol needs at least 5 closed trades and 3
losses with negative net profit to enter a temporary 12-hour performance
cooldown. It is automatically eligible again after the cooldown expires.

## Optional: Kronos research

Kronos supports `shadow` mode (logging only) and `gate` mode. In `gate` mode,
the existing strategy must agree with Kronos before an order is submitted. If
Kronos is unavailable or disagrees, the bot holds.

On the Ubuntu VPS:

```bash
git clone https://github.com/shiyu-coder/Kronos.git ~/Kronos
source ~/GrokBotSwarm/.venv/bin/activate
pip install -r ~/Kronos/requirements.txt
```

Then set in the VPS `.env`:

```ini
SWARM_KRONOS_MODE=gate
KRONOS_HOME=/home/ubuntu/Kronos
```

The first cycle downloads the public Kronos-small model weights.
