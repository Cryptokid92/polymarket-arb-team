"""Paper full-set stats payload. Decimal serializes as string; no floats."""

from __future__ import annotations

import json
from decimal import Decimal

from arb.fullset_stats import FullSetRunStats, fullset_stats_payload


def test_default_payload_closest_set_sum_is_none() -> None:
    payload = fullset_stats_payload(FullSetRunStats())
    assert payload["closest_set_sum"] is None
    assert payload["fullset_events"] == 0
    assert payload["fullset_gaps"] == 0
    assert payload["fullset_fills"] == 0


def test_decimal_closest_set_sum_serializes_to_string_not_float() -> None:
    payload = fullset_stats_payload(FullSetRunStats(closest_set_sum=Decimal("0.98")))
    assert payload["closest_set_sum"] == "0.98"
    assert type(payload["closest_set_sum"]) is str
    assert type(payload["closest_set_sum"]) is not float


def test_json_dumps_payload_works() -> None:
    payload = fullset_stats_payload(
        FullSetRunStats(
            fullset_events=1,
            fullset_gaps=2,
            fullset_fills=3,
            closest_set_sum=Decimal("0.98"),
        )
    )
    dumped = json.dumps(payload)
    loaded = json.loads(dumped)
    assert loaded["fullset_events"] == 1
    assert loaded["fullset_gaps"] == 2
    assert loaded["fullset_fills"] == 3
    assert loaded["closest_set_sum"] == "0.98"


def test_payload_values_are_not_float() -> None:
    payloads = (
        fullset_stats_payload(FullSetRunStats()),
        fullset_stats_payload(FullSetRunStats(closest_set_sum=Decimal("0.98"))),
    )
    for payload in payloads:
        for value in payload.values():
            assert type(value) is not float
        loaded = json.loads(json.dumps(payload))
        for value in loaded.values():
            assert type(value) is not float
