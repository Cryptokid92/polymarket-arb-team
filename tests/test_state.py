from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from arb.money import d
from arb.state import StateStore


def test_restore_round_trip_open_order_fill_inventory_pnl_halt(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite"
    store = StateStore(path)
    store.record_open_order(
        client_order_id="cid-yes-1",
        condition_id="0xmkt",
        token_id="yes-1",
        side="YES",
        size=d("10"),
    )
    store.record_fill(
        client_order_id="cid-yes-1",
        condition_id="0xmkt",
        size=d("10"),
        price=d("0.55"),
        ts_ms=1_000,
    )
    store.set_inventory("0xmkt", d("10"), d("0"))
    store.set_daily_pnl(d("-1.25"))
    store.set_bankroll(d("500.30"))
    store.set_halted(True, reason="ws_stale")

    restored = StateStore(path).restore()
    assert restored.halted is True
    assert restored.halt_reason == "ws_stale"
    assert restored.daily_pnl == d("-1.25")
    assert restored.bankroll == d("500.30")
    assert restored.inventory["0xmkt"] == (d("10"), d("0"))
    assert "cid-yes-1" in restored.client_order_ids
    assert len(restored.open_orders) == 1
    assert restored.open_orders[0]["client_order_id"] == "cid-yes-1"
    assert restored.open_orders[0]["token_id"] == "yes-1"
    assert Decimal(restored.open_orders[0]["size"]) == d("10")
    assert len(restored.fills) == 1
    assert Decimal(restored.fills[0]["size"]) == d("10")
    assert Decimal(restored.fills[0]["price"]) == d("0.55")


def test_restore_does_not_duplicate_open_pair_or_client_order_id(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite"
    store = StateStore(path)
    assert store.record_open_order(
        client_order_id="cid-pair-yes",
        condition_id="0xmkt",
        token_id="yes-1",
        side="YES",
        size=d("10"),
    )
    assert store.record_open_order(
        client_order_id="cid-pair-no",
        condition_id="0xmkt",
        token_id="no-1",
        side="NO",
        size=d("10"),
    )

    restored = StateStore(path).restore()
    assert restored.client_order_ids == {"cid-pair-yes", "cid-pair-no"}
    assert len(restored.open_orders) == 2

    again = StateStore(path)
    assert again.has_client_order_id("cid-pair-yes")
    assert again.record_open_order(
        client_order_id="cid-pair-yes",
        condition_id="0xmkt",
        token_id="yes-1",
        side="YES",
        size=d("10"),
    ) is False
    assert again.record_open_order(
        client_order_id="cid-pair-no",
        condition_id="0xmkt",
        token_id="no-1",
        side="NO",
        size=d("10"),
    ) is False

    after = again.restore()
    assert len(after.open_orders) == 2
    assert after.client_order_ids == {"cid-pair-yes", "cid-pair-no"}


def test_missing_bankroll_meta_is_none(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite"
    store = StateStore(path)
    restored = store.restore()
    assert restored.bankroll is None
    assert restored.daily_pnl == Decimal("0")


def test_default_state_path_is_gitignored_sqlite() -> None:
    store = StateStore()
    assert store.path == Path("data/state.sqlite")
    gitignore = Path(".gitignore").read_text(encoding="utf-8")
    assert "data/" in gitignore
