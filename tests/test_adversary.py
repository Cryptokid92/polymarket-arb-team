from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from arb.adversary import detect_lookahead, detect_mid_fill, lie_by_lookahead, lie_by_mid_fill
from arb.backtest import BacktestConfig, run_backtest
from arb.fees import pair_taker_fees
from arb.money import d
from arb.recorder import load_jsonl

RECORDED = Path(__file__).parent / "fixtures" / "recorded" / "gap_persist.jsonl"


def _cfg(**overrides: object) -> BacktestConfig:
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


def _book(
    ts_ms: int,
    side: str,
    asset_id: str,
    bid: str,
    ask: str,
    ask_size: str = "100",
    bid_size: str = "20",
) -> dict:
    return {
        "event_type": "book",
        "ts_ms": ts_ms,
        "timestamp": str(ts_ms),
        "condition_id": "syn-adv",
        "asset_id": asset_id,
        "market_side": side,
        "tick_size": "0.01",
        "min_order_size": "5",
        "bids": [{"price": bid, "size": bid_size}],
        "asks": [{"price": ask, "size": ask_size}],
    }


def test_detect_mid_fill_catches_mid_fill_lies() -> None:
    honest = run_backtest(load_jsonl(RECORDED), _cfg())
    detect_mid_fill(honest)
    lying = lie_by_mid_fill(honest)
    with pytest.raises(AssertionError, match="mid-fill"):
        detect_mid_fill(lying)


def test_vanished_second_ask_is_not_a_completed_pair() -> None:
    events = [
        _book(1000, "YES", "yes-v", "0.54", "0.55", ask_size="80", bid_size="80"),
        _book(1000, "NO", "no-v", "0.41", "0.42", ask_size="80", bid_size="80"),
        # Second ask disappears before t+latency (1000+100=1100).
        _book(1050, "YES", "yes-v", "0.54", "0.55", ask_size="80", bid_size="80"),
        _book(1050, "NO", "no-v", "0.41", "0.99", ask_size="1", bid_size="80"),
    ]
    result = run_backtest(events, _cfg(latency_ms=100, p_miss=d("0")))
    assert result.completed_pairs == 0
    assert result.naked_incidents >= 1


def test_crypto_50c_2c_gap_taker_is_not_profitable() -> None:
    events = [
        _book(1000, "YES", "yes-50", "0.49", "0.50"),
        _book(1000, "NO", "no-50", "0.47", "0.48"),
    ]
    result = run_backtest(
        events,
        _cfg(
            latency_ms=0,
            p_miss=d("0"),
            fee_rate_yes=d("0.07"),
            fee_rate_no=d("0.07"),
            max_shares=d("100"),
            min_edge=d("0.01"),
        ),
    )
    fees = pair_taker_fees(
        d("100"), d("0.50"), d("100"), d("0.48"), d("0.07"), d("0.07")
    )
    raw = d("0.02") * d("100")
    assert fees > raw
    assert result.completed_pairs == 0
    assert result.net_pnl == Decimal("0")
    assert all(fill.kind != "taker_fak" for fill in result.fills)


def test_default_modules_have_no_network_client() -> None:
    from arb import adversary, backtest, recorder

    for module in (adversary, backtest, recorder):
        source = Path(module.__file__).read_text(encoding="utf-8").lower()
        assert "urllib" not in source
        assert "httpx" not in source
        assert "requests" not in source
        assert "asyncsecureclient" not in source
        assert "urlopen" not in source


def test_detect_lookahead_catches_hunter_seeing_book_t_plus_1() -> None:
    honest = run_backtest(load_jsonl(RECORDED), _cfg())
    detect_lookahead(honest)
    lying = lie_by_lookahead(honest)
    with pytest.raises(AssertionError, match="lookahead"):
        detect_lookahead(lying)
