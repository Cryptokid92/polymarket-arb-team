from __future__ import annotations

import ast
import inspect
from decimal import Decimal
from pathlib import Path

from arb.adversary import detect_lookahead, detect_mid_fill
from arb.backtest import (
    BacktestConfig,
    analyze_tape_edges,
    run_backtest,
    summarize_tape,
    walk_bids,
)
from arb.books import Level
from arb.fees import pair_taker_fees
from arb.money import d
from arb.recorder import load_jsonl

RECORDED = Path(__file__).parent / "fixtures" / "recorded" / "gap_persist.jsonl"


def _honest_cfg(**overrides: object) -> BacktestConfig:
    values: dict[str, object] = dict(
        path="taker_fak",
        p_miss=d("0"),
        latency_ms=100,
        hedge_slippage=d("0.01"),
        fee_rate_yes=d("0"),
        fee_rate_no=d("0"),
        min_edge=d("0.01"),
        min_size=d("5"),
        max_shares=d("80"),
        starting_capital=d("100"),
        rng_seed=1,
    )
    values.update(overrides)
    return BacktestConfig(**values)  # type: ignore[arg-type]


def test_honest_replay_completes_pair_on_ask_vwap_not_mid() -> None:
    events = load_jsonl(RECORDED)
    result = run_backtest(events, _honest_cfg())
    assert result.completed_pairs >= 1
    assert result.trades >= 1
    assert result.net_pnl > Decimal("0")
    assert result.capital_turns > Decimal("0")
    buys = [fill for fill in result.fills if fill.kind != "hedge"]
    assert buys
    for fill in buys:
        assert fill.fill_source == "ask"
        mid = (fill.best_bid + fill.best_ask) / Decimal("2")
        assert fill.price == fill.ask_vwap
        assert fill.price != mid
    detect_mid_fill(result)
    detect_lookahead(result)


def test_p_miss_one_makes_second_fak_fail_naked() -> None:
    events = load_jsonl(RECORDED)
    result = run_backtest(events, _honest_cfg(p_miss=d("1")))
    assert result.completed_pairs == 0
    assert result.naked_incidents >= 1
    sides = {fill.side for fill in result.fills if fill.kind != "hedge"}
    assert sides == {"YES"}
    hedges = [fill for fill in result.fills if fill.kind == "hedge"]
    assert hedges
    assert hedges[0].fill_source == "bid"
    assert hedges[0].price == d("0.54") - d("0.01")


def test_taker_fees_are_subtracted() -> None:
    events = _wide_gap_events()
    free = run_backtest(events, _honest_cfg(latency_ms=0, max_shares=d("80")))
    taxed = run_backtest(
        events,
        _honest_cfg(
            latency_ms=0,
            max_shares=d("80"),
            fee_rate_yes=d("0.07"),
            fee_rate_no=d("0.07"),
        ),
    )
    assert taxed.completed_pairs == free.completed_pairs
    assert taxed.completed_pairs >= 1
    assert taxed.net_pnl < free.net_pnl
    size = taxed.fills[0].size
    expected_fees = pair_taker_fees(
        size, d("0.60"), size, d("0.32"), d("0.07"), d("0.07")
    )
    assert free.net_pnl - taxed.net_pnl == expected_fees * taxed.completed_pairs


def test_gap_persist_crypto_fees_do_not_complete_nonpositive_taker_ev() -> None:
    events = load_jsonl(RECORDED)
    result = run_backtest(
        events,
        _honest_cfg(fee_rate_yes=d("0.07"), fee_rate_no=d("0.07")),
    )
    assert result.completed_pairs == 0
    assert all(fill.kind != "taker_fak" for fill in result.fills)


def test_run_backtest_hunt_calls_choose_intent_taker() -> None:
    source = inspect.getsource(run_backtest)
    assert "choose_intent" in source
    assert 'source="taker"' in source or "source='taker'" in source


def test_walk_bids_uses_depth_not_mid() -> None:
    bids = [Level(price=d("0.54"), size=d("10")), Level(price=d("0.50"), size=d("10"))]
    vwap, filled = walk_bids(bids, d("20"))
    assert filled == d("20")
    assert vwap == (d("0.54") * d("10") + d("0.50") * d("10")) / d("20")
    assert vwap != (d("0.54") + d("0.55")) / d("2")


def test_reports_required_fields() -> None:
    result = run_backtest(load_jsonl(RECORDED), _honest_cfg())
    for name in (
        "trades",
        "completed_pairs",
        "naked_incidents",
        "net_pnl",
        "capital_turns",
    ):
        assert hasattr(result, name)


def test_record_books_script_uses_official_public_client_only() -> None:
    source = Path("scripts/record_books.py").read_text(encoding="utf-8")
    assert "refuses to place orders" in source
    assert "AsyncSecureClient" not in source
    assert "from polymarket import AsyncPublicClient" in source
    assert "import urllib" not in source
    assert "import httpx" not in source
    assert "import requests" not in source

    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "record_books_cli", Path("scripts/record_books.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main(["--place-orders"]) == 2


def test_summarize_tape_empty_is_no_tape() -> None:
    summary = summarize_tape([])
    assert summary["verdict"] == "no_tape"
    assert summary["events"] == 0


def test_summarize_tape_gap_persist_is_positive() -> None:
    summary = summarize_tape(load_jsonl(RECORDED), _honest_cfg())
    assert summary["events"] >= 1
    assert int(summary["completed_pairs"]) >= 1
    assert summary["verdict"] == "positive"


def test_backtest_public_api_has_no_float_literals() -> None:
    source = inspect.getsource(run_backtest)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and type(node.value) is float:
            raise AssertionError("run_backtest must not use float literals")


def _wide_gap_events() -> list[dict]:
    rows: list[dict] = []
    for ts in (1000, 1100, 1200):
        for side, token, bid, ask in (
            ("YES", "yes-wide", "0.59", "0.60"),
            ("NO", "no-wide", "0.31", "0.32"),
        ):
            rows.append(
                {
                    "event_type": "book",
                    "ts_ms": ts,
                    "timestamp": str(ts),
                    "condition_id": "syn-wide",
                    "asset_id": token,
                    "market_side": side,
                    "tick_size": "0.01",
                    "min_order_size": "5",
                    "bids": [{"price": bid, "size": "80"}],
                    "asks": [{"price": ask, "size": "80"}],
                }
            )
    return rows


def _complete_ask_events() -> list[dict]:
    rows: list[dict] = []
    for ts in (1000, 1400, 1800):
        for side, token, bid, ask in (
            ("YES", "yes-flat", "0.49", "0.50"),
            ("NO", "no-flat", "0.49", "0.50"),
        ):
            rows.append(
                {
                    "event_type": "book",
                    "ts_ms": ts,
                    "timestamp": str(ts),
                    "condition_id": "syn-flat",
                    "asset_id": token,
                    "market_side": side,
                    "tick_size": "0.01",
                    "min_order_size": "5",
                    "bids": [{"price": bid, "size": "20"}],
                    "asks": [{"price": ask, "size": "50"}],
                }
            )
    return rows


def test_analyze_tape_complete_asks_is_maker_completeness() -> None:
    analysis = analyze_tape_edges(_complete_ask_events())
    assert analysis["ask_gap_frames"] == 0
    assert int(analysis["maker_quote_frames"]) >= 1
    assert Decimal(str(analysis["best_ask_edge"])) == Decimal("0")
    assert analysis["decision"] == "maker_completeness"
    assert analysis["edge_thresholds"]["gte_0.01"] == 0


def test_maker_complete_tape_still_at_bid_does_not_fill() -> None:
    result = run_backtest(_complete_ask_events(), _honest_cfg())
    assert result.completed_pairs == 0
    buys = [fill for fill in result.fills if fill.kind != "hedge"]
    assert buys == []


def _ask_through_events() -> list[dict]:
    rows: list[dict] = []
    for ts, ask in ((1000, "0.50"), (1400, "0.49")):
        for side, token, bid in (
            ("YES", "yes-flat", "0.49"),
            ("NO", "no-flat", "0.49"),
        ):
            rows.append(
                {
                    "event_type": "book",
                    "ts_ms": ts,
                    "timestamp": str(ts),
                    "condition_id": "syn-through",
                    "asset_id": token,
                    "market_side": side,
                    "tick_size": "0.01",
                    "min_order_size": "5",
                    "bids": [{"price": bid, "size": "20"}],
                    "asks": [{"price": ask, "size": "50"}],
                }
            )
    return rows


def test_maker_complete_tape_fills_once_on_shown_take() -> None:
    result = run_backtest(_ask_through_events(), _honest_cfg())
    assert result.completed_pairs == 1
    buys = [fill for fill in result.fills if fill.kind != "hedge"]
    assert len(buys) == 2
    for fill in buys:
        assert fill.fill_source == "bid"
        assert fill.price == d("0.49")
        assert fill.size == d("20")


def test_analyze_tape_gap_persist_is_capture() -> None:
    analysis = analyze_tape_edges(load_jsonl(RECORDED))
    assert int(analysis["ask_gap_frames"]) >= 1
    assert analysis["decision"] == "capture"
    assert analysis["best_ask_edge"] == "0.03"


def test_hunt_tape_does_not_rest_as_maker_gtc() -> None:
    events = load_jsonl(RECORDED)
    result = run_backtest(
        events,
        _honest_cfg(path="maker_gtc", maker_rest_ms=400, latency_ms=0),
    )
    assert result.completed_pairs >= 1
    for fill in result.fills:
        if fill.kind != "hedge":
            assert fill.fill_source == "ask"
            assert fill.kind == "taker_fak"


def test_gap_persist_consumes_ask_depth() -> None:
    result = run_backtest(load_jsonl(RECORDED), _honest_cfg())
    assert result.completed_pairs == 1
    buys = [fill for fill in result.fills if fill.kind != "hedge"]
    assert len(buys) == 2
    assert {fill.size for fill in buys} == {d("80")}
