from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HostAgentConfig:
    """Runtime settings supplied by the host application's composition root."""

    orchestration_url: str
    registry_url: str
    ssl_verify: bool = False
    max_negotiation_exchanges: int = 3

    def __post_init__(self) -> None:
        if not self.orchestration_url:
            raise ValueError("orchestration_url is required")
        if not self.registry_url:
            raise ValueError("registry_url is required")
        if self.max_negotiation_exchanges < 1:
            raise ValueError("max_negotiation_exchanges must be positive")


@dataclass(frozen=True, slots=True)
class ControlPointContext:
    """Request-scoped values made available to a business policy factory."""

    orchestration_url: str
    ssl_verify: bool
    lang: str
