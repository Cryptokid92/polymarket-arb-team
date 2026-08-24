from __future__ import annotations

import inspect
from datetime import date
from pathlib import Path
from typing import Any

import arb.preflight as preflight_mod
from arb.config import Settings
from arb.money import d
from arb.preflight import run_preflight


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


def test_paper_preflight_ok_without_secrets(tmp_path: Path) -> None:
    settings = _settings(arb_mode="paper", private_key=None, wallet_address=None)
    result = run_preflight(settings, tmp_path)
    assert result.ok is True
    assert result.reason is None


def test_live_preflight_without_allow_live_fails(tmp_path: Path) -> None:
    settings = _settings(arb_mode="live", private_key=None, wallet_address=None)
    result = run_preflight(settings, tmp_path)
    assert result.ok is False
    assert result.reason is not None
    assert "ALLOW_LIVE" in result.reason
    assert not (tmp_path / "ALLOW_LIVE").exists()


def test_live_preflight_blocked_geoblock_refuses(tmp_path: Path) -> None:
    (tmp_path / "ALLOW_LIVE").write_text(date.today().isoformat() + "\n", encoding="utf-8")
    settings = _settings(
        arb_mode="live",
        private_key="0xnot-a-real-key",
        wallet_address="0xabc",
    )
    result = run_preflight(
        settings,
        tmp_path,
        geoblock_fetcher=lambda: {"blocked": True},
    )
    assert result.ok is False
    assert result.reason is not None
    assert "geoblock" in result.reason.lower()


def test_live_preflight_injected_unblocked_ok(tmp_path: Path) -> None:
    (tmp_path / "ALLOW_LIVE").write_text(date.today().isoformat() + "\n", encoding="utf-8")
    settings = _settings(
        arb_mode="live",
        private_key="0xnot-a-real-key",
        wallet_address="0xabc",
    )
    result = run_preflight(
        settings,
        tmp_path,
        geoblock_fetcher=lambda: {"blocked": False},
    )
    assert result.ok is True


def test_preflight_source_has_no_network_client() -> None:
    source = inspect.getsource(run_preflight)
    lowered = source.lower()
    assert "urllib" not in lowered
    assert "requests" not in lowered
    assert "httpx" not in lowered
    assert "asyncsecureclient" not in lowered
    assert "urlopen" not in lowered
    module = inspect.getsource(preflight_mod)
    module_l = module.lower()
    assert "urllib" not in module_l
    assert "requests" not in module_l
    assert "httpx" not in module_l
    assert "asyncsecureclient" not in module_l
