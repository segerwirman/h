# Phase 18 Ecosystem Extension Safety Plan

**Goal:** Close the plugin lifecycle gap so persistent local-plugin activation is validated before it can contribute capabilities, while preserving trusted-local/no-auto-import behavior.

**Architecture:** `jarvis.plugins.manifest` remains the single validation authority. `PluginRuntime.activate()` calls it before assigning tools or persisting a manifest. `PluginRuntime._load()` reuses the same activation path, so stale/corrupt saved manifests become inert. The runtime stores no plugin source, payload, or secret; it only persists validated manifests already supplied by the desktop-local plugin workflow.

**Scope:** This first Phase 18 slice hardens the existing plugin parity foundation. It does not create a marketplace, auto-download/install code, import plugin entrypoints, change release flags, or expose plugins to a remote gateway.

## TDD slices

1. Add a red test that an invalid manifest cannot reserve a tool or be persisted; implement a single call to `manifest.validate()` in `PluginRuntime.activate()`.
2. Add a red restore test with one invalid and one valid persisted manifest; ensure valid contributions restore while invalid ones remain inactive.
3. Update existing runtime fixtures to use complete trusted-local manifests accepted by the existing validator.
4. Document local-only activation and failure semantics.
5. Verify focused plugin suites, full suite, frozen manifest, and diff integrity.

## Files

- Modify: `jarvis/plugins/runtime.py`
- Modify: `tests/test_plugin_runtime.py`
- Modify: `docs/OPERATIONS_RUNBOOK.md`
- Create: `docs/archive/plans/2026-07-23_000000-phase18-ecosystem-extension-safety.md`

## Verification

```bash
unset PYTHONPATH; python -m pytest -q tests/test_plugins.py tests/test_plugin_permissions.py tests/test_plugin_runtime.py
unset PYTHONPATH; python -m pytest -q
python scripts/verify_frozen.py
git diff --check
```
