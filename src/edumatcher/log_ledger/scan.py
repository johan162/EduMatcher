"""Find every WARNING+ log call site in the ``edumatcher`` package.

The log ledger has one entry per ``(logger, template)`` pair, where
``template`` is the format string a call passes before ``%``-formatting
(docs-design/EduMatcher-Log-Ledger.md §3.2). This module reads the package
source with :mod:`ast` (it imports nothing it scans) and reports each call
site as a :class:`CallSite`: its logger name, the levels it can log at, and
its template — or, when it cannot work those out, a ``problem`` saying why,
so a site is never skipped silently.

A call is a log call when its receiver is a name bound at module level to
``logging.getLogger(...)``. Levels come from the method name
(``warning``/``error``/``critical``/``exception``) or, for ``log.log(level,
...)``, from the level expression: ``logging.WARNING``, a conditional
between such constants, or a module-level dict of them.

Relay sites — a helper that receives its template from the caller and logs
it — are listed in :data:`RELAYS`. The scanner reads the template from each
call that feeds the relay instead of from the relay's own log call.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import edumatcher

#: Python logging levels by name, for level expressions and comparisons.
LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}

#: Levels the ledger covers; the log client only sends a template id for these.
LEDGER_LEVELS = frozenset({"WARNING", "ERROR", "CRITICAL"})

_METHOD_LEVEL = {
    "warning": "WARNING",
    "error": "ERROR",
    "exception": "ERROR",
    "critical": "CRITICAL",
}


@dataclass(frozen=True)
class Relay:
    """A helper that logs a template its caller hands it.

    ``function`` is the relaying function's name: log calls (and feeder
    calls) inside it with a non-literal template are not reported. Every
    call in ``module`` whose callee is spelled ``feeder`` supplies one
    template, at argument ``template_arg`` (item 0 of that argument when
    ``tuple_item``). Its level is ``level``, or read from argument
    ``level_arg``.
    """

    module: str
    function: str
    feeder: str
    template_arg: int
    level: str | None = None
    level_arg: int | None = None
    tuple_item: bool = False


RELAYS: tuple[Relay, ...] = (
    # Warnings collected at import time, before logging is configured, and
    # replayed by _log_startup_warnings() as log.warning(template, *args).
    Relay("edumatcher.board.main", "_log_startup_warnings", "warnings.append", 0, "WARNING", tuple_item=True),
    Relay("edumatcher.orders.main", "_log_startup_warnings", "warnings.append", 0, "WARNING", tuple_item=True),
    # Rate-limited warnings, one limiter per kind.
    Relay("edumatcher.monitor.collector", "_warn", "self._warn", 1, "WARNING"),
    # Rate-limited warnings: _warn() -> _log_rate_limited(level, ...).
    Relay("edumatcher.health.reporter", "_warn", "self._warn", 0, "WARNING"),
    Relay("edumatcher.health.reporter", "_log_rate_limited", "self._log_rate_limited", 1, level_arg=0),
)  # fmt: skip


@dataclass(frozen=True)
class CallSite:
    """One WARNING+ log call (or relay feeder) found in the source."""

    path: str  # relative to the package root's parent, e.g. "edumatcher/engine/main.py"
    line: int
    module: str
    logger: str | None
    levels: frozenset[str]
    template: str | None
    problem: str | None = None

    @property
    def package(self) -> str:
        """The top-level subpackage (or module) under ``edumatcher``."""
        parts = self.module.split(".")
        return parts[1] if len(parts) > 1 else parts[0]

    @property
    def level(self) -> str:
        """The highest ledger level this site can log at."""
        return max(self.levels & LEDGER_LEVELS, key=LEVELS.__getitem__)

    @property
    def where(self) -> str:
        return f"{self.path}:{self.line}"


def package_root() -> Path:
    """The installed (or checked-out) ``edumatcher`` package directory."""
    return Path(edumatcher.__file__).resolve().parent


def scan_package(root: Path | None = None) -> list[CallSite]:
    """Every WARNING+ call site under ``root`` (default: the package itself)."""
    root = root or package_root()
    sites: list[CallSite] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root.parent)
        module = ".".join(rel.with_suffix("").parts)
        if module.endswith(".__init__"):
            module = module.removesuffix(".__init__")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        sites.extend(_ModuleScanner(str(rel), module, tree).scan())
    return sites


class _ModuleScanner:
    def __init__(self, path: str, module: str, tree: ast.Module) -> None:
        self.path = path
        self.module = module
        self.tree = tree
        self.loggers = self._module_loggers()
        self.level_maps = self._module_level_maps()
        self.relays = [r for r in RELAYS if r.module == module]
        self.sites: list[CallSite] = []

    # -- module-level facts ------------------------------------------------

    def _module_loggers(self) -> dict[str, str]:
        """Module-level names bound to ``logging.getLogger(...)``."""
        out: dict[str, str] = {}
        for node in self.tree.body:
            if not isinstance(node, ast.Assign) or not _is_get_logger(node.value):
                continue
            assert isinstance(node.value, ast.Call)
            args = node.value.args
            if not args:
                continue  # the root logger: not used for call sites here
            arg = args[0]
            if isinstance(arg, ast.Name) and arg.id == "__name__":
                name = self.module
            elif isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                name = arg.value
            else:
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = name
        return out

    def _module_level_maps(self) -> dict[str, frozenset[str]]:
        """Module-level dict literals whose values are all ``logging.X``."""
        out: dict[str, frozenset[str]] = {}
        for node in self.tree.body:
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
                continue
            levels = [_level_constant(v) for v in node.value.values]
            if levels and all(lv is not None for lv in levels):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        out[target.id] = frozenset(lv for lv in levels if lv)
        return out

    # -- traversal ---------------------------------------------------------

    def scan(self) -> list[CallSite]:
        self._visit(self.tree, [])
        return self.sites

    def _visit(
        self, node: ast.AST, funcs: list[ast.FunctionDef | ast.AsyncFunctionDef]
    ) -> None:
        for child in ast.iter_child_nodes(node):
            inner = funcs
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                inner = [*funcs, child]
            if isinstance(child, ast.Call):
                self._call(child, inner)
            self._visit(child, inner)

    def _call(
        self, call: ast.Call, funcs: list[ast.FunctionDef | ast.AsyncFunctionDef]
    ) -> None:
        func = call.func
        callee = ast.unparse(func)
        in_relay = bool(funcs) and any(
            r.function == funcs[-1].name for r in self.relays
        )
        for relay in self.relays:
            if callee == relay.feeder:
                self._feeder(call, relay, in_relay)
                return
        if not isinstance(func, ast.Attribute) or not isinstance(func.value, ast.Name):
            return
        receiver = func.value.id
        if func.attr not in _METHOD_LEVEL and func.attr != "log":
            return
        if receiver not in self.loggers:
            if receiver in ("log", "logger") and func.attr != "log":
                self._add(
                    call,
                    None,
                    frozenset(LEDGER_LEVELS),
                    None,
                    f"logger {receiver!r} is not a module-level logging.getLogger(...)",
                )
            return
        if any(receiver in _local_names(f) for f in funcs):
            self._add(
                call,
                None,
                frozenset(LEDGER_LEVELS),
                None,
                f"logger {receiver!r} is shadowed by a local name",
            )
            return
        logger = self.loggers[receiver]
        if func.attr == "log":
            if len(call.args) < 2:
                return
            levels = self._levels(call.args[0])
            template_node: ast.expr | None = call.args[1]
        else:
            levels = frozenset({_METHOD_LEVEL[func.attr]})
            template_node = call.args[0] if call.args else None
        if levels is None:
            if in_relay:
                return
            self._add(
                call,
                logger,
                frozenset(LEDGER_LEVELS),
                None,
                "level expression not understood",
            )
            return
        if not levels & LEDGER_LEVELS:
            return
        template = _literal(template_node)
        if template is None:
            if in_relay:
                return
            self._add(call, logger, levels, None, "template is not a string literal")
            return
        self._add(call, logger, levels, template)

    def _feeder(self, call: ast.Call, relay: Relay, in_relay: bool) -> None:
        logger = self.loggers.get("log")
        if relay.level_arg is not None:
            levels = (
                self._levels(call.args[relay.level_arg])
                if len(call.args) > relay.level_arg
                else None
            )
        else:
            assert relay.level is not None
            levels = frozenset({relay.level})
        if levels is None:
            if not in_relay:
                self._add(
                    call,
                    logger,
                    frozenset(LEDGER_LEVELS),
                    None,
                    "relay level expression not understood",
                )
            return
        if not levels & LEDGER_LEVELS:
            return
        node: ast.expr | None = (
            call.args[relay.template_arg]
            if len(call.args) > relay.template_arg
            else None
        )
        if relay.tuple_item:
            node = node.elts[0] if isinstance(node, ast.Tuple) and node.elts else None
        template = _literal(node)
        if template is None:
            if not in_relay:
                self._add(
                    call,
                    logger,
                    levels,
                    None,
                    "relayed template is not a string literal",
                )
            return
        if logger is None:
            self._add(
                call,
                None,
                levels,
                template,
                "relay module has no module-level 'log' logger",
            )
            return
        self._add(call, logger, levels, template)

    def _levels(self, node: ast.expr) -> frozenset[str] | None:
        constant = _level_constant(node)
        if constant is not None:
            return frozenset({constant})
        if isinstance(node, ast.IfExp):
            body, orelse = self._levels(node.body), self._levels(node.orelse)
            return None if body is None or orelse is None else body | orelse
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
            return self.level_maps.get(node.value.id)
        return None

    def _add(
        self,
        call: ast.Call,
        logger: str | None,
        levels: frozenset[str],
        template: str | None,
        problem: str | None = None,
    ) -> None:
        self.sites.append(
            CallSite(
                self.path, call.lineno, self.module, logger, levels, template, problem
            )
        )


def _is_get_logger(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "getLogger"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "logging"
    )


def _level_constant(node: ast.expr) -> str | None:
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "logging"
        and node.attr in LEVELS
    ):
        return node.attr
    return None


def _literal(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _local_names(func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Parameters and names assigned directly in ``func``'s own body."""
    args = func.args
    names = {a.arg for a in [*args.posonlyargs, *args.args, *args.kwonlyargs]}
    for extra in (args.vararg, args.kwarg):
        if extra is not None:
            names.add(extra.arg)
    for node in ast.walk(func):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names |= {t.id for t in targets if isinstance(t, ast.Name)}
    return names
