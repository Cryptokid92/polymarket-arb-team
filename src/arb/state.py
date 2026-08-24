"""Crash-safe sqlite state. Path injectable; default data/state.sqlite."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

_DEFAULT_PATH = Path("data/state.sqlite")


@dataclass
class RestoredState:
    open_orders: list[dict[str, str]]
    fills: list[dict[str, str]]
    inventory: dict[str, tuple[Decimal, Decimal]]
    daily_pnl: Decimal
    halted: bool
    halt_reason: str = ""
    bankroll: Decimal | None = None
    client_order_ids: set[str] = field(default_factory=set)


class StateStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else _DEFAULT_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._init()

    def _init(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS open_orders (
                client_order_id TEXT PRIMARY KEY,
                condition_id TEXT NOT NULL,
                token_id TEXT NOT NULL,
                side TEXT NOT NULL,
                size TEXT NOT NULL,
                status TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS fills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_order_id TEXT NOT NULL,
                condition_id TEXT NOT NULL,
                size TEXT NOT NULL,
                price TEXT NOT NULL,
                ts_ms INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS inventory (
                condition_id TEXT PRIMARY KEY,
                yes_shares TEXT NOT NULL,
                no_shares TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS hedge_incidents (
                ts_ms INTEGER NOT NULL
            );
            """
        )
        self._conn.commit()

    def _set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
            (key, value),
        )
        self._conn.commit()

    def _get_meta(self, key: str, default: str) -> str:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        return default if row is None else row[0]

    def set_halted(self, halted: bool, *, reason: str | None = None) -> None:
        if halted:
            already = self._get_meta("halted", "0") == "1"
            stored_reason = self._get_meta("halt_reason", "")
            if reason and (not already or not stored_reason):
                self._set_meta("halt_reason", reason)
            self._set_meta("halted", "1")
            return
        self._set_meta("halted", "0")
        self._set_meta("halt_reason", "")

    def set_daily_pnl(self, pnl: Decimal) -> None:
        self._set_meta("daily_pnl", str(pnl))

    def set_bankroll(self, bankroll: Decimal) -> None:
        self._set_meta("bankroll", str(bankroll))

    def set_inventory(
        self, condition_id: str, yes_shares: Decimal, no_shares: Decimal
    ) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO inventory(condition_id, yes_shares, no_shares)
            VALUES (?, ?, ?)
            """,
            (condition_id, str(yes_shares), str(no_shares)),
        )
        self._conn.commit()

    def record_open_order(
        self,
        client_order_id: str,
        condition_id: str,
        token_id: str,
        side: str,
        size: Decimal,
        status: str = "open",
    ) -> bool:
        try:
            self._conn.execute(
                """
                INSERT INTO open_orders(
                    client_order_id, condition_id, token_id, side, size, status
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    client_order_id,
                    condition_id,
                    token_id,
                    side,
                    str(size),
                    status,
                ),
            )
            self._conn.commit()
        except sqlite3.IntegrityError:
            return False
        return True

    def has_client_order_id(self, client_order_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM open_orders WHERE client_order_id = ?",
            (client_order_id,),
        ).fetchone()
        return row is not None

    def record_fill(
        self,
        client_order_id: str,
        condition_id: str,
        size: Decimal,
        price: Decimal,
        ts_ms: int,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO fills(client_order_id, condition_id, size, price, ts_ms)
            VALUES (?, ?, ?, ?, ?)
            """,
            (client_order_id, condition_id, str(size), str(price), ts_ms),
        )
        self._conn.commit()

    def record_hedge_incident(self, ts_ms: int) -> None:
        self._conn.execute(
            "INSERT INTO hedge_incidents(ts_ms) VALUES (?)", (ts_ms,)
        )
        self._conn.commit()

    def hedge_incidents_since(self, ts_ms: int) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM hedge_incidents WHERE ts_ms >= ?",
            (ts_ms,),
        ).fetchone()
        return int(row[0]) if row else 0

    def restore(self) -> RestoredState:
        open_orders = [
            {
                "client_order_id": row[0],
                "condition_id": row[1],
                "token_id": row[2],
                "side": row[3],
                "size": row[4],
                "status": row[5],
            }
            for row in self._conn.execute(
                "SELECT client_order_id, condition_id, token_id, side, size, status "
                "FROM open_orders"
            )
        ]
        fills = [
            {
                "client_order_id": row[0],
                "condition_id": row[1],
                "size": row[2],
                "price": row[3],
                "ts_ms": str(row[4]),
            }
            for row in self._conn.execute(
                "SELECT client_order_id, condition_id, size, price, ts_ms FROM fills"
            )
        ]
        inventory = {
            row[0]: (Decimal(row[1]), Decimal(row[2]))
            for row in self._conn.execute(
                "SELECT condition_id, yes_shares, no_shares FROM inventory"
            )
        }
        raw_bankroll = self._get_meta("bankroll", "")
        return RestoredState(
            open_orders=open_orders,
            fills=fills,
            inventory=inventory,
            daily_pnl=Decimal(self._get_meta("daily_pnl", "0")),
            halted=self._get_meta("halted", "0") == "1",
            halt_reason=self._get_meta("halt_reason", ""),
            bankroll=Decimal(raw_bankroll) if raw_bankroll else None,
            client_order_ids={row["client_order_id"] for row in open_orders},
        )
