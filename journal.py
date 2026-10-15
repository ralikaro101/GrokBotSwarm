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