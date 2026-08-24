# Task: write a how-this-bot-works guide and add it to the repo

Repo: /workspace/polymarket-arb-team
Public origin: https://github.com/Cryptokid92/polymarket-arb-team
Paper only. Never create ALLOW_LIVE. Never place live orders. Never commit .env, secrets, data/, sqlite, JSONL, uv.lock.

## What to write
A clear human guide: how this completeness-arb bot actually works. Not a changelog. Not a task list.

Put it at: docs/guide/how-this-bot-works.md
Also add a short index docs/guide/README.md
Link it from README.md (one line under Plans and debug reports is fine).
Copy this implementer prompt to docs/plans/grok-how-this-bot-works.md (Nikolai wants all Grok/Cursor plans in docs/plans/).

## Read first (do not invent)
AGENTS.md, PLAN.md, README.md, src/arb/app.py, hunter.py, risk.py, fee_agent.py, fees.py, books.py, killswitch.py, state.py, executor.py, config.py, scripts/paper_run.py, scripts/paper_ui.py, scripts/report_paper.py.

## Cover, in plain language
1. What completeness arb is here: same-market binary YES+NO asks, buy both when sum < $1, size by walked ask depth (not mid).
2. What it is not: not live, not financial advice, no guaranteed PnL, no LLM on the hot path, official polymarket-client only.
3. Pipeline: list markets → v1 universe filter → books (REST then WS/poll) → hunt → risk → fees/intent → paper executor. In-process specialists.
4. Fees: C * feeRate * p * (1-p). Makers pay 0. Rebates not in EV. Taker needs EV after fees + 0.005/share.
5. Risk refuses: halt, not binary, delay, neg-risk, stale, max gap, max pairs, daily loss, uncompletable.
6. Kill switch: daily loss, HALT file, WS silence (last stream/poll receive, not book ts), ≥3 hedge incidents/hour. No auto-resume.
7. Paper logs + UI at 127.0.0.1:8765. How to run paper_run / paper_ui / report_paper.
8. Live gate (document only): ARB_MODE=live AND human ALLOW_LIVE with today's date. Task 12 not built. Do not enable live.
9. Known paper-run issues from docs/debug-reports (hour-1 halt wiring, hour-2 WS min_order_size None). Be honest.

Write for Nikolai: short sentences, no hype, no "certainly".

## Git
Branch: docs/how-this-bot-works (not main).
Commit the guide + README link + plan copy.
Push the branch if remotes work. Open a PR if gh works. Do not merge. Do not force-push.

Report: path, commit hash, PR URL if any.
