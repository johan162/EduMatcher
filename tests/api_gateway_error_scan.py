"""Which ``error.code`` values can each gateway route answer with?

Derived from the source, not from what the route declares: every error code
is a string literal (``{"code": "STATS_DB"}``, ``_require_accepted(ack,
"HALT_REJECTED")``), so a route can produce exactly the codes written in its
handler body, in the functions it reaches by calls, and in its ``Depends``
dependencies -- plus the app-level ones (``VALIDATION`` from request parsing
when the route takes input, ``INTERNAL_ERROR`` from the catch-all).

Calls are resolved by name: a plain call to a function of the same module or
one imported from the package, and a method call ``x.name(...)`` to every
package method called ``name``. The method rule over-approximates by design;
the tests that use this compare it with the declared codes, so a false
positive shows up as a failure to look at, never as a silent gap.

Not a test module (no test_ prefix) -- pytest will not collect it.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from edumatcher.api_gateway.errors import ERROR_CODES

PACKAGE = "edumatcher.api_gateway"
ROOT = Path(__file__).resolve().parents[1] / "src" / "edumatcher" / "api_gateway"

#: Raised by the app for every route (main.py's catch-all handler).
ALWAYS = frozenset({"INTERNAL_ERROR"})


@dataclass
class _Module:
    name: str
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = field(
        default_factory=dict
    )
    #: local name -> (module, attribute) for ``from X import a``
    imported: dict[str, tuple[str, str]] = field(default_factory=dict)


def _module_name(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    return ".".join((PACKAGE, *rel.parts))


@cache
def _index() -> tuple[dict[str, _Module], dict[str, list[ast.AST]], dict[int, _Module]]:
    """Modules by name, package methods by name, and each function's module."""
    modules: dict[str, _Module] = {}
    methods: dict[str, list[ast.AST]] = {}
    owners: dict[int, _Module] = {}
    for path in sorted(ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module = _Module(_module_name(path))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                module.functions[node.name] = node
                owners[id(node)] = module
            elif isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        methods.setdefault(item.name, []).append(item)
                        owners[id(item)] = module
            elif isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    module.imported[alias.asname or alias.name] = (
                        node.module,
                        alias.name,
                    )
        modules[module.name] = module
    return modules, methods, owners


def _resolve(name: str, module: _Module) -> ast.AST | None:
    modules = _index()[0]
    if name in module.functions:
        return module.functions[name]
    if name in module.imported:
        source, attr = module.imported[name]
        if source in modules:
            return modules[source].functions.get(attr)
    return None


def _body_nodes(func: Any) -> list[ast.AST]:
    """Everything in *func*'s body (nested defs included), not its decorators."""
    nodes: list[ast.AST] = []
    for statement in func.body:
        nodes.extend(ast.walk(statement))
    return nodes


def _dependencies(func: Any) -> list[ast.Call]:
    """The ``Depends(x)`` calls in *func*'s parameter annotations and defaults."""
    found: list[ast.AST] = []
    args = func.args
    for node in [*args.args, *args.kwonlyargs]:
        if node.annotation is not None:
            found.extend(ast.walk(node.annotation))
    for default in [*args.defaults, *args.kw_defaults]:
        if default is not None:
            found.extend(ast.walk(default))
    return [
        n
        for n in found
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "Depends"
    ]


def codes_of(func: Any, module: _Module, seen: set[int] | None = None) -> set[str]:
    """Error codes reachable from *func* (defined in *module*)."""
    seen = set() if seen is None else seen
    if id(func) in seen:
        return set()
    seen.add(id(func))
    methods = _index()[1]
    codes: set[str] = set()
    targets: list[tuple[ast.AST, _Module]] = []
    for call in _dependencies(func):
        for arg in call.args:
            if isinstance(arg, ast.Name):
                target = _resolve(arg.id, module)
                if target is not None:
                    targets.append((target, _module_of(target)))
    for node in _body_nodes(func):
        if isinstance(node, ast.Constant) and node.value in ERROR_CODES:
            codes.add(node.value)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                target = _resolve(node.func.id, module)
                if target is not None:
                    targets.append((target, _module_of(target)))
            elif isinstance(node.func, ast.Attribute):
                for method in methods.get(node.func.attr, []):
                    targets.append((method, _module_of(method)))
    for target, owner in targets:
        codes |= codes_of(target, owner, seen)
    return codes


def _module_of(node: ast.AST) -> _Module:
    return _index()[2][id(node)]


def route_codes(module_name: str, handler: str, takes_input: bool) -> set[str]:
    """Every code the route served by *module_name*.*handler* can answer with."""
    module = _index()[0][module_name]
    codes = codes_of(module.functions[handler], module) | ALWAYS
    if takes_input:
        codes.add("VALIDATION")
    return codes
