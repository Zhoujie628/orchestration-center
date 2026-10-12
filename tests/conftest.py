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

"""Shared pytest fixtures for the orchestration-center test suite."""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure the project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
   sys.path.insert(0, str(PROJECT_ROOT))

@pytest.fixture(autouse=True)
def _suppress_module_side_effects(monkeypatch):
   """Prevent module-level singletons (e.g. audit_logger) from
   performing I/O during test collection."""
   monkeypatch.setenv("PYTEST_RUNNING", "1")

@pytest.fixture(autouse=True)
def _dev_loopback_auth(monkeypatch):
   """Exercise the internal API without credentials, through the one
   sanctioned path: security.dev_insecure_mode on a loopback bind.

   auth_middleware answers 503 to unauthenticated internal requests unless
   the deployment opted into that dev mode, so tests that call business
   endpoints get it installed here. Tests that need authentication enabled
   patch ``orchestrate.server.auth.is_auth_enabled`` / ``get_conf`` and
   override this automatically (their monkeypatch wins).
   """
   monkeypatch.setattr(
       "orchestrate.server.auth.get_conf",
       lambda: {"ip": "127.0.0.1", "security.dev_insecure_mode": "true"},
   )

@pytest.fixture
def sample_psop_dict():
    """Return a minimal valid PSOP dictionary for tests."""
    return {
        "id": "test-psop-001",
        "name": "Test Workflow",
        "description": "A test workflow",
        "steps": [
            {
                "name": "step1",
                "type": "AllSuccess",
                "subtasks": [
                    {
                        "task_id": "t1",
                        "description": "Do something",
                        "agent": "agent_a",
                        "skill": "skill_a",
                        "status": "pending",
                    }
                ],
                "next": None,
                "layer": 0,
            }
        ],
        "tags": ["test"],
    }

@pytest.fixture
def mock_agent_card():
    """Return a mock AgentCard for tests that need one."""
    card = MagicMock()
    card.name = "mock_agent"
    card.description = "A mock agent for testing"
    skill = MagicMock()
    skill.name = "mock_skill"
    skill.description = "A mock skill"
    card.skills = [skill]
    card.security_schemes = None
    card.security_requirements = None
    card.capabilities = MagicMock()
    card.capabilities.streaming = False
    card.capabilities.extensions = []
    iface = MagicMock()
    iface.url = "http://localhost:9999"
    iface.protocol_binding = "HTTP+JSON"
    card.supported_interfaces = [iface]
    return card
