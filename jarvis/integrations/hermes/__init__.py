"""Hermes Agent integration — JARVIS gains Hermes' full tool ecosystem.

Tiering (latency contract):
  Tier 2  bridge.send_direct()   — no-LLM message send, ~1s
  Tier 3  async_dispatch()       — full agent tasks, instant ACK + async result

The bridge NEVER blocks the voice pipeline: tier-3 always acks first, and a
circuit breaker keeps a dead Hermes install from adding latency to anything.
"""
from jarvis.integrations.hermes.bridge import HermesBridge          # noqa: F401
from jarvis.integrations.hermes.async_dispatch import dispatch_async  # noqa: F401
