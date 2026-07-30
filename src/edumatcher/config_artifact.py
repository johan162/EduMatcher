"""
The compiled configuration artifact.

`engine_config.yaml` is what you author. This module defines what the exchange
actually *runs*: a single JSON document at
``<DATA_DIR>/ref_data/engine_config.json`` in which every default is already
resolved and every value already validated.

Why compile at all
------------------
Eight modules used to parse the same YAML independently — the engine plus one
loader per subsystem — each with its own copy of the defaults for its section.
Nothing kept those copies in step, so a default could be changed in one and
silently disagree with the others. Resolving them once, at compile time, leaves
exactly one place where a default is decided and turns every runtime loader
into plain deserialisation.

The codec below is generic rather than hand-written per class: there are around
twenty dataclasses across the eight sections, and hand-rolled ``from_dict``
methods for each would be both more code and one more thing to drift.
"""

from __future__ import annotations

import enum
import hashlib
import json
import logging
import types
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
from typing import Any, TypeVar, Union, get_args, get_origin, get_type_hints

from edumatcher.alf_gwy.config import AlfGatewayConfig
from edumatcher.config import COMPILED_CONFIG_FILE
from edumatcher.api_gateway.config import ApiGatewayConfig
from edumatcher.balf_gwy.config import BalfGatewayConfig
from edumatcher.dc_gateway.config import DcGatewayConfig
from edumatcher.engine.config_loader import EngineConfig
from edumatcher.log_srv.config import LogClientConfig, LogServerConfig
from edumatcher.md_gateway.config import MarketDataGatewayConfig
from edumatcher.ralf_gateway.config import RalfGatewayConfig

# Bumped whenever the artifact's shape changes in a way an older reader would
# misinterpret. A process that meets an unknown version refuses to start rather
# than guessing — see `load_compiled_config`.
SCHEMA_VERSION = 3

T = TypeVar("T")


class ArtifactError(Exception):
    """The artifact is absent, unreadable, or of an unusable schema version."""


@dataclass(frozen=True)
class ArtifactMeta:
    """Provenance for one compiled artifact.

    ``source_path`` and ``source_sha256`` describe the YAML this was built
    from. They exist so a process can notice that the authored file has moved
    on since the last compile — the one failure the compile step introduces
    that the previous arrangement did not have.
    """

    schema_version: int
    compiler_version: str
    compiled_at: str
    source_path: str
    source_sha256: str
    #: SHA-256 over every section *except* this meta block, so the artifact
    #: carries a digest of its own payload. Recomputed and checked on every
    #: load, which is what distinguishes a compiled artifact from a file that
    #: merely looks like one: a hand-edit after deployment no longer passes
    #: silently.
    #:
    #: This detects modification, not malice. The digest travels inside the
    #: file it protects, so anyone who edits the payload can recompute it —
    #: proving provenance rather than integrity would need a signature over a
    #: key the artifact does not carry.
    content_sha256: str = ""


@dataclass(frozen=True)
class CompiledConfig:
    """Everything every EduMatcher process needs, already resolved.

    One field per consumer. A section is present even when its subsystem is
    disabled, because "disabled" is itself a resolved value and a reader should
    never have to distinguish absent-from-the-artifact from off.
    """

    meta: ArtifactMeta
    engine: EngineConfig
    alf_gateway: AlfGatewayConfig
    balf_gateway: BalfGatewayConfig
    market_data_gateway: MarketDataGatewayConfig
    post_trade_gateway: RalfGatewayConfig
    dc_gateway: DcGatewayConfig
    log_server: LogServerConfig
    log_client: LogClientConfig
    api_gateways: dict[str, ApiGatewayConfig]


# ---------------------------------------------------------------------------
# Generic dataclass <-> JSON codec
# ---------------------------------------------------------------------------


def to_jsonable(value: Any) -> Any:
    """Convert a dataclass tree into JSON-safe primitives.

    Enum members are written as their ``value``. Every enum in the config tree
    subclasses ``str``, so this also keeps the artifact readable by eye — a
    reviewer should be able to diff two compiles without a decoder.
    """
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_jsonable(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, Path):
        # Written as text, and absolute: the artifact is read by processes
        # started from arbitrary working directories, so a relative path here
        # would resolve differently per process.
        return str(value)
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    return value


def _is_optional(tp: Any) -> bool:
    return get_origin(tp) in (Union, types.UnionType) and type(None) in get_args(tp)


def _unwrap_optional(tp: Any) -> Any:
    """Return the single non-None member of an optional annotation."""
    remaining = [a for a in get_args(tp) if a is not type(None)]
    return remaining[0] if len(remaining) == 1 else Any


def from_jsonable(tp: Any, value: Any) -> Any:
    """Rebuild a typed value of annotation *tp* from decoded JSON.

    Deliberately strict about ``None``: an optional field decodes to ``None``
    and nothing else. Absent and zero are different facts throughout this
    codebase, and a codec that quietly substituted one for the other would
    undo that everywhere at once.
    """
    if tp is Any:
        return value
    if isinstance(tp, str):
        # An annotation written as `list["Thing"]` rather than `list[Thing]`.
        # `get_type_hints` resolves the outer string but leaves the argument a
        # plain `str`, and this decoder would then hand back the raw dict —
        # producing a config whose nested values look right in JSON and are
        # the wrong type in Python. Refuse instead of degrading quietly.
        raise ArtifactError(
            f"annotation {tp!r} could not be resolved to a type. Remove the "
            f"quotes around it: `from __future__ import annotations` already "
            f"makes the whole annotation lazy."
        )
    if _is_optional(tp):
        return None if value is None else from_jsonable(_unwrap_optional(tp), value)
    if value is None:
        return None

    origin = get_origin(tp)
    if origin is list:
        args = get_args(tp)
        item_tp = args[0] if args else Any
        return [from_jsonable(item_tp, v) for v in value]
    if origin is tuple:
        # JSON has no tuple, so `to_jsonable` wrote a list. Rebuilding the
        # tuple matters for equality: a config whose `allowed_roles` came back
        # as a list would compare unequal to the one that was compiled.
        args = get_args(tp)
        if not args:
            return tuple(value)
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(from_jsonable(args[0], v) for v in value)
        return tuple(from_jsonable(arg, v) for arg, v in zip(args, value))
    if origin is dict:
        key_tp, val_tp = get_args(tp) or (Any, Any)
        return {
            from_jsonable(key_tp, k): from_jsonable(val_tp, v) for k, v in value.items()
        }
    if tp is Path:
        return Path(value)
    if isinstance(tp, type) and issubclass(tp, enum.Enum):
        return tp(value)
    if is_dataclass(tp) and isinstance(tp, type):
        hints = get_type_hints(tp)
        kwargs = {
            f.name: from_jsonable(hints[f.name], value[f.name])
            for f in fields(tp)
            if f.name in value
        }
        return tp(**kwargs)
    return value


# ---------------------------------------------------------------------------
# Artifact text
# ---------------------------------------------------------------------------


def load_compiled_config(path: Path | None = None) -> CompiledConfig | None:
    """Read the deployed artifact, or ``None`` when none has been deployed.

    Absence and corruption are treated differently, deliberately.

    *Absence* is a legitimate state — a fresh data directory before the first
    ``pm-config-deploy`` — and returning ``None`` lets each caller fall back to
    the same defaults it used to fall back to when the YAML was missing. That
    matters because roughly twenty processes read the logging sections alone,
    including read-only tools like ``pm-calf-spy`` and ``pm-viewer`` that have
    no business demanding a configured exchange.

    *Corruption*, or an artifact this build cannot read, raises. A deployed
    file that cannot be parsed is not a fresh install; quietly substituting
    defaults there is how a process ends up running settings nobody chose.
    """
    target = COMPILED_CONFIG_FILE if path is None else path
    if not target.exists():
        return None
    return decode(target.read_text(encoding="utf-8"))


def staleness(config: CompiledConfig) -> str | None:
    """Return a warning when the authored source has changed since compiling.

    Compiling introduces exactly one failure mode the previous arrangement did
    not have: editing the YAML and forgetting to deploy, so the exchange keeps
    running the previous configuration while the file on disk says otherwise.
    This is the check for it.

    The comparison is against ``meta.source_path`` — the file the operator
    edits — not against the copy deploy leaves beside the artifact, which is
    by construction the exact bytes that were compiled and could never differ.

    Returns ``None`` when the source is unreachable. A configuration compiled
    on another machine, or from a file since moved, is not evidence of
    staleness, and warning about it would train people to ignore the warning.
    """
    source = Path(config.meta.source_path)
    try:
        if not source.is_file():
            return None
        current = source_digest(source.read_text(encoding="utf-8"))
    except OSError:
        return None

    if current == config.meta.source_sha256:
        return None
    return (
        f"{source} has changed since the running configuration was compiled "
        f"at {config.meta.compiled_at} — this exchange is still running the "
        f"previous one. Run pm-config-deploy to pick up the edit."
    )


def report_deployment(log: logging.Logger) -> None:
    """Log which configuration a starting process is about to run.

    Called by every process that reads the exchange configuration, so that
    "which config is this running?" is answerable from the log alone — the
    question that took an afternoon to answer when each process resolved its
    own path.
    """
    try:
        config = load_compiled_config()
    except ArtifactError as exc:
        log.error("cannot read the deployed configuration: %s", exc)
        raise

    if config is None:
        log.warning(
            "no compiled configuration at %s — running on built-in defaults. "
            "Run pm-config-deploy to install one.",
            COMPILED_CONFIG_FILE,
        )
        return

    log.info(
        "using compiled config %s (compiled %s from %s)",
        COMPILED_CONFIG_FILE,
        config.meta.compiled_at,
        config.meta.source_path,
    )
    warning = staleness(config)
    if warning:
        log.warning("%s", warning)


def source_digest(text: str) -> str:
    """Return the SHA-256 of an authored config's text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _payload_text(payload: dict[str, Any]) -> str:
    """Deterministic JSON for a decoded artifact body."""
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def content_digest(config: CompiledConfig) -> str:
    """Return the SHA-256 of everything in *config* except its meta block.

    Meta is excluded because the digest lives there; including it would be
    self-referential. Excluding it also means a recompile of an unchanged
    source produces an unchanged digest even though ``compiled_at`` moved on,
    so the digest answers "is this the same configuration?" rather than "was
    this the same compile run?".
    """
    payload = to_jsonable(config)
    payload.pop("meta", None)
    return hashlib.sha256(_payload_text(payload).encode("utf-8")).hexdigest()


def encode(config: CompiledConfig) -> str:
    """Serialise to deterministic JSON text.

    Sorted keys and a fixed indent, so recompiling an unchanged source yields a
    byte-identical file. That makes "did the configuration change?" answerable
    with a checksum, and keeps a redeploy from looking like an edit.
    """
    payload = to_jsonable(config)
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def decode(text: str) -> CompiledConfig:
    """Parse artifact text, rejecting a schema version this build cannot read."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ArtifactError(f"compiled config is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise ArtifactError("compiled config must be a JSON object")

    meta = payload.get("meta")
    if not isinstance(meta, dict) or "schema_version" not in meta:
        raise ArtifactError("compiled config has no meta.schema_version")

    version = meta["schema_version"]
    if version != SCHEMA_VERSION:
        raise ArtifactError(
            f"compiled config has schema version {version}, but this build "
            f"reads version {SCHEMA_VERSION} — recompile with pm-config-compile"
        )

    result = from_jsonable(CompiledConfig, payload)
    assert isinstance(result, CompiledConfig)

    # A recorded digest that no longer matches means the artifact was changed
    # after it was compiled — the sections and the meta block now describe
    # different configurations. Treat that as corruption rather than as a new
    # configuration, because whatever is in the file was never validated.
    recorded = result.meta.content_sha256
    if recorded:
        actual = content_digest(result)
        if actual != recorded:
            raise ArtifactError(
                "compiled config has been modified since it was compiled "
                f"(payload digest {actual[:12]}… does not match the recorded "
                f"{recorded[:12]}…) — edit the source and run pm-config-deploy "
                "rather than editing the deployed artifact"
            )
    return result


__all__ = [
    "SCHEMA_VERSION",
    "ArtifactError",
    "ArtifactMeta",
    "CompiledConfig",
    "content_digest",
    "decode",
    "encode",
    "load_compiled_config",
    "report_deployment",
    "staleness",
    "from_jsonable",
    "source_digest",
    "to_jsonable",
]
