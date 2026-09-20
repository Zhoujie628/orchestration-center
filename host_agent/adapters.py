from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from workflow_engine import A2ATransport, RegistryClient, WorkflowEngineClient


class AgentCardProvider(Protocol):
    async def load(self) -> list[Any]: ...


class EngineClientFactory(Protocol):
    def create(self, agent_cards: list[Any]): ...


class RegistryAgentCardProvider:
    """Load the current AgentCards from a registry service."""

    def __init__(self, registry_url: str, *, ssl_verify: bool = False) -> None:
        self._registry_url = registry_url
        self._ssl_verify = ssl_verify

    async def load(self) -> list[Any]:
        registry = RegistryClient(self._registry_url, ssl_verify=self._ssl_verify)
        return await registry.fetch_agent_cards()


class DefaultEngineClientFactory:
    """Build an owning workflow-engine client for one HostAgent execution."""

    def __init__(
        self,
        *,
        credentials_config: str | dict | None = None,
        ssl_verify: bool = False,
        max_negotiation_exchanges: int = 3,
        transport_factory: Callable[..., Any] = A2ATransport,
    ) -> None:
        self._credentials_config = credentials_config
        self._ssl_verify = ssl_verify
        self._max_negotiation_exchanges = max_negotiation_exchanges
        self._transport_factory = transport_factory

    def create(self, agent_cards: list[Any]):
        transport = self._transport_factory(
            agent_cards=agent_cards,
            credentials_config=self._credentials_config,
            ssl_verify=self._ssl_verify,
        )
        return WorkflowEngineClient.owning(
            transport,
            max_negotiation_exchanges=self._max_negotiation_exchanges,
        )
