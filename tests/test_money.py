"""Task 1 contracts: Decimal money helpers and paper-default live gate."""

from __future__ import annotations

import ast
import inspect
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import get_args, get_origin, get_type_hints

from arb import config as config_mod
from arb import money as money_mod
from arb.config import Settings, live_allowed, load_settings
from arb.money import d, round_price, round_size


def _type_includes_float(annotation: object) -> bool:
    origin = get_origin(annotation)
    if annotation is float:
        return True
    if origin is None:
        return annotation is float
    return any(arg is float for arg in get_args(annotation))


def test_round_price_buys_round_down() -> None:
    assert round_price(d("0.556"), tick=d("0.01")) == Decimal("0.55")


def test_round_size_rounds_down_to_cent() -> None:
    assert round_size(d("1.239")) == Decimal("1.23")


def test_d_accepts_str_int_decimal_only() -> None:
    assert d("1.25") == Decimal("1.25")
    assert d(2) == Decimal(2)
    assert d(Decimal("3.5")) == Decimal("3.5")


def test_d_rejects_float() -> None:
    try:
        d(0.556)  # type: ignore[arg-type]
    except TypeError:
        return
    raise AssertionError("d() must reject float")


def test_money_public_helpers_never_use_float() -> None:
    public_helpers = (d, round_price, round_size)
    for helper in public_helpers:
        hints = get_type_hints(helper)
        for name, annotation in hints.items():
            assert not _type_includes_float(annotation), (
                f"{helper.__name__} annotation {name} must not include float"
            )
        source = inspect.getsource(helper)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id != "float", f"{helper.__name__} must not call float()"
            if isinstance(node, ast.Constant) and type(node.value) is float:
                raise AssertionError(f"{helper.__name__} must not use float literals")

    assert money_mod.D is Decimal


def test_default_arb_mode_is_paper() -> None:
    assert Settings.model_fields["arb_mode"].default == "paper"
    settings = Settings(
        max_notional_per_trade=Decimal("25"),
        max_daily_loss=Decimal("50"),
        max_open_pairs=3,
        min_edge=Decimal("0.01"),
        max_gap=Decimal("0.08"),
        stale_ms=400,
        hedge_timeout_ms=1500,
        ws_stale_ms=3000,
    )
    assert settings.arb_mode == "paper"


def test_load_settings_defaults_to_paper(monkeypatch) -> None:
    monkeypatch.delenv("ARB_MODE", raising=False)
    settings = load_settings()
    assert settings.arb_mode == "paper"


def test_live_allowed_false_without_allow_live(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ARB_MODE", "live")
    assert not (tmp_path / "ALLOW_LIVE").exists()
    assert live_allowed(tmp_path) is False


def test_live_allowed_false_when_paper_even_with_allow_live(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ARB_MODE", "paper")
    (tmp_path / "ALLOW_LIVE").write_text(date.today().isoformat() + "\n", encoding="utf-8")
    assert live_allowed(tmp_path) is False


def test_live_allowed_false_when_allow_live_date_is_stale(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ARB_MODE", "live")
    (tmp_path / "ALLOW_LIVE").write_text("1999-01-01\n", encoding="utf-8")
    assert live_allowed(tmp_path) is False


def test_config_module_does_not_ship_allow_live() -> None:
    project_root = Path(config_mod.__file__).resolve().parents[2]
    assert not (project_root / "ALLOW_LIVE").exists()
