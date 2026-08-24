# Task: run current main and report what works / what does not

Repo: /workspace/polymarket-arb-team
Public: https://github.com/Cryptokid92/polymarket-arb-team
Paper only. Never create ALLOW_LIVE. Never place live orders. Never commit .env, secrets, data/, sqlite, JSONL, uv.lock.

## Do
1. git fetch && stay on or pull origin/main. Record HEAD SHA.
2. Run `uv run pytest -q`. Record pass/fail count.
3. Inspect the live paper hour if present: processes `scripts/paper_run.py` and `scripts/paper_ui.py`, `data/paper-hour5/` (stats.json, meta in state.sqlite, reject reasons, whether halted / halt_reason). Do not delete those logs.
4. If no runner is alive, you MAY start one paper-only: `ARB_MODE=paper uv run python scripts/paper_run.py --once --max-markets 80 --data-dir data/paper-grok-status`. Never --place-orders. Never live.
5. Read AGENTS.md, docs/guide/how-this-bot-works.md, docs/debug-reports/ (halt, decimal crash, quiet ws_stale). Be honest. Do not invent numbers.

## Write
`docs/debug-reports/2026-08-24-grok-main-status.md`

Plain language for Nikolai. Two sections: Working. Not working / still broken. Include:
- SHA, pytest result
- Paper pipeline pieces that are real (list, universe filter, fees, hunter, risk, paper executor, UI)
- Live paper counts if you have them (listed / universe / gaps / intents / halt)
- Known leftover: Task 12 dark, geoblock on this host, almost all markets neg_risk so few binary markets, no gaps seen yet
- Do not claim PnL or that live works

Copy this prompt to `docs/plans/grok-main-status.md`. Add a row to `docs/debug-reports/README.md` and `docs/plans/README.md`.

## Git
Branch `docs/grok-main-status`. Commit only the markdown. Push and open a PR if gh works. Do not merge. Do not force-push.

Report: SHA, pytest, paper facts, PR URL.
