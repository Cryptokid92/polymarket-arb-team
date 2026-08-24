# Hour-5 UI stale while runner is alive

Date: 2026-08-24
Code: main after PR #17 (`e761264`)
Data: hour-5 paper dir (gitignored)

## What happened
1. `paper_run` process was up. Not halted. No `HALT` file.
2. `stats.json` was still being rewritten (counts / mtime moving).
3. Read-only UI at `127.0.0.1:8765` showed **stale** and **last event 11m ago**.
4. Nikolai: the UI must reflect the runner.

## Cause
`summarize_dashboard` takes the newest JSONL `ts_ms` first. Opening universe scan writes `rejects.jsonl` (often `neg_risk`) and then goes quiet on gaps/intents.

`stats.json` is rewritten on each `consider()` / snapshot. That mtime is collected with the other log files, but it is ignored whenever any JSONL row has `ts_ms`. Eleven minutes of live stats rewrites still look like the last reject.

Stale UI status is a dashboard clock. It must not invent a kill-switch halt.

## Fix
Count `stats.json` mtime and `heartbeat_ms` from `write_paper_stats` as events. Last activity is the max of JSONL timestamps, stats heartbeat, and log mtimes. A rewrite or heartbeat within seconds → `running`. Halt stays `HALT` / sqlite only.

See [cursor-ui-follows-runner.md](../plans/cursor-ui-follows-runner.md).
