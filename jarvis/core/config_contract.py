"""Kontrak dua arah antara ``config.yaml`` dan consumer production.

Analyzer tidak mengimpor modul production. Pembacaan config ditemukan lewat AST;
pola dinamis hanya diterima bila domainnya finite dan terdaftar di sini.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


_SLOT_IDS = (
    "vision",
    "reflect",
    "compression",
    "web_extract",
    "title_gen",
    "approval",
    "curator_review",
    "embedding",
)
_GOOGLE_APIS = ("calendar", "youtube", "gmail", "drive")
_ACK_LANGUAGES = ("id", "en")

_SOURCE_DIRS = ("jarvis", "actions", "dashboard", "memory")
_SOURCE_FILES = ("main.py",)
# Pengecualian selalu exact. BrowserAgentView sudah dipensiunkan: jalur
# OPEN_BROWSER_AGENT di window.py membuka browser sistem, dan tidak ada import
# production ke modul ini. ui.py root juga keluar dari entry point pada Fase 38.
_SOURCE_EXCLUSIONS = {
    "jarvis/browser/agent_view.py": (
        "Embedded browser dipensiunkan; browser sistem jadi jalur canonical."
    ),
    "ui.py": "UI legacy tidak lagi diimpor entry point canonical (Fase 38).",
}

_WRAPPER_READS: dict[str, dict[str, str]] = {
    "jarvis/agent/interaction.py": {"_int_config": ""},
    "jarvis/agent/voice_consent.py": {"_words": ""},
    "jarvis/integrations/whatsapp_rollout.py": {"_config_get": ""},
    "jarvis/integrations/whatsapp_readiness.py": {"_config_flag": ""},
    "jarvis/integrations/youtube_capability.py": {
        "_secret_name": "integrations.youtube.",
    },
}

# Panggilan config dinamis yang diimplementasikan wrapper di atas. Consumer
# wrapper-nya dipindai terpisah; body ini tidak boleh menjadi wildcard global.
_DECLARED_ONLY_EXCEPTIONS: dict[str, str] = {}
_READ_ONLY_EXCEPTIONS: dict[str, str] = {}

_WRAPPER_BODIES = {
    (relative, function)
    for relative, wrappers in _WRAPPER_READS.items()
    for function in wrappers
}
_WRAPPER_BODIES.update({
    ("jarvis/core/settings_service.py", "resolve"),
    ("jarvis/integrations/whatsapp_readiness.py", "_config_allowlist"),
})

# Field Settings ini dihitung dari backend runtime dan sengaja tidak menyentuh
# config.yaml; resolve() punya branch khusus sebelum config.get(f["key"]).
_SETTINGS_VIRTUAL_FIELDS = {"security.secrets_backend"}

_LITERAL_DOMAINS: dict[tuple[str, str, str], tuple[str, ...]] = {
    (
        "jarvis/agent/auxiliary.py",
        "slot_config",
        "auxiliary.{task}.provider",
    ): _SLOT_IDS,
    (
        "jarvis/agent/auxiliary.py",
        "slot_config",
        "auxiliary.{task}.model",
    ): _SLOT_IDS,
    (
        "jarvis/integrations/google_auth.py",
        "api_enabled",
        "providers.google.apis.{api}.enabled",
    ): _GOOGLE_APIS,
    (
        "jarvis/integrations/google_auth.py",
        "write_enabled",
        "providers.google.apis.{api}.write",
    ): _GOOGLE_APIS,
    (
        "jarvis/integrations/google_auth.py",
        "requested_scopes",
        "providers.google.apis.{api}.enabled",
    ): _GOOGLE_APIS,
    (
        "jarvis/integrations/google_auth.py",
        "requested_scopes",
        "providers.google.apis.{api}.write",
    ): ("calendar", "youtube"),
    (
        "jarvis/agent/interaction.py",
        "render_ack",
        "agent.interaction.ack_templates.{lang}",
    ): _ACK_LANGUAGES,
    (
        "jarvis/core/settings_service.py",
        "_auxiliary_fields",
        "auxiliary.{sid}.provider",
    ): _SLOT_IDS,
    (
        "jarvis/core/settings_service.py",
        "_auxiliary_fields",
        "auxiliary.{sid}.model",
    ): tuple(slot for slot in _SLOT_IDS if slot != "embedding"),
}


@dataclass(frozen=True)
class ContractReport:
    declared_nodes: tuple[str, ...] = ()
    declared_leaves: tuple[str, ...] = ()
    exact_reads: tuple[str, ...] = ()
    section_reads: tuple[str, ...] = ()
    dead_keys: tuple[str, ...] = ()
    undeclared_reads: tuple[str, ...] = ()
    unresolved_dynamic: tuple[str, ...] = ()
    scan_errors: tuple[str, ...] = ()
    skipped_reason: str = ""


def _flatten(data: Any) -> tuple[set[str], set[str]]:
    nodes: set[str] = set()
    leaves: set[str] = set()

    def visit(value: Any, prefix: str) -> None:
        if isinstance(value, dict) and value:
            for raw_key, child in value.items():
                key = str(raw_key)
                path = f"{prefix}.{key}" if prefix else key
                nodes.add(path)
                visit(child, path)
            return
        if prefix:
            leaves.add(prefix)

    visit(data, "")
    return nodes, leaves


def _source_paths(root: Path) -> tuple[Path, ...]:
    paths: set[Path] = set()
    for dirname in _SOURCE_DIRS:
        folder = root / dirname
        if folder.is_dir():
            paths.update(
                path
                for path in folder.rglob("*.py")
                if path.is_file()
                and _relative(path, root) not in _SOURCE_EXCLUSIONS
            )
    for name in _SOURCE_FILES:
        path = root / name
        if path.is_file() and name not in _SOURCE_EXCLUSIONS:
            paths.add(path)
    return tuple(sorted(paths, key=lambda path: path.as_posix()))


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def _literal_values(
    node: ast.AST | None,
    env: dict[str, set[str]],
) -> set[str] | None:
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.Name):
        values = env.get(node.id)
        return set(values) if values is not None else None
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        out: set[str] = set()
        for item in node.elts:
            values = _literal_values(item, env)
            if values is None:
                return None
            out.update(values)
        return out
    if isinstance(node, ast.IfExp):
        left = _literal_values(node.body, env)
        right = _literal_values(node.orelse, env)
        if left is None or right is None:
            return None
        return left | right
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _literal_values(node.left, env)
        right = _literal_values(node.right, env)
        if left is None or right is None:
            return None
        return {a + b for a in left for b in right}
    if isinstance(node, ast.JoinedStr):
        out = {""}
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                values = {part.value}
            elif isinstance(part, ast.FormattedValue):
                values = _literal_values(part.value, env)
                if values is None:
                    return None
            else:
                return None
            out = {prefix + value for prefix in out for value in values}
        return out
    return None


def _template(node: ast.AST | None) -> str:
    if not isinstance(node, ast.JoinedStr):
        return "<dynamic>"
    parts: list[str] = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
        elif isinstance(value, ast.FormattedValue):
            expr = value.value
            if isinstance(expr, ast.Name):
                parts.append("{" + expr.id + "}")
            elif isinstance(expr, ast.Subscript) and isinstance(expr.value, ast.Name):
                parts.append("{" + expr.value.id + "[...]}")
            else:
                parts.append("{...}")
    return "".join(parts) or "<dynamic>"


def _target_names(node: ast.AST | None) -> set[str]:
    if node is None:
        return set()
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        return {
            name
            for item in node.elts
            for name in _target_names(item)
        }
    return set()


def _collect_assignments(
    body: Iterable[ast.stmt],
    base: dict[str, set[str]],
    *,
    blocked: Iterable[str] = (),
) -> dict[str, set[str]]:
    """Finite constants dalam satu scope, tanpa mewarisi nama local/parameter."""
    statements = list(body)
    scope = ast.Module(body=statements, type_ignores=[])
    entries: dict[str, list[ast.AST | None]] = {}
    bound = set(blocked)

    def add(target: ast.AST | None, value: ast.AST | None) -> None:
        for name in _target_names(target):
            bound.add(name)
            entries.setdefault(name, []).append(value)

    for stmt in _scope_nodes(scope):
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                add(target, stmt.value)
        elif isinstance(stmt, ast.AnnAssign):
            add(stmt.target, stmt.value)
        elif isinstance(stmt, ast.NamedExpr):
            add(stmt.target, stmt.value)
        elif isinstance(stmt, (ast.For, ast.AsyncFor)):
            add(stmt.target, None)
        elif isinstance(stmt, (ast.With, ast.AsyncWith)):
            for item in stmt.items:
                add(item.optional_vars, None)
        elif isinstance(stmt, ast.ExceptHandler) and stmt.name:
            bound.add(stmt.name)
            entries.setdefault(stmt.name, []).append(None)
        elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
            for item in stmt.names:
                name = item.asname or item.name.split(".", 1)[0]
                bound.add(name)
                entries.setdefault(name, []).append(None)
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(stmt.name)
            entries.setdefault(stmt.name, []).append(None)
        elif isinstance(stmt, ast.AugAssign):
            add(stmt.target, None)
        elif isinstance(stmt, ast.Delete):
            for target in stmt.targets:
                add(target, None)

    inherited = {
        name: set(values)
        for name, values in base.items()
        if name not in bound
    }
    env = dict(inherited)
    for _ in range(len(entries) + 1):
        resolved: dict[str, set[str]] = {}
        for name, values_nodes in entries.items():
            values: set[str] = set()
            for value_node in values_nodes:
                current = _literal_values(value_node, env)
                if current is None:
                    break
                values.update(current)
            else:
                resolved[name] = values
        updated = {**inherited, **resolved}
        if updated == env:
            break
        env = updated
    return env


def _scope_config_imports(scope: ast.AST) -> dict[str, tuple[int, ...]]:
    """Alias config dan semua baris import dalam satu lexical scope saja."""
    lines: dict[str, list[int]] = {}
    for node in _scope_nodes(scope):
        if isinstance(node, ast.ImportFrom) and node.module == "jarvis.core":
            for name in node.names:
                if name.name == "config":
                    alias = name.asname or name.name
                    lines.setdefault(alias, []).append(node.lineno)
        elif isinstance(node, ast.Import):
            for name in node.names:
                if name.name != "jarvis.core.config":
                    continue
                # ``import jarvis.core.config`` binds ``jarvis`` dan callers use
                # full attribute chain. ``as cfg`` binds explicit alias.
                alias = name.asname or "jarvis.core.config"
                lines.setdefault(alias, []).append(node.lineno)
    return {
        alias: tuple(sorted(alias_lines))
        for alias, alias_lines in lines.items()
    }


def _function_parameters(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
) -> set[str]:
    args = node.args
    names = {
        arg.arg
        for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs)
    }
    if args.vararg is not None:
        names.add(args.vararg.arg)
    if args.kwarg is not None:
        names.add(args.kwarg.arg)
    return names


def _scope_binding_lines(node: ast.AST) -> dict[str, tuple[int, ...]]:
    """Baris binding non-config dalam scope; parameter berlaku sejak awal."""
    lines: dict[str, list[int]] = {}
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        for name in _function_parameters(node):
            lines.setdefault(name, []).append(getattr(node, "lineno", 0))
    for child in _scope_nodes(node):
        targets: list[ast.AST | None] = []
        if isinstance(child, ast.Assign):
            targets.extend(child.targets)
        elif isinstance(child, ast.AnnAssign):
            targets.append(child.target)
        elif isinstance(child, ast.NamedExpr):
            targets.append(child.target)
        elif isinstance(child, (ast.For, ast.AsyncFor)):
            targets.append(child.target)
        elif isinstance(child, (ast.With, ast.AsyncWith)):
            targets.extend(item.optional_vars for item in child.items)
        elif isinstance(child, ast.ExceptHandler) and child.name:
            lines.setdefault(child.name, []).append(child.lineno)
        elif isinstance(child, ast.ImportFrom):
            for item in child.names:
                if child.module == "jarvis.core" and item.name == "config":
                    continue
                name = item.asname or item.name
                lines.setdefault(name, []).append(child.lineno)
        elif isinstance(child, ast.Import):
            for item in child.names:
                if item.name == "jarvis.core.config":
                    continue
                name = item.asname or item.name.split(".", 1)[0]
                lines.setdefault(name, []).append(child.lineno)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            lines.setdefault(child.name, []).append(child.lineno)
        elif isinstance(child, ast.AugAssign):
            targets.append(child.target)
        elif isinstance(child, ast.Delete):
            targets.extend(child.targets)
        for target in targets:
            for name in _target_names(target):
                lines.setdefault(name, []).append(child.lineno)
    return {
        name: tuple(sorted(binding_lines))
        for name, binding_lines in lines.items()
    }


def _dotted_name(node: ast.AST) -> str:
    parts: list[str] = []
    current: ast.AST | None = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return ""


def _scope_nodes(node: ast.AST) -> Iterable[ast.AST]:
    """Turun dalam satu lexical scope tanpa masuk function/class bersarang."""
    for child in ast.iter_child_nodes(node):
        yield child
        if isinstance(
            child,
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef),
        ):
            continue
        yield from _scope_nodes(child)


def _config_call(
    node: ast.Call,
    aliases: set[str],
) -> tuple[str, ast.AST | None] | None:
    func = node.func
    method = ""
    if isinstance(func, ast.Attribute):
        owner = _dotted_name(func.value)
        if owner in aliases:
            method = func.attr
    elif isinstance(func, ast.Name) and "" in aliases:
        method = func.id
    if method not in {"get", "section", "secret"}:
        return None
    index = 1 if method == "secret" else 0
    argument = node.args[index] if len(node.args) > index else None
    if argument is None:
        keyword = "config_path" if method == "secret" else "path"
        argument = next(
            (item.value for item in node.keywords if item.arg == keyword),
            None,
        )
    if method == "secret" and argument is None:
        # ``secret("ENV_NAME")`` hanya membaca environment; tidak ada config
        # path yang perlu dicocokkan atau dilaporkan sebagai dynamic.
        argument = ast.Constant(value="")
    return method, argument


def _dynamic_expansion(
    relative: str,
    function: str,
    template: str,
) -> set[str] | None:
    domain = _LITERAL_DOMAINS.get((relative, function, template))
    if domain is None:
        return None
    field = next(
        (part[1:-1] for part in template.split(".") if part.startswith("{")),
        "",
    )
    if not field:
        return None
    return {template.replace("{" + field + "}", value) for value in domain}


def _wrapper_argument(node: ast.Call) -> ast.AST | None:
    if node.args:
        return node.args[0]
    return next(
        (
            item.value
            for item in node.keywords
            if item.arg in {"key", "path"}
        ),
        None,
    )


def _enclosing_function(
    node: ast.AST,
    parents: dict[ast.AST, ast.AST],
) -> str:
    current = parents.get(node)
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current.name
        if isinstance(current, ast.Lambda):
            return "<lambda>"
        current = parents.get(current)
    return "<module>"


def _settings_field_reads(
    tree: ast.AST,
    relative: str,
    parents: dict[ast.AST, ast.AST],
) -> tuple[set[str], set[str]]:
    if relative != "jarvis/core/settings_service.py":
        return set(), set()
    out: set[str] = set()
    unresolved: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        function = _enclosing_function(node, parents)
        if function not in {"sections", "_auxiliary_fields"}:
            continue
        for key, value in zip(node.keys, node.values):
            if not isinstance(key, ast.Constant) or key.value != "key":
                continue
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                out.add(value.value)
                continue
            template = _template(value)
            expanded = _dynamic_expansion(relative, function, template)
            if expanded is not None:
                out.update(expanded)
            else:
                unresolved.add(
                    f"{relative}:{value.lineno} settings_key:{template}"
                )
    return out - _SETTINGS_VIRTUAL_FIELDS, unresolved


def _scan_file(
    path: Path,
    root: Path,
) -> tuple[set[str], set[str], set[str], set[str]]:
    relative = _relative(path, root)
    try:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=relative)
    except (OSError, SyntaxError, UnicodeError) as exc:
        return set(), set(), set(), {f"{relative}:{type(exc).__name__}"}

    own_module = relative == "jarvis/core/config.py"
    module_imports = _scope_config_imports(tree)
    module_bindings = _scope_binding_lines(tree)
    module_initial_aliases = {""} if own_module else set()

    parents: dict[ast.AST, ast.AST] = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    module_env = _collect_assignments(tree.body, {})
    exact: set[str] = set()
    wrappers = _WRAPPER_READS.get(relative, {})
    wrapper_definition_lines = {
        node.name: node.lineno
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in wrappers
    }
    settings_reads, unresolved_settings = _settings_field_reads(
        tree,
        relative,
        parents,
    )
    exact.update(settings_reads)
    if relative == "jarvis/integrations/whatsapp_readiness.py":
        exact.update(
            module_env.get("_ENABLED_KEY", set())
            | module_env.get("_ALLOWED_IDS_KEY", set())
        )
    sections: set[str] = set()
    unresolved = set(unresolved_settings)
    function_envs: dict[
        ast.AST,
        tuple[
            str,
            dict[str, set[str]],
            set[str],
            dict[str, tuple[int, ...]],
            dict[str, tuple[int, ...]],
        ],
    ] = {}

    def register_nested(
        node: ast.AST,
        inherited_env: dict[str, set[str]],
        inherited_aliases: set[str],
    ) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(
                child,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda),
            ):
                register_scope(child, inherited_env, inherited_aliases)
            elif isinstance(child, ast.ClassDef):
                # Nama di class body bukan lexical parent method. Method tetap
                # mewarisi module/outer-function constants, bukan class attrs.
                register_nested(child, inherited_env, inherited_aliases)
            else:
                register_nested(child, inherited_env, inherited_aliases)

    def completed_scope_aliases(
        inherited: set[str],
        imports: dict[str, tuple[int, ...]],
        bindings: dict[str, tuple[int, ...]],
    ) -> set[str]:
        local_roots = set(bindings) | {
            alias.split(".", 1)[0]
            for alias in imports
            if alias
        }
        active = {
            alias
            for alias in inherited
            if not alias or alias.split(".", 1)[0] not in local_roots
        }
        for root in local_roots:
            import_events = {
                line: alias
                for alias, lines in imports.items()
                if alias.split(".", 1)[0] == root
                for line in lines
            }
            binding_events = bindings.get(root, ())
            latest_import = max(import_events, default=-1)
            latest_binding = max(binding_events, default=-1)
            if latest_import > latest_binding:
                active.add(import_events[latest_import])
        return active

    def aliases_in_scope(
        inherited: set[str],
        imports: dict[str, tuple[int, ...]],
        bindings: dict[str, tuple[int, ...]],
        line: int,
        *,
        lexical: bool,
    ) -> set[str]:
        # Binding function bersifat lexical: alias warisan tertutup sejak awal.
        # Binding module bersifat berurutan: call sebelum assignment masih sah.
        local_roots = set(bindings) | {
            alias.split(".", 1)[0]
            for alias in imports
            if alias
        }
        roots = set(bindings) | {
            alias.split(".", 1)[0]
            for alias in inherited | set(imports)
            if alias
        }
        active = {alias for alias in inherited if not alias}
        for root in roots:
            import_events = {
                event_line: alias
                for alias, lines in imports.items()
                if alias.split(".", 1)[0] == root
                for event_line in lines
                if event_line <= line
            }
            binding_events = tuple(
                event_line
                for event_line in bindings.get(root, ())
                if event_line <= line
            )
            latest_import = max(import_events, default=-1)
            latest_binding = max(binding_events, default=-1)
            if latest_import > latest_binding:
                active.add(import_events[latest_import])
                continue
            if lexical and root in local_roots:
                continue
            active.update(
                alias
                for alias in inherited
                if alias and alias.split(".", 1)[0] == root
            )
        return active

    def register_scope(
        node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
        inherited_env: dict[str, set[str]],
        inherited_aliases: set[str],
    ) -> None:
        body = node.body if isinstance(node.body, list) else []
        function_env = _collect_assignments(
            body,
            inherited_env,
            blocked=_function_parameters(node),
        )
        function = node.name if hasattr(node, "name") else "<lambda>"
        local_imports = _scope_config_imports(node)
        local_bindings = _scope_binding_lines(node)
        aliases = completed_scope_aliases(
            inherited_aliases,
            local_imports,
            local_bindings,
        )
        function_envs[node] = (
            function,
            function_env,
            aliases,
            local_imports,
            local_bindings,
        )
        register_nested(node, function_env, aliases)

    module_aliases = completed_scope_aliases(
        module_initial_aliases,
        module_imports,
        module_bindings,
    )
    register_nested(tree, module_env, module_aliases)

    def wrapper_is_active(node: ast.AST, name: str) -> bool:
        definition_line = wrapper_definition_lines.get(name)
        if definition_line is None:
            return False

        current: ast.AST | None = node
        scopes: list[ast.AST] = []
        while current is not None:
            if current in function_envs:
                scopes.append(current)
            current = parents.get(current)

        # Function bodies execute after module initialization, while a module
        # call observes bindings in source order. The canonical wrapper is live
        # only while its module-level definition is the latest binding.
        line = max(module_bindings.get(name, ()), default=-1)
        if not scopes:
            call_line = getattr(node, "lineno", 0)
            line = max(
                (
                    event_line
                    for event_line in module_bindings.get(name, ())
                    if event_line <= call_line
                ),
                default=-1,
            )
        active = line == definition_line
        if not active:
            return False

        # Any function-local binding is lexical in Python: it shadows the
        # inherited wrapper throughout that scope, including before assignment
        # and in nested closures. Class bodies are intentionally not lexical
        # parents of methods and therefore do not appear in function_envs.
        for scope in reversed(scopes):
            local_bindings = function_envs[scope][4]
            if name in local_bindings:
                return False
        return True

    def context(
        node: ast.AST,
    ) -> tuple[str, dict[str, set[str]], set[str]]:
        current: ast.AST | None = node
        function = "<module>"
        env = module_env
        call_line = getattr(node, "lineno", 0)
        scopes: list[ast.AST] = []
        while current is not None:
            if current in function_envs:
                scopes.append(current)
            current = parents.get(current)
        if scopes:
            # Function dijalankan setelah module selesai diimpor. Outer function
            # juga sudah mencapai titik pembuatan/pemanggilan closure; hanya scope
            # pemilik call yang membutuhkan urutan event terhadap baris call.
            aliases = set(module_aliases)
            for scope in reversed(scopes):
                (
                    function,
                    env,
                    scope_aliases,
                    local_imports,
                    local_bindings,
                ) = function_envs[scope]
                if scope is scopes[0]:
                    aliases = aliases_in_scope(
                        aliases,
                        local_imports,
                        local_bindings,
                        call_line,
                        lexical=True,
                    )
                else:
                    aliases = set(scope_aliases)
        else:
            aliases = aliases_in_scope(
                module_initial_aliases,
                module_imports,
                module_bindings,
                call_line,
                lexical=False,
            )
        return function, env, aliases

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function, env, active_aliases = context(node)
        if isinstance(node.func, ast.Name):
            prefix = wrappers.get(node.func.id)
            if prefix is not None and wrapper_is_active(node, node.func.id):
                argument = _wrapper_argument(node)
                values = _literal_values(argument, env)
                if values is None:
                    unresolved.add(
                        f"{relative}:{node.lineno} wrapper:{node.func.id}"
                    )
                else:
                    exact.update(prefix + value for value in values if value)
        found = _config_call(node, active_aliases)
        if found is None:
            continue
        method, argument = found
        values = _literal_values(argument, env)
        if (
            relative == "jarvis/core/config.py"
            and isinstance(node.func, ast.Name)
            and node.func.id in {"get", "section", "secret"}
            and function != "<module>"
            and values is None
        ):
            # Implementasi config saling memanggil dengan path milik caller.
            # Itu bukan consumer YAML tambahan; literal di validate() tetap
            # dihitung sebagai consumer production biasa.
            continue
        if values is not None:
            target = sections if method == "section" else exact
            target.update(value for value in values if value)
            continue
        template = _template(argument)
        expanded = _dynamic_expansion(relative, function, template)
        if expanded is not None:
            exact.update(expanded)
            continue
        if (relative, function) in _WRAPPER_BODIES:
            continue
        unresolved.add(f"{relative}:{node.lineno} {template}")

    return exact, sections, unresolved, set()


def analyze(
    data: Any,
    source_root: Path,
    *,
    source_paths: Iterable[Path] | None = None,
) -> ContractReport:
    """Bandingkan data config dengan source production tanpa mengimpor source."""
    root = Path(source_root)
    nodes, leaves = _flatten(data)
    paths = tuple(source_paths) if source_paths is not None else _source_paths(root)
    if not root.is_dir() or (source_paths is None and not paths):
        return ContractReport(
            declared_nodes=tuple(sorted(nodes)),
            declared_leaves=tuple(sorted(leaves)),
            skipped_reason="source_unavailable",
        )

    exact: set[str] = set()
    sections: set[str] = set()
    unresolved: set[str] = set()
    scan_errors: set[str] = set()
    for path in paths:
        reads, section_reads, dynamic, errors = _scan_file(Path(path), root)
        exact.update(reads)
        sections.update(section_reads)
        unresolved.update(dynamic)
        scan_errors.update(errors)

    consumed = set(exact)
    for section in sections:
        prefix = section + "."
        if section in leaves:
            consumed.add(section)
        consumed.update(leaf for leaf in leaves if leaf.startswith(prefix))

    dead = leaves - consumed - set(_DECLARED_ONLY_EXCEPTIONS)
    undeclared = {
        path for path in exact
        if path not in nodes and path not in _READ_ONLY_EXCEPTIONS
    }
    undeclared.update(
        path for path in sections
        if path not in nodes and path not in _READ_ONLY_EXCEPTIONS
    )
    return ContractReport(
        declared_nodes=tuple(sorted(nodes)),
        declared_leaves=tuple(sorted(leaves)),
        exact_reads=tuple(sorted(exact)),
        section_reads=tuple(sorted(sections)),
        dead_keys=tuple(sorted(dead)),
        undeclared_reads=tuple(sorted(undeclared)),
        unresolved_dynamic=tuple(sorted(unresolved)),
        scan_errors=tuple(sorted(scan_errors)),
    )


def audit_repository(config_path: Path, source_root: Path) -> ContractReport:
    """Muat satu YAML lalu audit source root. Nilai config tidak masuk report."""
    try:
        import yaml

        data = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        data = {}
    except Exception as exc:  # YAML parser error harus aman dan bounded
        return ContractReport(
            scan_errors=(f"config.yaml:{type(exc).__name__}",),
        )
    return analyze(data, Path(source_root))


def issues(report: ContractReport) -> list[str]:
    """Issue aman untuk startup/health; hanya path dan jenis kegagalan."""
    out = [f"Config key tidak dipakai kode: {path}." for path in report.dead_keys]
    out.extend(
        f"Kode membaca config yang tidak dideklarasikan: {path}."
        for path in report.undeclared_reads
    )
    out.extend(
        f"Pembacaan config dinamis belum punya kontrak: {item}."
        for item in report.unresolved_dynamic
    )
    out.extend(
        f"Audit config gagal memindai: {item}."
        for item in report.scan_errors
    )
    return out
