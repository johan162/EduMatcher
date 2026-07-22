"""DC drop-copy TCP gateway package."""

from edumatcher.dc_gateway.config import DcGatewayConfig
from edumatcher.dc_gateway.gateway import DcGateway

__all__ = ["DcGateway", "DcGatewayConfig"]
