from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from arb.books import Book, BookStore
from arb.config import Settings
from arb.hunter import hunt
from arb.killswitch import KillSwitch
from arb.money import d
from arb.risk import MarketFlags, Portfolio, approve
from arb.state import StateStore

FIXTURES = Path(__file__).parent / "fixtures" / "books"
MIN_EDGE = d("0.01")


def _settings(**overrides: Any) -> Settings:
    base = dict(
        max_notional_per_trade=d("25"),
        max_daily_loss=d("50"),
        max_open_pairs=3,
        min_edge=d("0.01"),
        max_gap=d("0.08"),
        stale_ms=400,
        hedge_timeout_ms=1500,
        ws_stale_ms=3000,
    )
    base.update(overrides)
    return Settings(**base)


def _flags(**overrides: Any) -> MarketFlags:
    base = dict(accepting_orders=True, seconds_delay=0, neg_risk=False, binary=True)
    base.update(overrides)
    return MarketFlags(**base)


def _portfolio(**overrides: Any) -> Portfolio:
    base: dict[str, Any] = dict(
        yes={},
        no={},
        open_pairs=0,
        daily_pnl=d("0"),
        halted=False,
    )
    base.update(overrides)
    return Portfolio(**base)


def _load_pair(name: str) -> tuple[Book, Book, dict[str, Any]]:
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    store = BookStore()
    yes = store.apply_snapshot(payload["yes"])
    no = store.apply_snapshot(payload["no"])
    return yes, no, payload


def _gap_3c():
    yes, no, payload = _load_pair("gap_3c.json")
    found = hunt(yes, no, MIN_EDGE, yes.min_order_size, d(payload["max_shares"]), now_ms=1000)
    assert found is not None
    return found


def _switch(tmp_path: Path, settings: Settings | None = None) -> KillSwitch:
    return KillSwitch(
        project_root=tmp_path,
        state=StateStore(tmp_path / "state.sqlite"),
        settings=settings or _settings(),
    )


def test_halt_file_trips_switch(tmp_path: Path) -> None:
    ks = _switch(tmp_path)
    assert ks.allow_new_intents() is True
    (tmp_path / "HALT").write_text("stop\n", encoding="utf-8")
    assert ks.evaluate(daily_pnl=d("0"), ws_age_ms=0, now_ms=10_000) is False
    assert ks.state.restore().halted is True
    assert ks.allow_new_intents() is False


def test_daily_loss_cap_trips_and_does_not_auto_resume(tmp_path: Path) -> None:
    ks = _switch(tmp_path)
    assert ks.evaluate(daily_pnl=d("-50"), ws_age_ms=0, now_ms=10_000) is False
    assert ks.state.restore().halted is True
    # Recovered PnL must not auto-clear the halt.
    assert ks.evaluate(daily_pnl=d("10"), ws_age_ms=0, now_ms=11_000) is False
    assert ks.allow_new_intents() is False
    assert ks.resume() is True
    assert ks.allow_new_intents() is True


def test_ws_stale_trips_switch(tmp_path: Path) -> None:
    ks = _switch(tmp_path)
    assert ks.evaluate(daily_pnl=d("0"), ws_age_ms=3001, now_ms=10_000) is False
    assert ks.state.restore().halted is True
    assert ks.state.restore().halt_reason == "ws_stale"


def test_trip_persists_halt_reason_and_does_not_overwrite(tmp_path: Path) -> None:
    ks = _switch(tmp_path)
    ks.trip("ws_stale")
    assert ks.state.restore().halted is True
    assert ks.state.restore().halt_reason == "ws_stale"
    ks.trip("daily_loss")
    assert ks.state.restore().halt_reason == "ws_stale"
    assert ks.evaluate(daily_pnl=d("10"), ws_age_ms=0, now_ms=11_000) is False
    assert ks.state.restore().halt_reason == "ws_stale"
    assert ks.resume() is True
    assert ks.allow_new_intents() is True
    assert ks.state.restore().halt_reason == ""


def test_three_hedge_incidents_per_hour_trip(tmp_path: Path) -> None:
    ks = _switch(tmp_path)
    now = 3_600_000
    ks.state.record_hedge_incident(now - 1000)
    ks.state.record_hedge_incident(now - 2000)
    ks.state.record_hedge_incident(now - 3000)
    assert ks.evaluate(daily_pnl=d("0"), ws_age_ms=0, now_ms=now) is False
    assert ks.state.restore().halted is True


def test_resume_refuses_while_halt_file_present(tmp_path: Path) -> None:
    ks = _switch(tmp_path)
    ks.trip("manual")
    (tmp_path / "HALT").write_text("stop\n", encoding="utf-8")
    assert ks.resume() is False
    assert ks.allow_new_intents() is False
    (tmp_path / "HALT").unlink()
    assert ks.resume() is True
    assert ks.allow_new_intents() is True


def test_halt_blocks_hunter_intents(tmp_path: Path) -> None:
    ks = _switch(tmp_path)
    ks.trip("test")
    assert ks.allow_new_intents() is False

    gap = _gap_3c()
    restored = ks.state.restore()
    approved = approve(
        gap,
        _portfolio(halted=restored.halted),
        _settings(),
        _flags(),
    )
    assert approved is None

    # Healthy hunt still emits; approve/kill switch refuse new intents.
    yes, no, payload = _load_pair("gap_3c.json")
    found = hunt(
        yes,
        no,
        d("0.01"),
        yes.min_order_size,
        d(payload["max_shares"]),
        now_ms=1000,
    )
    assert found is not None
    assert ks.allow_new_intents() is False
