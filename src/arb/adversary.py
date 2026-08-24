"""Adversarial checks that fail a lying backtest. Honest replay must pass."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from arb.backtest import BacktestResult, FillRecord

_TWO = Decimal("2")


def _mid(fill: FillRecord) -> Decimal:
    return (fill.best_bid + fill.best_ask) / _TWO


def has_mid_fill(result: BacktestResult) -> bool:
    """True when a buy was marked or priced at mid instead of ask VWAP."""
    for fill in result.fills:
        if fill.kind == "hedge":
            continue
        mid = _mid(fill)
        if fill.fill_source == "mid":
            return True
        if fill.ask_vwap is not None and fill.price == mid and fill.price != fill.ask_vwap:
            return True
    return False


def detect_mid_fill(result: BacktestResult) -> None:
    """Fail the suite when the engine filled buys at mid instead of asks."""
    if has_mid_fill(result):
        raise AssertionError("mid-fill lie detected: buys used mid, not ask VWAP")


def has_lookahead(result: BacktestResult) -> bool:
    """True when a hunter decision used a book from after decision time."""
    for decision in result.decisions:
        if decision.yes_book_ts_ms > decision.t_ms:
            return True
        if decision.no_book_ts_ms > decision.t_ms:
            return True
    return False


def detect_lookahead(result: BacktestResult) -> None:
    """Hard fail if the hunter saw book[t+1] at time t."""
    if has_lookahead(result):
        raise AssertionError("lookahead lie detected: hunter saw book[t+1] at time t")


def lie_by_mid_fill(result: BacktestResult) -> BacktestResult:
    """Feed mids instead of asks. detect_mid_fill must catch this."""
    rewritten: list[FillRecord] = []
    for fill in result.fills:
        if fill.kind == "hedge":
            rewritten.append(fill)
            continue
        mid = _mid(fill)
        rewritten.append(replace(fill, price=mid, fill_source="mid"))
    return replace(result, fills=rewritten)


def lie_by_lookahead(result: BacktestResult) -> BacktestResult:
    """Rewrite traces so each hunt at t used the next book's timestamp."""
    lying = []
    decisions = result.decisions
    for index, decision in enumerate(decisions):
        if index + 1 < len(decisions):
            nxt = decisions[index + 1]
            lying.append(
                replace(
                    decision,
                    yes_book_ts_ms=nxt.yes_book_ts_ms,
                    no_book_ts_ms=nxt.no_book_ts_ms,
                )
            )
        else:
            lying.append(
                replace(
                    decision,
                    yes_book_ts_ms=decision.t_ms + 1,
                    no_book_ts_ms=decision.t_ms + 1,
                )
            )
    return replace(result, decisions=lying)
