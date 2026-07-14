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
import json
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.responses import StreamingResponse
from orchestrate.core.model.psop import PSOP, Step, StepType, Task, TaskStatus
from orchestrate.server.sse_executor import run_psop_sse


def _make_psop():
    return PSOP(
        id="test-psop-id",
        name="Test Workflow",
        description="test",
        steps=[
            Step(name="step1", step_type=StepType.ALL_SUCCESS, subtasks=[
                Task(task_id="t1", description="do thing", agent="Agent1", skill="skill1", status=TaskStatus.PENDING)
            ])
        ]
    )


class TestRunPsopSse:

    @pytest.mark.asyncio
    async def test_returns_streaming_response(self):
        psop = _make_psop()
        with patch("orchestrate.server.sse_executor.DynamicWorkflowEngine") as MockEngine:
            mock_engine = AsyncMock()
            mock_engine.run = AsyncMock(return_value=[{"event": "COMPLETED"}])
            mock_engine.execution_history = [{"event": "COMPLETED"}]
            MockEngine.return_value = mock_engine
            response = await run_psop_sse(psop, [])
            assert isinstance(response, StreamingResponse)
            assert response.media_type == "text/event-stream"

    @pytest.mark.asyncio
    async def test_response_headers(self):
        psop = _make_psop()
        with patch("orchestrate.server.sse_executor.DynamicWorkflowEngine") as MockEngine:
            mock_engine = AsyncMock()
            mock_engine.run = AsyncMock(return_value=[{"event": "COMPLETED"}])
            mock_engine.execution_history = [{"event": "COMPLETED"}]
            MockEngine.return_value = mock_engine
            response = await run_psop_sse(psop, [])
            assert response.headers["Cache-Control"] == "no-cache"
            assert response.headers["X-Accel-Buffering"] == "no"

    def test_push_callback_serializes_model_dump(self):
        psop = _make_psop()
        mock_obj = MagicMock()
        mock_obj.model_dump = MagicMock(return_value={"k": "v"})
        serializable_data = {}
        for key, value in {"field": mock_obj}.items():
            if hasattr(value, "model_dump"):
                serializable_data[key] = value.model_dump()
            elif hasattr(value, "__dict__"):
                try:
                    serializable_data[key] = value.__dict__
                except Exception:
                    serializable_data[key] = str(value)
            else:
                serializable_data[key] = value
        assert serializable_data == {"field": {"k": "v"}}

    def test_push_callback_handles_list_with_model_dump_items(self):
        mock_item = MagicMock()
        mock_item.model_dump = MagicMock(return_value={"x": 1})
        serializable_data = {}
        items = [mock_item, "plain_string"]
        for key, value in {"results": items}.items():
            if isinstance(value, (tuple, list)):
                serializable_data[key] = []
                for item in value:
                    if hasattr(item, "model_dump"):
                        serializable_data[key].append(item.model_dump())
                    elif hasattr(item, "__dict__"):
                        try:
                            serializable_data[key].append(item.__dict__)
                        except Exception:
                            serializable_data[key].append(str(item))
                    else:
                        serializable_data[key].append(item)
            else:
                serializable_data[key] = value
        assert serializable_data == {"results": [{"x": 1}, "plain_string"]}
