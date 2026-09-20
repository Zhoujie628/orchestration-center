from pathlib import Path

from fastapi.testclient import TestClient

from host_agent.service import create_agent_app
from orchestrate import AgentCardLoader
from samples.spn_host_agent.auth import SampleFixedCredentialAuth


class _Executor:
    async def execute(self, context, event_queue):
        del context, event_queue

    async def cancel(self, context, event_queue):
        del context, event_queue


def _secured_agent_card():
    cards = AgentCardLoader(
        Path(__file__).resolve().parents[1] / "samples" / "agentcard"
    ).get_all_agent_cards()
    return next(card for card in cards if card.name == "SPN Domain Agent City1")


def test_generic_host_server_does_not_install_demo_login_route():
    app = create_agent_app(_secured_agent_card(), _Executor())

    response = TestClient(app).post(
        "/rest/plat/smapp/v1/oauth/token",
        json={"username": "admin", "password": "Admin@123"},
    )

    assert response.status_code == 404


def test_sample_auth_provider_owns_demo_credentials():
    app = create_agent_app(
        _secured_agent_card(),
        _Executor(),
        auth_provider=SampleFixedCredentialAuth(),
    )
    client = TestClient(app)

    rejected = client.post(
        "/rest/plat/smapp/v1/oauth/token",
        json={"username": "admin", "password": "wrong"},
    )
    accepted = client.post(
        "/rest/plat/smapp/v1/oauth/token",
        json={"username": "admin", "password": "Admin@123"},
    )

    assert rejected.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json()["accessSession"]
