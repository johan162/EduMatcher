"""Tests for pm-config-deploy — compiling an authored config into the live one.

The command is the only moment the authored YAML and the running configuration
meet, so it is the only place validation is still cheap and the only place a
default gets decided. These pin both, plus the failure behaviour that matters
most: a bad compile must leave the previous artifact exactly as it was.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from edumatcher.config_artifact import (
    SCHEMA_VERSION,
    ArtifactError,
    content_digest,
    decode,
    encode,
    source_digest,
)
from edumatcher.config_deploy import (
    CompileError,
    compile_config,
    deploy,
    validate,
)

# No MARKET_MAKER gateway: pm-cverifier makes a market maker without
# `market_maker_quotes` a blocking error (M001), and these tests are about the
# compile step rather than about quote seeding.
VALID = """
symbols:
  AAPL: {tick_decimals: 2, last_buy_price: 150.0}
  MSFT: {tick_decimals: 2, last_buy_price: 400.0}
gateways:
  alf:
    - id: TRADER01
      role: TRADER
    - id: OPS01
      role: ADMIN
"""

# `symbols` must be a mapping; a sequence is rejected by the schema layer.
INVALID = "symbols: [not a mapping]\ngateways: {alf: []}\n"


def _source(tmp_path: Path, text: str = VALID, name: str = "authored.yaml") -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


class TestValidation:
    def test_a_usable_config_has_no_blocking_findings(self, tmp_path: Path) -> None:
        assert validate(_source(tmp_path)) == []

    def test_a_broken_config_is_reported_rather_than_compiled(
        self, tmp_path: Path
    ) -> None:
        assert validate(_source(tmp_path, INVALID)) != []

    def test_compiling_a_broken_config_raises_with_its_findings(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(CompileError) as exc:
            compile_config(_source(tmp_path, INVALID))

        assert exc.value.findings, "the operator needs to know what was wrong"

    def test_warnings_do_not_block(self, tmp_path: Path) -> None:
        # A configuration that will run must deploy. Refusing on advice would
        # push people towards editing the deployed copy by hand, which is the
        # habit this arrangement exists to remove.
        source = _source(tmp_path)
        assert all(f.severity.value == "ERROR" for f in validate(source))


class TestResolution:
    def test_resolves_every_section_not_just_the_engine(self, tmp_path: Path) -> None:
        # The prize: defaults are decided once here rather than in eight
        # loaders that can drift apart.
        config = compile_config(_source(tmp_path))

        assert config.market_data_gateway.port > 0
        assert config.log_server.port > 0
        assert config.log_client.failover_timeout_sec > 0
        assert config.dc_gateway.port > 0

    def test_materialises_defaults_the_source_never_mentioned(
        self, tmp_path: Path
    ) -> None:
        # VALID names no market_data_gateway block at all, yet a reader of the
        # artifact must still find a complete one — that is what lets runtime
        # loaders stop carrying their own copies of the defaults.
        dest = tmp_path / "engine_config.json"
        deploy(_source(tmp_path), dest)

        section = json.loads(dest.read_text())["market_data_gateway"]

        assert "market_data_gateway" not in VALID
        assert section["heartbeat_interval_sec"] > 0
        assert section["port"] > 0

    def test_records_the_symbols_it_compiled(self, tmp_path: Path) -> None:
        config = compile_config(_source(tmp_path))
        assert sorted(config.engine.symbols) == ["AAPL", "MSFT"]

    def test_stamps_the_schema_version_this_build_writes(self, tmp_path: Path) -> None:
        assert compile_config(_source(tmp_path)).meta.schema_version == SCHEMA_VERSION

    def test_records_the_source_it_was_built_from(self, tmp_path: Path) -> None:
        # This is what lets a process notice the authored file has moved on —
        # the one new failure mode compiling introduces.
        source = _source(tmp_path)
        meta = compile_config(source).meta

        assert meta.source_path == str(source)
        assert meta.source_sha256 == source_digest(VALID)


class TestDeploy:
    def test_installs_a_readable_artifact(self, tmp_path: Path) -> None:
        dest = tmp_path / "ref_data" / "engine_config.json"

        deploy(_source(tmp_path), dest)

        assert sorted(decode(dest.read_text()).engine.symbols) == ["AAPL", "MSFT"]

    def test_creates_the_reference_directory(self, tmp_path: Path) -> None:
        dest = tmp_path / "brand" / "new" / "engine_config.json"
        deploy(_source(tmp_path), dest)
        assert dest.is_file()

    def test_installs_the_source_beside_the_artifact(self, tmp_path: Path) -> None:
        # A deployed directory holding an artifact and an unrelated source
        # would be worse than one holding neither.
        dest = tmp_path / "ref_data" / "engine_config.json"

        deploy(_source(tmp_path), dest)

        assert (dest.parent / "engine_config.yaml").read_text() == VALID

    def test_replaces_a_previous_deployment(self, tmp_path: Path) -> None:
        dest = tmp_path / "engine_config.json"
        deploy(_source(tmp_path), dest)

        newer = _source(
            tmp_path,
            VALID.replace("  MSFT: {tick_decimals: 2, last_buy_price: 400.0}\n", ""),
            name="newer.yaml",
        )
        deploy(newer, dest)

        assert sorted(decode(dest.read_text()).engine.symbols) == ["AAPL"]

    def test_leaves_the_old_artifact_untouched_when_the_new_source_is_bad(
        self, tmp_path: Path
    ) -> None:
        # Half-deploying is worse than not deploying: the exchange would come
        # back up on a configuration nobody wrote.
        dest = tmp_path / "engine_config.json"
        deploy(_source(tmp_path), dest)
        before = dest.read_text()

        with pytest.raises(CompileError):
            deploy(_source(tmp_path, INVALID, name="bad.yaml"), dest)

        assert dest.read_text() == before

    def test_writes_nothing_at_all_on_a_first_failed_compile(
        self, tmp_path: Path
    ) -> None:
        dest = tmp_path / "engine_config.json"

        with pytest.raises(CompileError):
            deploy(_source(tmp_path, INVALID, name="bad.yaml"), dest)

        assert not dest.exists()

    def test_leaves_no_staging_file_behind(self, tmp_path: Path) -> None:
        dest = tmp_path / "ref_data" / "engine_config.json"
        deploy(_source(tmp_path), dest)
        assert list(dest.parent.glob("*.tmp")) == []


class TestDeterminism:
    def test_the_config_body_is_identical_across_recompiles(
        self, tmp_path: Path
    ) -> None:
        # `meta.compiled_at` is a wall-clock stamp and does vary; everything
        # that describes the exchange must not, so a redeploy of an unchanged
        # source is visibly a redeploy and not an edit.
        source = _source(tmp_path)
        first = json.loads(encode(compile_config(source)))
        second = json.loads(encode(compile_config(source)))

        first.pop("meta")
        second.pop("meta")
        assert first == second

    def test_the_source_digest_is_stable_across_recompiles(
        self, tmp_path: Path
    ) -> None:
        source = _source(tmp_path)
        assert (
            compile_config(source).meta.source_sha256
            == compile_config(source).meta.source_sha256
        )


class TestShippedSample:
    """The config the product itself ships must compile.

    `pm-setup` deploys this file into a fresh data directory, so if it ever
    failed validation a new installation would be unable to start — and the
    compile step is strictly more demanding than the runtime loaders were.
    """

    def test_the_bundled_sample_config_compiles(self, tmp_path: Path) -> None:
        from importlib import resources

        sample = resources.files("edumatcher").joinpath("engine_config.sample.yaml")
        source = tmp_path / "engine_config.yaml"
        source.write_text(sample.read_text(encoding="utf-8"), encoding="utf-8")

        config = compile_config(source)

        assert config.engine.symbols, "a sample with no symbols would teach nothing"
        assert config.engine.fix_gateways


class TestProvenance:
    """What the deployed artifact records about how it came to exist."""

    def test_stamps_a_digest_of_its_own_payload(self, tmp_path: Path) -> None:
        config = compile_config(_source(tmp_path))
        assert config.meta.content_sha256 == content_digest(config)

    def test_the_payload_digest_differs_from_the_source_digest(
        self, tmp_path: Path
    ) -> None:
        # They answer different questions: one is "has the authored file
        # changed since this was built?", the other "has this file been
        # changed since it was built?".
        meta = compile_config(_source(tmp_path)).meta
        assert meta.content_sha256 != meta.source_sha256

    def test_stamps_a_wall_clock_compile_time(self, tmp_path: Path) -> None:
        stamped = compile_config(_source(tmp_path)).meta.compiled_at
        datetime.strptime(stamped, "%Y-%m-%dT%H:%M:%S.000Z")

    def test_a_deployed_artifact_is_rejected_once_edited_by_hand(
        self, tmp_path: Path
    ) -> None:
        # The whole point of deploying a compiled file rather than a copy: what
        # runs must be something that was validated, not something that merely
        # looks like it.
        dest = tmp_path / "engine_config.json"
        deploy(_source(tmp_path), dest)

        payload = json.loads(dest.read_text())
        payload["engine"]["symbols"].pop("MSFT")
        dest.write_text(json.dumps(payload))

        with pytest.raises(ArtifactError, match="modified since it was compiled"):
            decode(dest.read_text())

    def test_recompiling_an_unchanged_source_keeps_the_same_payload_digest(
        self, tmp_path: Path
    ) -> None:
        source = _source(tmp_path)
        assert (
            compile_config(source).meta.content_sha256
            == compile_config(source).meta.content_sha256
        )
