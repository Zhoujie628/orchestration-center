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
