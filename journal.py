"""Shared SQLite journal used by every agent."""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).with_name("swarm.db")


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        create table if not exists events (
            id integer primary key,
            created_at text default current_timestamp,
            agent text not null,
            symbol text,
            action text not null,
            detail text not null
        )
        """
    )
    conn.execute(
        """
        create table if not exists closed_trades (
            exit_deal integer primary key,
            position_id integer,
            closed_at text not null,
            symbol text not null,
            side text not null,
            volume real not null,
            profit real not null,
            commission real not null,
            swap real not null,
            net_profit real not null,
            magic integer
        )
        """
    )
    return conn


def record(agent, action, detail, symbol=""):
    with connect() as conn:
        conn.execute(
            "insert into events(agent, symbol, action, detail) values (?, ?, ?, ?)",
            (agent, symbol.upper(), action, detail[:1000]),
        )


def recent(limit=10):
    with connect() as conn:
        rows = conn.execute(
            """
            select id, created_at, agent, symbol, action, detail
            from events order by id desc limit ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def recent_text(limit=8):
    rows = recent(limit)
    if not rows:
        return "Shared journal is empty."
    return "\n".join(
        f"#{row['id']} {row['created_at']} {row['agent']} {row['symbol']} "
        f"{row['action']}: {row['detail']}"
        for row in rows
    )


def sync_closed_trades(trades):
    """Persist broker-confirmed closed trade outcomes for every agent to reuse."""
    with connect() as conn:
        conn.executemany(
            """
            insert into closed_trades(
                exit_deal, position_id, closed_at, symbol, side, volume,
                profit, commission, swap, net_profit, magic
            ) values (
                :exit_deal, :position_id, :closed_at, :symbol, :side, :volume,
                :profit, :commission, :swap, :net_profit, :magic
            )
            on conflict(exit_deal) do update set
                position_id=excluded.position_id,
                closed_at=excluded.closed_at,
                symbol=excluded.symbol,
                side=excluded.side,
                volume=excluded.volume,
                profit=excluded.profit,
                commission=excluded.commission,
                swap=excluded.swap,
                net_profit=excluded.net_profit,
                magic=excluded.magic
            """,
            trades,
        )


def symbol_performance():
    """Return trade-level expectancy evidence grouped by symbol."""
    with connect() as conn:
        rows = conn.execute(
            """
            select
                symbol,
                count(*) as trades,
                sum(case when net_profit > 0 then 1 else 0 end) as wins,
                sum(case when net_profit < 0 then 1 else 0 end) as losses,
                round(sum(net_profit), 2) as net_profit,
                round(sum(case when net_profit > 0 then net_profit else 0 end), 2)
                    as gross_profit,
                round(sum(case when net_profit < 0 then net_profit else 0 end), 2)
                    as gross_loss,
                round(avg(net_profit), 4) as expectancy
            from closed_trades
            group by symbol
            """
        ).fetchall()
    results = {}
    for row in rows:
        item = dict(row)
        gross_loss = abs(item["gross_loss"] or 0)
        item["profit_factor"] = (
            round(item["gross_profit"] / gross_loss, 3) if gross_loss else None
        )
        results[item["symbol"]] = item
    return results
