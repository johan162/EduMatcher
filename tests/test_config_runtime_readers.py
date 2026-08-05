"""Every subsystem reads its section from the compiled artifact.

Before this, eight modules each parsed the same YAML and each carried its own
copy of the defaults for its section, with nothing keeping those copies in
step. These tests pin the two properties that replaced that: a deployed
artifact is what every loader returns, and the absence of one still yields the
same defaults the YAML loaders used to fall back to.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

import pytest

from edumatcher.alf_gwy.config import AlfGatewayConfig, load_default_alf_gateway_config
from edumatcher.api_gateway.config import (
    ApiGatewayConfig,
    load_default_api_gateway_config,
)
from edumatcher.balf_gwy.config import (
    BalfGatewayConfig,
    load_default_balf_gateway_config,
)
from edumatcher.config_artifact import decode, report_deployment, staleness
from edumatcher.config_deploy import deploy
from edumatcher.dc_gateway.config import DcGatewayConfig, load_default_dc_gateway_config
from edumatcher.log_srv.config import (
    LogClientConfig,
    LogServerConfig,
    load_default_log_client_config,
    load_default_log_server_config,
)
from edumatcher.md_gateway.config import (
    MarketDataGatewayConfig,
    load_default_market_data_gateway_config,
)
from edumatcher.ralf_gateway.config import (
    RalfGatewayConfig,
    load_default_ralf_gateway_config,
)

BASE = """
symbols:
  AAPL: {tick_decimals: 2, last_buy_price: 150.0}
gateways:
  alf: [{id: TRADER01, role: TRADER}]
"""

# One distinctive value per section, so a reader returning the wrong section —
# or falling back to defaults when it should not — is unmistakable.
CONFIGURED = BASE + """
alf_gateway: {port: 15565}
balf_gateway: {port: 15566}
dc_gateway: {port: 15590}
market_data_gateway: {port: 15570}
post_trade_gateway: {port: 15580}
log_server:
  port: 15600
  client: {failover_timeout_sec: 99}
api_gateways:
  desk:
    port: 18080
    # M022: a credential's gateway_id must name a configured ALF gateway.
    credentials: [{api_key: k, gateway_id: TRADER01}]
"""

# (loader, default type, attribute, configured value)
SECTIONS: list[tuple[Callable[[], Any], type, str, Any]] = [
    (load_default_alf_gateway_config, AlfGatewayConfig, "port", 15565),
    (load_default_balf_gateway_config, BalfGatewayConfig, "port", 15566),
    (load_default_dc_gateway_config, DcGatewayConfig, "port", 15590),
    (load_default_market_data_gateway_config, MarketDataGatewayConfig, "port", 15570),
    (load_default_ralf_gateway_config, RalfGatewayConfig, "port", 15580),
    (load_default_log_server_config, LogServerConfig, "port", 15600),
    (load_default_log_client_config, LogClientConfig, "failover_timeout_sec", 99.0),
    (load_default_api_gateway_config, ApiGatewayConfig, "port", 18080),
]

IDS = [tp.__name__ for _fn, tp, _attr, _val in SECTIONS]


@pytest.fixture
def deployed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[[str], Path]:
    """Compile a config and point the artifact reader at it."""

    def _deploy(text: str) -> Path:
        source = tmp_path / "authored.yaml"
        source.write_text(text)
        dest = tmp_path / "ref_data" / "engine_config.json"
        deploy(source, dest)
        monkeypatch.setattr(
            "edumatcher.config_artifact.COMPILED_CONFIG_FILE", dest, raising=True
        )
        return dest

    return _deploy


@pytest.fixture
def nothing_deployed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "edumatcher.config_artifact.COMPILED_CONFIG_FILE",
        tmp_path / "absent" / "engine_config.json",
        raising=True,
    )


@pytest.mark.parametrize("loader, default_type, attr, configured", SECTIONS, ids=IDS)
class TestSectionReaders:
    def test_reads_its_own_section_from_the_artifact(
        self,
        loader: Callable[[], Any],
        default_type: type,
        attr: str,
        configured: Any,
        deployed: Callable[[str], Path],
    ) -> None:
        deployed(CONFIGURED)
        assert getattr(loader(), attr) == configured

    def test_falls_back_to_defaults_when_nothing_is_deployed(
        self,
        loader: Callable[[], Any],
        default_type: type,
        attr: str,
        configured: Any,
        nothing_deployed: None,
    ) -> None:
        # A fresh data directory, before any pm-config-deploy. Read-only tools
        # like pm-calf-spy and pm-viewer read the logging sections and must
        # still run against an exchange whose config was never installed.
        assert getattr(loader(), attr) == getattr(default_type(), attr)

    def test_returns_the_declared_type(
        self,
        loader: Callable[[], Any],
        default_type: type,
        attr: str,
        configured: Any,
        deployed: Callable[[str], Path],
    ) -> None:
        deployed(CONFIGURED)
        assert isinstance(loader(), default_type)


class TestDefaultsAreResolvedOnce:
    def test_a_section_the_source_never_mentioned_still_arrives_complete(
        self, deployed: Callable[[str], Path]
    ) -> None:
        # BASE configures no gateways at all, yet every reader must return a
        # usable section — the defaults now come from the compile step rather
        # than from each loader's own copy.
        deployed(BASE)

        assert load_default_market_data_gateway_config().port > 0
        assert load_default_log_server_config().port > 0
        assert load_default_balf_gateway_config().port > 0

    def test_the_artifact_wins_over_a_loader_default(
        self, deployed: Callable[[str], Path]
    ) -> None:
        deployed(CONFIGURED)
        assert load_default_market_data_gateway_config().port != (
            MarketDataGatewayConfig().port
        )


class TestCorruptionIsNotSilentlyIgnored:
    def test_an_unreadable_artifact_raises_rather_than_yielding_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Absence is a fresh install; corruption is not. Substituting defaults
        # for a deployed file that cannot be parsed is how a process ends up
        # running settings nobody chose.
        from edumatcher.config_artifact import ArtifactError

        broken = tmp_path / "engine_config.json"
        broken.write_text("{ not json")
        monkeypatch.setattr(
            "edumatcher.config_artifact.COMPILED_CONFIG_FILE", broken, raising=True
        )

        with pytest.raises(ArtifactError):
            load_default_market_data_gateway_config()

    def test_an_artifact_from_a_future_build_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import json

        from edumatcher.config_artifact import ArtifactError

        source = tmp_path / "authored.yaml"
        source.write_text(BASE)
        dest = tmp_path / "engine_config.json"
        deploy(source, dest)

        payload = json.loads(dest.read_text())
        payload["meta"]["schema_version"] = 999
        dest.write_text(json.dumps(payload))
        monkeypatch.setattr(
            "edumatcher.config_artifact.COMPILED_CONFIG_FILE", dest, raising=True
        )

        with pytest.raises(ArtifactError, match="schema version"):
            load_default_log_client_config()


class TestStaleness:
    """Compiling introduces one new failure mode: editing and forgetting.

    Nothing else in this design can go wrong that could not go wrong before, so
    this is the check that has to earn its place.
    """

    def test_a_freshly_deployed_config_is_not_stale(self, tmp_path: Path) -> None:
        source = tmp_path / "authored.yaml"
        source.write_text(BASE)
        dest = tmp_path / "engine_config.json"
        deploy(source, dest)

        assert staleness(decode(dest.read_text())) is None

    def test_an_edited_source_is_reported_as_stale(self, tmp_path: Path) -> None:
        source = tmp_path / "authored.yaml"
        source.write_text(BASE)
        dest = tmp_path / "engine_config.json"
        deploy(source, dest)

        source.write_text(BASE.replace("AAPL", "MSFT"))

        warning = staleness(decode(dest.read_text()))
        assert warning is not None
        assert "pm-config-deploy" in warning

    def test_a_whitespace_only_edit_still_counts(self, tmp_path: Path) -> None:
        # The digest answers "was this built from this exact file?", so a
        # reformat should prompt a recompile rather than pass unnoticed.
        source = tmp_path / "authored.yaml"
        source.write_text(BASE)
        dest = tmp_path / "engine_config.json"
        deploy(source, dest)

        source.write_text(BASE + "\n")

        assert staleness(decode(dest.read_text())) is not None

    def test_an_unreachable_source_is_not_reported_as_stale(
        self, tmp_path: Path
    ) -> None:
        # A config compiled on another machine, or from a file since moved, is
        # not evidence of staleness — warning about it would train people to
        # ignore the warning.
        source = tmp_path / "authored.yaml"
        source.write_text(BASE)
        dest = tmp_path / "engine_config.json"
        deploy(source, dest)
        source.unlink()

        assert staleness(decode(dest.read_text())) is None


class TestDeploymentReport:
    def test_warns_when_nothing_is_deployed(
        self, nothing_deployed: None, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level("INFO"):
            report_deployment(logging.getLogger("test"))

        assert "no compiled configuration" in caplog.text
        assert "pm-config-deploy" in caplog.text

    def test_names_the_artifact_and_its_source(
        self, deployed: Callable[[str], Path], caplog: pytest.LogCaptureFixture
    ) -> None:
        # "Which configuration is this process running?" must be answerable
        # from the log alone — the question that took an afternoon to answer
        # when every process resolved its own path.
        deployed(CONFIGURED)

        with caplog.at_level("INFO"):
            report_deployment(logging.getLogger("test"))

        assert "using compiled config" in caplog.text
        assert "authored.yaml" in caplog.text

    def test_warns_that_the_source_has_moved_on(
        self,
        tmp_path: Path,
        deployed: Callable[[str], Path],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        deployed(CONFIGURED)
        (tmp_path / "authored.yaml").write_text(CONFIGURED + "\n")

        with caplog.at_level("INFO"):
            report_deployment(logging.getLogger("test"))

        assert "still running the previous one" in caplog.text

    def test_raises_rather_than_starting_on_an_unreadable_artifact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from edumatcher.config_artifact import ArtifactError

        broken = tmp_path / "engine_config.json"
        broken.write_text("{ not json")
        monkeypatch.setattr(
            "edumatcher.config_artifact.COMPILED_CONFIG_FILE", broken, raising=True
        )

        with pytest.raises(ArtifactError):
            report_deployment(logging.getLogger("test"))
