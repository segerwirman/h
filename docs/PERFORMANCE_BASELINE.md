# Performance Baseline

Measure cold and warm paths separately. Do not claim network, browser launch, provider calls, or dependency installation are instant.

| Helper class | Cold path | Warm path | Metric |
|---|---|---|---|
| Weather browser open | Browser launch/network | TTL cache hit | p50/p95 ms |
| Browser automation | Profile/process startup | persistent resource pool | p50/p95 ms |
| Desktop action | OS/accessibility lookup | leased action | p50/p95 ms |
| MCP | Process startup | connected server | p50/p95 ms |
| Memory search | SQLite open | WAL/FTS query | p50/p95 ms |

Run `python scripts/benchmark_helpers.py` only in a controlled local environment. Record hardware, sample size, cold/warm definition, p50, p95, and failures.
