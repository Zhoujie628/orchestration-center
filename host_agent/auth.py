from __future__ import annotations

from typing import Any, Protocol

from fastapi import Request


class HostAuthenticationProvider(Protocol):
    """Optional authentication endpoint supplied by the host application."""

    @property
    def login_path(self) -> str: ...

    async def authenticate(self, request: Request) -> Any: ...
