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

The lifecycle (event stream, start/complete/error/close, cancellation,
event collection) is owned by the a2at-engine SDK runner
(``execute_psop`` via ``DynamicWorkflowEngine.events()``). This module is
the business/transport layer only: it drains the SDK event stream into an
SSE ``StreamingResponse`` and persists an ``ExecutionRecord`` via the
``on_finish`` hook.
"""

import json
from datetime import datetime, timezone
from typing import List

from a2a.types import AgentCard
from fastapi.responses import StreamingResponse
from loguru import logger

from common.custom.default_handle import HandlerRegistry
from common.custom.interface_type import InterfaceType
from orchestrate.core.model.execution_record import ExecutionRecord, ExecutionStatus
from orchestrate.core.model.psop import PSOP
from orchestrate.runtime.exec_engine import DynamicWorkflowEngine


async def run_psop_sse(
    psop: PSOP,
    agent_cards: List[AgentCard],
    runtime_intent: str = None,
    lang: str = None,
) -> StreamingResponse:
    """Execute a PSOP workflow and return an SSE stream.

    The SDK owns the event stream + lifecycle + cancellation; this function
    only wires the persistence hook (on_finish) and drains events into SSE.
    """
    started_at = datetime.now(timezone.utc)
    engine = DynamicWorkflowEngine(psop, agent_cards, runtime_intent=runtime_intent, lang=lang)

    async def on_finish(result, events):
        try:
            final_psop = psop.model_dump() if hasattr(psop, "model_dump") else str(psop)
            if result.success:
                status = ExecutionStatus.SUCCESS
            elif result.error and "cancelled" in result.error.lower():
                status = ExecutionStatus.STOPPED
            else:
                status = ExecutionStatus.FAILED
            record = ExecutionRecord(
                psop_id=psop.id,
                psop_name=getattr(psop, "name", ""),
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                status=status,
                execution_history=result.history,
                final_psop=final_psop,
                events=events,
                error=result.error,
            )
            handler = HandlerRegistry.get_handler(InterfaceType.SAVE_EXECUTION_RECORD)
            handler.handle(record)
            logger.info(f"Execution record saved: {record.execution_id}")
        except Exception as e:
            logger.error(f"Failed to save execution record: {e}")

    async def stream():
        async for event in engine.events(on_finish=on_finish):
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
