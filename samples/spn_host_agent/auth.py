from __future__ import annotations

import secrets
import time

from fastapi import Request
from starlette.responses import JSONResponse


class SampleFixedCredentialAuth:
    """Demo-only login endpoint used by the bundled sample AgentCards."""

    login_path = "/rest/plat/smapp/v1/oauth/token"

    def __init__(
        self,
        *,
        username: str = "admin",
        password: str = "Admin@123",
        token_ttl_seconds: int = 3600,
    ) -> None:
        self._username = username
        self._password = password
        self._token_ttl_seconds = token_ttl_seconds
        self._valid_tokens: dict[str, float] = {}

    async def authenticate(self, request: Request):
        content_type = request.headers.get("content-type", "")
        try:
            if "json" in content_type:
                body = await request.json()
            elif "form" in content_type:
                form = await request.form()
                body = dict(form)
            else:
                body = {}
        except Exception:
            body = {}

        username = body.get("userName") or body.get("username")
        password = body.get("value") or body.get("password")
        if username != self._username or password != self._password:
            return JSONResponse(status_code=401, content={"error": "Invalid credentials"})

        token = secrets.token_urlsafe(24)
        self._valid_tokens[token] = time.time() + self._token_ttl_seconds
        return {"accessSession": token}
