"""Fase 39: config.yaml dan consumer production harus punya kontrak dua arah."""
from __future__ import annotations

from pathlib import Path

from jarvis.core import config


def _write_source(root: Path, relative: str, source: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def test_literal_section_secret_and_alias_reads_are_matched(tmp_path):
    from jarvis.core import config_contract

    source = _write_source(
        tmp_path,
        "jarvis/example.py",
        """
from jarvis.core import config as cfg

cfg.section("block")
cfg.get("list_value", [])
cfg.get("null_value")
cfg.get("empty_map", {})
cfg.secret("JARVIS_TOKEN", "secret_name")
cfg.secret("ENV_ONLY")
cfg.get("missing.read", False)

from jarvis.core import config

def unrelated(config):
    return config.get("not.a.jarvis.config.path")
""",
    )
    data = {
        "block": {"one": 1, "nested": {"two": 2}},
        "list_value": [1, 2],
        "null_value": None,
        "empty_map": {},
        "secret_name": "must-never-appear-in-report",
        "dead": "also-secret-looking",
    }

    report = config_contract.analyze(data, tmp_path, source_paths=[source])

    assert set(report.declared_leaves) == {
        "block.one",
        "block.nested.two",
        "dead",
        "empty_map",
        "list_value",
        "null_value",
        "secret_name",
    }
    assert set(report.dead_keys) == {"dead"}
    assert set(report.undeclared_reads) == {"missing.read"}
    assert "JARVIS_TOKEN" not in report.exact_reads
    assert "ENV_ONLY" not in report.unresolved_dynamic
    assert "not.a.jarvis.config.path" not in report.exact_reads
    assert not report.unresolved_dynamic
    assert not report.scan_errors

    rendered = " ".join(config_contract.issues(report))
    assert "also-secret-looking" not in rendered
    assert "must-never-appear-in-report" not in rendered


def test_function_local_config_import_is_scoped(tmp_path):
    from jarvis.core import config_contract

    source = _write_source(
        tmp_path,
        "jarvis/example.py",
        """
def actual_read():
    from jarvis.core import config
    return config.get("local.import.path")

def unrelated(config):
    return config.get("not.module.config")
""",
    )

    report = config_contract.analyze(
        {"local": {"import": {"path": True}}},
        tmp_path,
        source_paths=[source],
    )

    assert set(report.exact_reads) == {"local.import.path"}
    assert not report.dead_keys
    assert not report.undeclared_reads
    assert not report.unresolved_dynamic


def test_import_after_read_does_not_mark_preimport_call_as_config(tmp_path):
    from jarvis.core import config_contract

    source = _write_source(
        tmp_path,
        "jarvis/example.py",
        """
def target(config):
    config.get("not.module.config")
    from jarvis.core import config
    return config.get("local.import.path")
""",
    )

    report = config_contract.analyze(
        {"local": {"import": {"path": True}}},
        tmp_path,
        source_paths=[source],
    )

    assert set(report.exact_reads) == {"local.import.path"}
    assert not report.dead_keys
    assert not report.undeclared_reads
    assert not report.unresolved_dynamic


def test_module_import_after_read_does_not_mark_preimport_call_as_config(
    tmp_path,
):
    from jarvis.core import config_contract

    source = _write_source(
        tmp_path,
        "jarvis/example.py",
        """
class Unrelated:
    def get(self, path):
        return path

config = Unrelated()
config.get("not.module.config")
from jarvis.core import config
config.get("module.path")
""",
    )

    report = config_contract.analyze(
        {"module": {"path": True}},
        tmp_path,
        source_paths=[source],
    )

    assert set(report.exact_reads) == {"module.path"}
    assert not report.dead_keys
    assert not report.undeclared_reads
    assert not report.unresolved_dynamic


def test_module_assignment_after_import_stops_alias(tmp_path):
    from jarvis.core import config_contract

    source = _write_source(
        tmp_path,
        "jarvis/example.py",
        """
from jarvis.core import config
config.get("actual.path")
config = object()
config.get("not.module.config")
""",
    )

    report = config_contract.analyze(
        {"actual": {"path": True}},
        tmp_path,
        source_paths=[source],
    )

    assert set(report.exact_reads) == {"actual.path"}
    assert not report.dead_keys
    assert not report.undeclared_reads
    assert not report.unresolved_dynamic


def test_assignment_after_local_import_stops_alias_at_assignment(tmp_path):
    from jarvis.core import config_contract

    source = _write_source(
        tmp_path,
        "jarvis/example.py",
        """
def target():
    from jarvis.core import config
    config.get("actual.path")
    config = object()
    config.get("not.module.config")
""",
    )

    report = config_contract.analyze(
        {"actual": {"path": True}},
        tmp_path,
        source_paths=[source],
    )

    assert set(report.exact_reads) == {"actual.path"}
    assert not report.dead_keys
    assert not report.undeclared_reads
    assert not report.unresolved_dynamic


def test_local_assignment_shadows_module_alias_before_assignment(
    tmp_path,
):
    from jarvis.core import config_contract

    source = _write_source(
        tmp_path,
        "jarvis/example.py",
        """
from jarvis.core import config

def target():
    config.get("not.module.before.assignment")
    config = object()
    config.get("not.module.after.assignment")
""",
    )

    report = config_contract.analyze(
        {"declared": True},
        tmp_path,
        source_paths=[source],
    )

    assert not report.exact_reads
    assert report.dead_keys == ("declared",)
    assert not report.undeclared_reads
    assert not report.unresolved_dynamic


def test_non_config_import_after_config_import_stops_alias(tmp_path):
    from jarvis.core import config_contract

    source = _write_source(
        tmp_path,
        "jarvis/example.py",
        """
from jarvis.core import config
config.get("actual.path")
from unrelated import config
config.get("not.module.config")
""",
    )

    report = config_contract.analyze(
        {"actual": {"path": True}},
        tmp_path,
        source_paths=[source],
    )

    assert set(report.exact_reads) == {"actual.path"}
    assert not report.dead_keys
    assert not report.undeclared_reads
    assert not report.unresolved_dynamic


def test_keyword_paths_and_module_scope_do_not_hide_real_reads(tmp_path):
    from jarvis.core import config_contract

    source = _write_source(
        tmp_path,
        "jarvis/example.py",
        """
from jarvis.core import config

config.get(path="module.path")

def unrelated(config):
    return config.get("not.module.config")

def actual_read():
    return config.secret("TOKEN", config_path="secret.path")
""",
    )
    data = {"module": {"path": True}, "secret": {"path": "hidden"}}

    report = config_contract.analyze(data, tmp_path, source_paths=[source])

    assert set(report.exact_reads) == {"module.path", "secret.path"}
    assert not report.dead_keys
    assert not report.undeclared_reads
    assert not report.unresolved_dynamic


def test_outer_local_import_applies_to_nested_closure(tmp_path):
    from jarvis.core import config_contract

    source = _write_source(
        tmp_path,
        "jarvis/example.py",
        """
def outer():
    def nested():
        return config.get("closure.path")

    from jarvis.core import config
    return nested
""",
    )

    report = config_contract.analyze(
        {"closure": {"path": True}},
        tmp_path,
        source_paths=[source],
    )

    assert set(report.exact_reads) == {"closure.path"}
    assert not report.dead_keys
    assert not report.undeclared_reads
    assert not report.unresolved_dynamic


def test_outer_scope_constants_and_shadowing_propagate_to_closures(tmp_path):
    from jarvis.core import config_contract

    source = _write_source(
        tmp_path,
        "jarvis/example.py",
        """
from jarvis.core import config

MODULE_PATH = "module.path"

def reads_outer_constant():
    local_path = "local.path"

    def nested():
        config.get(local_path)
        config.get(MODULE_PATH)

    return nested

def shadowed(config):
    def nested():
        return config.get("not.jarvis.config")
    return nested
""",
    )
    data = {"module": {"path": True}, "local": {"path": True}}

    report = config_contract.analyze(data, tmp_path, source_paths=[source])

    assert set(report.exact_reads) == {"local.path", "module.path"}
    assert not report.dead_keys
    assert not report.undeclared_reads
    assert not report.unresolved_dynamic


def test_function_parameter_does_not_inherit_same_named_module_constant(tmp_path):
    from jarvis.core import config_contract

    source = _write_source(
        tmp_path,
        "jarvis/example.py",
        """
from jarvis.core import config

PATH = "module.path"

def actual_read():
    return config.get(PATH)

def unrelated(PATH):
    return config.get(PATH)
""",
    )

    report = config_contract.analyze(
        {"module": {"path": True}},
        tmp_path,
        source_paths=[source],
    )

    assert set(report.exact_reads) == {"module.path"}
    assert len(report.unresolved_dynamic) == 1
    assert report.unresolved_dynamic[0].endswith(" <dynamic>")
    assert not report.dead_keys
    assert not report.undeclared_reads


def test_nested_closure_does_not_revive_outer_shadowed_alias(tmp_path):
    from jarvis.core import config_contract

    source = _write_source(
        tmp_path,
        "jarvis/example.py",
        """
from jarvis.core import config

def outer(config):
    def nested():
        return config.get("not.jarvis.config")
    return nested
""",
    )

    report = config_contract.analyze(
        {"declared": True},
        tmp_path,
        source_paths=[source],
    )

    assert not report.exact_reads
    assert report.dead_keys == ("declared",)
    assert not report.undeclared_reads
    assert not report.unresolved_dynamic


def test_nested_closure_inherits_unrelated_module_config_alias(tmp_path):
    from jarvis.core import config_contract

    source = _write_source(
        tmp_path,
        "jarvis/example.py",
        """
from jarvis.core import config

def outer(other):
    def nested():
        return config.get("closure.path")
    return nested
""",
    )

    report = config_contract.analyze(
        {"closure": {"path": True}},
        tmp_path,
        source_paths=[source],
    )

    assert set(report.exact_reads) == {"closure.path"}
    assert not report.dead_keys
    assert not report.undeclared_reads
    assert not report.unresolved_dynamic


def test_direct_module_import_without_alias_uses_bound_name(tmp_path):
    from jarvis.core import config_contract

    source = _write_source(
        tmp_path,
        "jarvis/example.py",
        """
import jarvis.core.config

jarvis.core.config.get("fully.qualified")
""",
    )

    report = config_contract.analyze(
        {"fully": {"qualified": True}},
        tmp_path,
        source_paths=[source],
    )

    assert set(report.exact_reads) == {"fully.qualified"}
    assert not report.dead_keys
    assert not report.undeclared_reads
    assert not report.unresolved_dynamic


def test_fully_qualified_import_root_shadowing_is_respected(tmp_path):
    from jarvis.core import config_contract

    source = _write_source(
        tmp_path,
        "jarvis/example.py",
        """
import jarvis.core.config

def unrelated(jarvis):
    return jarvis.core.config.get("not.jarvis.config")
""",
    )

    report = config_contract.analyze(
        {"declared": True},
        tmp_path,
        source_paths=[source],
    )

    assert not report.exact_reads
    assert report.dead_keys == ("declared",)
    assert not report.undeclared_reads
    assert not report.unresolved_dynamic


def test_known_dynamic_family_is_finite_and_unknown_dynamic_is_visible(tmp_path):
    from jarvis.core import config_contract

    known = _write_source(
        tmp_path,
        "jarvis/agent/auxiliary.py",
        """
from jarvis.core import config

def slot_config(task):
    provider = config.get(f"auxiliary.{task}.provider", "auto")
    model = config.get(f"auxiliary.{task}.model", "")
    return provider, model
""",
    )
    unknown = _write_source(
        tmp_path,
        "jarvis/example.py",
        """
from jarvis.core import config

def enabled(name):
    return config.get(f"feature.{name}.enabled", False)
""",
    )
    data = {
        "auxiliary": {
            "vision": {"provider": "auto", "model": ""},
            "embedding": {"provider": "auto", "model": ""},
            "not_a_slot": {"provider": "auto"},
        },
    }

    report = config_contract.analyze(
        data,
        tmp_path,
        source_paths=[known, unknown],
    )

    assert "auxiliary.vision.provider" in report.exact_reads
    assert "auxiliary.vision.model" in report.exact_reads
    assert "auxiliary.embedding.model" in report.exact_reads
    assert set(report.dead_keys) == {"auxiliary.not_a_slot.provider"}
    assert len(report.unresolved_dynamic) == 1
    assert "feature.{name}.enabled" in report.unresolved_dynamic[0]


def test_conditional_path_assignments_are_resolved_without_file_exception(tmp_path):
    from jarvis.core import config_contract

    source = _write_source(
        tmp_path,
        "jarvis/example.py",
        """
from jarvis.core import config

def target(docked):
    path = "active.diameter" if docked else "empty.diameter"
    return config.get(path, 300)

def unrelated(path):
    return config.get(path, 0)
""",
    )
    data = {"active": {"diameter": 200}, "empty": {"diameter": 300}}

    report = config_contract.analyze(data, tmp_path, source_paths=[source])

    assert set(report.exact_reads) == {"active.diameter", "empty.diameter"}
    assert not report.dead_keys
    assert len(report.unresolved_dynamic) == 1
    assert "jarvis/example.py:" in report.unresolved_dynamic[0]
    assert report.unresolved_dynamic[0].endswith(" <dynamic>")


def test_dynamic_function_that_is_not_config_wrapper_stays_unresolved(tmp_path):
    from jarvis.core import config_contract

    source = _write_source(
        tmp_path,
        "jarvis/example.py",
        """
from jarvis.core import config

def section(path):
    return config.get(path, {})
""",
    )

    report = config_contract.analyze(
        {"declared": True},
        tmp_path,
        source_paths=[source],
    )

    assert report.dead_keys == ("declared",)
    assert len(report.unresolved_dynamic) == 1
    assert "jarvis/example.py:" in report.unresolved_dynamic[0]
    assert report.unresolved_dynamic[0].endswith(" <dynamic>")


def test_config_module_internal_get_is_not_reported_dynamic(tmp_path):
    from jarvis.core import config_contract

    source = _write_source(
        tmp_path,
        "jarvis/core/config.py",
        """
def get(path, default=None):
    return default

def section(path):
    return get(path, {})

def secret(env_name, config_path="", default=""):
    return get(config_path, default) if config_path else default
""",
    )

    report = config_contract.analyze(
        {"declared": True},
        tmp_path,
        source_paths=[source],
    )

    assert report.dead_keys == ("declared",)
    assert not report.unresolved_dynamic


def test_config_module_validate_literal_reads_still_count(tmp_path):
    from jarvis.core import config_contract

    source = _write_source(
        tmp_path,
        "jarvis/core/config.py",
        """
def get(path, default=None):
    return default

def validate():
    return get("runtime.toggle", False)
""",
    )

    report = config_contract.analyze(
        {"runtime": {"toggle": True}},
        tmp_path,
        source_paths=[source],
    )

    assert set(report.exact_reads) == {"runtime.toggle"}
    assert not report.dead_keys
    assert not report.undeclared_reads
    assert not report.unresolved_dynamic


def test_settings_virtual_field_is_not_a_config_read(tmp_path):
    from jarvis.core import config_contract

    source = _write_source(
        tmp_path,
        "jarvis/core/settings_service.py",
        """
from jarvis.core import config

def sections():
    return [{"fields": [
        {"key": "real.path"},
        {"key": "security.secrets_backend"},
    ]}]

def unrelated_metadata():
    return {"key": "not.a.settings.field"}

def resolve(fields):
    for field in fields:
        if field["key"] == "security.secrets_backend":
            value = "runtime"
        else:
            value = config.get(field["key"], "")
""",
    )

    report = config_contract.analyze(
        {"real": {"path": True}},
        tmp_path,
        source_paths=[source],
    )

    assert set(report.exact_reads) == {"real.path"}
    assert "not.a.settings.field" not in report.exact_reads
    assert not report.dead_keys
    assert not report.undeclared_reads
    assert not report.unresolved_dynamic


def test_unknown_dynamic_settings_field_is_visible(tmp_path):
    from jarvis.core import config_contract

    source = _write_source(
        tmp_path,
        "jarvis/core/settings_service.py",
        """
from jarvis.core import config

def sections(name):
    return [{"fields": [{"key": f"feature.{name}.enabled"}]}]

def resolve(fields):
    for field in fields:
        config.get(field["key"], "")
""",
    )

    report = config_contract.analyze(
        {"declared": True},
        tmp_path,
        source_paths=[source],
    )

    assert report.dead_keys == ("declared",)
    assert not report.exact_reads
    assert len(report.unresolved_dynamic) == 1
    assert "settings_key:feature.{name}.enabled" in (
        report.unresolved_dynamic[0]
    )


def test_environment_fallback_uses_exact_config_contract(tmp_path):
    from jarvis.core import config_contract

    client = _write_source(
        tmp_path,
        "jarvis/integrations/relay/client.py",
        """
import os
from jarvis.core import config

TIMEOUT = os.environ.get("RELAY_REQUEST_TIMEOUT_SECONDS", "") or config.get(
    "relay.request_timeout_seconds", 10
)
""",
    )
    webhook = _write_source(
        tmp_path,
        "jarvis/integrations/relay/webhook.py",
        """
import os
from jarvis.core import config

PORT = os.environ.get("RELAY_WEBHOOK_PORT", "") or config.get(
    "relay.webhook_port", 8791
)
""",
    )

    report = config_contract.analyze(
        {
            "relay": {
                "request_timeout_seconds": 10,
                "webhook_port": 8791,
            },
        },
        tmp_path,
        source_paths=[client, webhook],
    )

    assert set(report.exact_reads) == {
        "relay.request_timeout_seconds",
        "relay.webhook_port",
    }
    assert not report.dead_keys
    assert not report.undeclared_reads
    assert not report.unresolved_dynamic


def test_unknown_dynamic_wrapper_caller_is_visible(tmp_path):
    from jarvis.core import config_contract

    source = _write_source(
        tmp_path,
        "jarvis/agent/interaction.py",
        """
from jarvis.core import config

def _int_config(key, default):
    return config.get(key, default)

def unexpected(key):
    return _int_config(key, 1)
""",
    )

    report = config_contract.analyze(
        {"declared": True},
        tmp_path,
        source_paths=[source],
    )

    assert report.dead_keys == ("declared",)
    assert len(report.unresolved_dynamic) == 1
    assert "wrapper:_int_config" in report.unresolved_dynamic[0]


def test_wrapper_parameter_shadow_does_not_invent_config_read(tmp_path):
    from jarvis.core import config_contract

    source = _write_source(
        tmp_path,
        "jarvis/agent/interaction.py",
        """
from jarvis.core import config

def _int_config(key, default):
    return config.get(key, default)

def unrelated(_int_config):
    return _int_config("not.config.parameter", 1)
""",
    )

    report = config_contract.analyze(
        {"declared": True}, tmp_path, source_paths=[source]
    )

    assert not report.exact_reads
    assert report.dead_keys == ("declared",)
    assert not report.undeclared_reads
    assert not report.unresolved_dynamic


def test_wrapper_local_assignment_shadows_calls_before_and_after_it(tmp_path):
    from jarvis.core import config_contract

    source = _write_source(
        tmp_path,
        "jarvis/agent/interaction.py",
        """
from jarvis.core import config

def _int_config(key, default):
    return config.get(key, default)

def unrelated():
    _int_config("not.config.before", 1)
    _int_config = lambda key, default: default
    return _int_config("not.config.after", 1)
""",
    )

    report = config_contract.analyze(
        {"declared": True}, tmp_path, source_paths=[source]
    )

    assert not report.exact_reads
    assert report.dead_keys == ("declared",)
    assert not report.undeclared_reads
    assert not report.unresolved_dynamic


def test_wrapper_resolution_propagates_through_nested_closures(tmp_path):
    from jarvis.core import config_contract

    source = _write_source(
        tmp_path,
        "jarvis/agent/interaction.py",
        """
from jarvis.core import config

def _int_config(key, default):
    return config.get(key, default)

def actual_outer():
    def nested():
        return _int_config("actual.closure", 1)
    return nested

def shadowed_outer(_int_config):
    def nested():
        return _int_config("not.config.closure", 1)
    return nested
""",
    )

    report = config_contract.analyze(
        {"actual": {"closure": True}}, tmp_path, source_paths=[source]
    )

    assert set(report.exact_reads) == {"actual.closure"}
    assert not report.dead_keys
    assert not report.undeclared_reads
    assert not report.unresolved_dynamic


def test_local_helper_definition_shadows_registered_wrapper(tmp_path):
    from jarvis.core import config_contract

    source = _write_source(
        tmp_path,
        "jarvis/agent/interaction.py",
        """
from jarvis.core import config

def _int_config(key, default):
    return config.get(key, default)

def unrelated():
    def _int_config(key, default):
        return default
    return _int_config("not.config.helper", 1)
""",
    )

    report = config_contract.analyze(
        {"declared": True}, tmp_path, source_paths=[source]
    )

    assert not report.exact_reads
    assert report.dead_keys == ("declared",)
    assert not report.undeclared_reads
    assert not report.unresolved_dynamic


def test_replacement_import_stops_registered_wrapper_resolution(tmp_path):
    from jarvis.core import config_contract

    source = _write_source(
        tmp_path,
        "jarvis/agent/interaction.py",
        """
from jarvis.core import config

def _int_config(key, default):
    return config.get(key, default)

_int_config("actual.before.import", 1)
from unrelated import _int_config
_int_config("not.config.after.import", 1)
""",
    )

    report = config_contract.analyze(
        {"actual": {"before": {"import": True}}},
        tmp_path,
        source_paths=[source],
    )

    assert set(report.exact_reads) == {"actual.before.import"}
    assert not report.dead_keys
    assert not report.undeclared_reads
    assert not report.unresolved_dynamic


def test_finite_dynamic_contract_is_bound_to_expected_function(tmp_path):
    from jarvis.core import config_contract

    source = _write_source(
        tmp_path,
        "jarvis/agent/auxiliary.py",
        """
from jarvis.core import config

def unrelated(task):
    return config.get(f"auxiliary.{task}.provider", "auto")
""",
    )

    report = config_contract.analyze(
        {"auxiliary": {"vision": {"provider": "auto"}}},
        tmp_path,
        source_paths=[source],
    )

    assert report.dead_keys == ("auxiliary.vision.provider",)
    assert len(report.unresolved_dynamic) == 1
    assert "auxiliary.{task}.provider" in report.unresolved_dynamic[0]


def test_exact_dormant_source_exclusion_does_not_hide_neighbors(tmp_path):
    from jarvis.core import config_contract

    dormant = _write_source(
        tmp_path,
        "jarvis/browser/agent_view.py",
        """
from jarvis.core import config
config.get("retired.key")
""",
    )
    active = _write_source(
        tmp_path,
        "jarvis/browser/active.py",
        """
from jarvis.core import config
config.get("active.key")
""",
    )
    assert dormant.exists() and active.exists()

    report = config_contract.analyze(
        {"active": {"key": True}},
        tmp_path,
    )

    assert set(report.exact_reads) == {"active.key"}
    assert not report.dead_keys
    assert not report.undeclared_reads


def test_explicit_empty_source_list_is_a_real_empty_scan(tmp_path):
    from jarvis.core import config_contract

    report = config_contract.analyze(
        {"declared": True},
        tmp_path,
        source_paths=[],
    )

    assert report.skipped_reason == ""
    assert report.dead_keys == ("declared",)
    assert not report.undeclared_reads
    assert not report.scan_errors


def test_source_unavailable_is_skipped_without_false_drift(tmp_path):
    from jarvis.core import config_contract

    missing = tmp_path / "not-installed-source"
    report = config_contract.analyze({"declared": True}, missing)

    assert report.skipped_reason == "source_unavailable"
    assert not report.dead_keys
    assert not report.undeclared_reads
    assert not report.scan_errors


def test_config_validate_skips_contract_scan_when_frozen(tmp_path, monkeypatch):
    from jarvis.core import config_contract

    cfg = tmp_path / "config.yaml"
    cfg.write_text("declared: true\n", encoding="utf-8")
    called = False

    def fail_if_called(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("source scan must not run when frozen")

    monkeypatch.setattr(config, "CONFIG_PATH", cfg)
    monkeypatch.setattr(config.sys, "frozen", True, raising=False)
    monkeypatch.setattr(config_contract, "audit_repository", fail_if_called)
    monkeypatch.setattr(config, "get", lambda path, default=None: default)
    monkeypatch.setattr(config, "secret", lambda *_a, **_k: "")

    issues = config.validate()

    assert called is False
    assert not any("Kontrak config" in issue for issue in issues)


def test_config_validate_forwards_contract_issues_without_values(
    tmp_path, monkeypatch
):
    from jarvis.core import config_contract

    cfg = tmp_path / "config.yaml"
    cfg.write_text("dead: private-value\n", encoding="utf-8")
    report = config_contract.ContractReport(
        declared_nodes=("dead",),
        declared_leaves=("dead",),
        dead_keys=("dead",),
    )
    monkeypatch.setattr(config, "CONFIG_PATH", cfg)
    monkeypatch.delattr(config.sys, "frozen", raising=False)
    monkeypatch.setattr(config, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(config_contract, "audit_repository", lambda *_a, **_k: report)
    monkeypatch.setattr(config, "get", lambda path, default=None: default)
    monkeypatch.setattr(config, "secret", lambda *_a, **_k: "")

    issues = config.validate()
    rendered = " ".join(issues)

    assert "dead" in rendered
    assert "private-value" not in rendered


def test_real_repository_config_has_no_drift():
    from jarvis.core import config_contract

    root = Path(__file__).resolve().parent.parent
    report = config_contract.audit_repository(root / "config.yaml", root)

    assert report.skipped_reason == ""
    assert report.scan_errors == ()
    assert report.unresolved_dynamic == ()
    assert report.dead_keys == ()
    assert report.undeclared_reads == ()
