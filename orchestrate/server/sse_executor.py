# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""Shared SSE execution endpoint.

The orchestration center does NOT execute workflows itself. It sends
the intent to the Workbench Agent via A2A-T, which searches/loads the
PSOP, executes the workflow, and streams SDK events back as A2A-T
TaskUpdate metadata (__sdk_event__). This module drains the stream
and forwards events to the frontend SSE.
"""

import json
from typing import List

from a2a.types import AgentCard
from fastapi.responses import StreamingResponse

from orchestrate.runtime.exec_engine import OrchestrationEngine


async def dispatch_intent_sse(
    agent_cards: List[AgentCard],
    intent: str,
    target_agent: str = None,
    lang: str = None,
) -> StreamingResponse:
    """Dispatch an intent to a host agent via A2A-T and stream events.

    Slim orchestration: the orchestration center does NOT execute the
    workflow itself. It sends the intent to the target host agent, which
    searches/loads the PSOP, executes it via the SDK, and streams SDK
    events back as A2A-T TaskUpdate metadata (__sdk_event__).

    This function drains the A2A-T response stream, extracts the SDK
    events from metadata, and forwards them to the frontend SSE.
    """
    engine = OrchestrationEngine(agent_cards, target_agent=target_agent, lang=lang)

    async def stream():
        async for event in engine.events(intent):
            yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
