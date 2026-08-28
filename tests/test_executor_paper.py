"""Task 7 contracts: paper executor + live broker dual gate."""

from __future__ import annotations

import ast
import inspect
import json
import textwrap
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from arb.app import paper_execute, run_pipeline
from arb.books import BookStore
from arb.config import Settings
from arb.executor import LiveBroker, PaperBroker
from arb.fee_agent import MarketFees
from arb.hunter import hunt
from arb.money import d
from arb.risk import MarketFlags, Portfolio

FIXTURES = Path(__file__).parent / "fixtures" / "books"
CRYPTO = MarketFees(yes_rate=d("0.07"), no_rate=d("0.07"))


def _settings() -> Settings:
    return Settings(
        max_notional_per_trade=d("25"),
        max_daily_loss=d("50"),
        max_open_pairs=3,
        min_edge=d("0.01"),
        max_gap=d("0.08"),
        stale_ms=400,
        hedge_timeout_ms=1500,
        ws_stale_ms=3000,
    )


def _flags() -> MarketFlags:
    return MarketFlags(accepting_orders=True, seconds_delay=0, neg_risk=False, binary=True)


def _portfolio() -> Portfolio:
    return Portfolio(yes={}, no={}, open_pairs=0, daily_pnl=d("0"), halted=False)


def _load_pair(name: str) -> tuple[Any, Any, dict[str, Any]]:
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    store = BookStore()
    yes = store.apply_snapshot(payload["yes"])
    no = store.apply_snapshot(payload["no"])
    return yes, no, payload


def _assert_no_secure_client(source: str) -> None:
    assert "AsyncSecureClient" not in source
    assert "from polymarket" not in source
    tree = ast.parse(textwrap.dedent(source))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "AsyncSecureClient"


def test_paper_modules_never_import_secure_client() -> None:
    import arb.app as app_mod
    import arb.bus as bus_mod
    import arb.executor as executor_mod

    _assert_no_secure_client(inspect.getsource(app_mod))
    _assert_no_secure_client(inspect.getsource(bus_mod))
    _assert_no_secure_client(inspect.getsource(PaperBroker))
    _assert_no_secure_client(inspect.getsource(executor_mod.PaperBroker.post_pair))


@pytest.mark.asyncio
async def test_paper_broker_writes_one_jsonl_record(tmp_path: Path) -> None:
    yes, no, _ = _load_pair("gap_3c.json")
    intent = run_pipeline(yes, no, _settings(), _flags(), CRYPTO, _portfolio(), now_ms=1000)
    assert intent is not None
    log_path = tmp_path / "intents.jsonl"
    broker = PaperBroker(log_path=log_path)
    yes_order, no_order = await paper_execute(intent, broker)
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["path"] == intent.path
    assert record["yes_order"]["order_id"] == yes_order.order_id
    assert record["no_order"]["order_id"] == no_order.order_id
    _assert_no_secure_client(inspect.getsource(PaperBroker.post_pair))


def test_live_broker_raises_without_allow_live(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ARB_MODE", "live")
    assert not (tmp_path / "ALLOW_LIVE").exists()
    with pytest.raises(RuntimeError, match="live trading is not allowed"):
        LiveBroker(client=object(), project_root=tmp_path)


def test_live_broker_raises_in_paper_mode_even_with_allow_live(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ARB_MODE", "paper")
    (tmp_path / "ALLOW_LIVE").write_text(date.today().isoformat() + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="live trading is not allowed"):
        LiveBroker(client=object(), project_root=tmp_path)


@pytest.mark.asyncio
async def test_live_broker_post_pair_raises_without_gate(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ARB_MODE", "live")
    with pytest.raises(RuntimeError, match="live trading is not allowed"):
        broker = LiveBroker(client=object(), project_root=tmp_path)
        yes, no, _ = _load_pair("gap_3c.json")
        intent = run_pipeline(yes, no, _settings(), _flags(), CRYPTO, _portfolio(), now_ms=1000)
        assert intent is not None
        await broker.post_pair(intent)


def test_pipeline_gap_3c_produces_maker_gtc() -> None:
    yes, no, _ = _load_pair("gap_3c.json")
    intent = run_pipeline(yes, no, _settings(), _flags(), CRYPTO, _portfolio(), now_ms=1000)
    assert intent is not None
    assert intent.path == "maker_gtc"
    assert intent.size > 0
    assert intent.size * (intent.yes_limit + intent.no_limit) <= d("25")


def test_pipeline_no_gap_uses_maker_completeness() -> None:
    yes, no, payload = _load_pair("no_gap.json")
    found = hunt(yes, no, d("0.01"), yes.min_order_size, d("50"), now_ms=1000)
    assert found is None
    intent = run_pipeline(yes, no, _settings(), _flags(), CRYPTO, _portfolio(), now_ms=1000)
    assert intent is not None
    assert intent.path == "maker_gtc"
    assert intent.yes_limit + intent.no_limit == d("0.98")
    assert payload["yes"]["asks"][0]["price"] == "0.50"
