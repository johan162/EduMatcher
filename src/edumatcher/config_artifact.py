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
import types
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
from typing import Any, TypeVar, Union, get_args, get_origin, get_type_hints

from edumatcher.alf_gwy.config import AlfGatewayConfig
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
SCHEMA_VERSION = 1

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


def source_digest(text: str) -> str:
    """Return the SHA-256 of an authored config's text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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
    return result


__all__ = [
    "SCHEMA_VERSION",
    "ArtifactError",
    "ArtifactMeta",
    "CompiledConfig",
    "decode",
    "encode",
    "from_jsonable",
    "source_digest",
    "to_jsonable",
]
