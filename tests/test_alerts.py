"""Local paper alerts. No live client."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from arb.alerts import alert_record
from arb.fees import net_edge_maker
from arb.hunter import hunt
from arb.books import BookStore
from arb.messages import Intent
from arb.money import d

FIXTURES = Path(__file__).parent / "fixtures" / "books"


def test_alert_record_has_vwaps_and_ev() -> None:
    payload = (FIXTURES / "gap_3c.json").read_text(encoding="utf-8")
    import json

    raw = json.loads(payload)
    store = BookStore()
    yes = store.apply_snapshot(raw["yes"])
    no = store.apply_snapshot(raw["no"])
    gap = hunt(yes, no, d("0.01"), yes.min_order_size, d("80"), now_ms=1000)
    assert gap is not None
    intent = Intent(
        gap=gap,
        path="maker_gtc",
        size=gap.fillable_shares,
        yes_limit=gap.yes_vwap,
        no_limit=gap.no_vwap,
        expected_net_edge=net_edge_maker(gap.raw_edge, gap.fillable_shares),
        taker_fee_yes=d("0"),
        taker_fee_no=d("0"),
    )
    row = alert_record(intent, 2000, outcome="filled")
    assert row["ts_ms"] == 2000
    assert row["path"] == "maker_gtc"
    assert row["raw_edge"] == "0.03"
    assert row["yes_vwap"] == "0.55"
    assert row["no_vwap"] == "0.42"
    assert row["outcome"] == "filled"
    assert "AsyncSecureClient" not in inspect.getsource(alert_record)


def test_alerts_module_has_no_secure_client() -> None:
    source = Path("src/arb/alerts.py").read_text(encoding="utf-8")
    assert "AsyncSecureClient" not in source
    assert "from polymarket" not in source
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "AsyncSecureClient"
