"""Tail.Link production-safety and API regression tests."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TEST_STATE = Path(tempfile.mkdtemp(prefix="tail-link-tests-"))
os.environ["TAIL_LINK_DB_PATH"] = str(TEST_STATE / "test.db")
os.environ["TAIL_LINK_ADMIN_TOKEN"] = "test-admin-token"
os.environ["TAIL_LINK_PUBLIC_URL"] = "https://www.taillink.cloud"
sys.path.insert(0, str(ROOT / "backend"))

import main  # noqa: E402
import matcher  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from models import Need, NeedType, Owner  # noqa: E402


ADMIN_HEADERS = {"X-Admin-Token": "test-admin-token"}


@pytest.fixture(scope="session")
def client():
    with TestClient(main.app) as test_client:
        yield test_client
    main.engine.dispose()
    shutil.rmtree(TEST_STATE, ignore_errors=True)


@pytest.fixture(autouse=True)
def clean_database(client):
    response = client.post("/api/admin/reset-db", headers=ADMIN_HEADERS)
    assert response.status_code == 200


def _register(client, name, owner_name):
    response = client.post("/api/register", json={
        "name": name,
        "owner_name": owner_name,
        "platform": "codex",
    })
    assert response.status_code == 200, response.text
    return response.json()["api_key"]


def test_health_and_security_headers(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["version"] == "0.3.6"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


def test_admin_endpoints_require_token(client):
    assert client.post("/api/admin/reset-db").status_code == 401
    assert client.post(
        "/api/admin/reset-db", headers={"X-Admin-Token": "wrong"}
    ).status_code == 401
    assert client.post("/api/admin/reset-db", headers=ADMIN_HEADERS).status_code == 200


def test_pending_agent_requires_valid_owner_consent(client):
    response = client.post("/api/auto-enroll", json={
        "agent_name": "Pending-Codex",
        "owner_name": "测试主人",
        "platform": "codex",
        "memory_source": "Codex memory",
        "owner_profile": {
            "age": 30,
            "city": "深圳",
            "personality": {"mbti": "INTJ"},
        },
    })
    assert response.status_code == 200, response.text
    payload = response.json()
    key_headers = {"X-API-Key": payload["api_key"]}
    consent_id = payload["consent_id"]

    assert client.get("/api/owner", headers=key_headers).status_code == 403
    assert client.get(f"/consent/{consent_id}").status_code == 200

    replacement = "a" if consent_id[-1] != "a" else "b"
    tampered = consent_id[:-1] + replacement
    assert client.get(f"/consent/{tampered}").status_code == 404

    approved = client.post(f"/consent/{consent_id}/approve")
    assert approved.status_code == 200
    assert client.get("/api/owner", headers=key_headers).status_code == 200
    assert client.post(f"/consent/{consent_id}/approve").status_code == 410


def test_handshake_uses_public_domain_and_is_single_use(client):
    started = client.post("/api/handshake/start", json={"agent_platform": "codex"})
    assert started.status_code == 200
    start_payload = started.json()
    assert start_payload["endpoint"] == "https://www.taillink.cloud"
    assert "https://www.taillink.cloud/api/handshake/" in start_payload["curl_command"]

    token = start_payload["token"]
    submitted = client.post(f"/api/handshake/{token}/submit", json={
        "agent_platform": "codex",
        "mtime_stats": {"file_count": 2, "memory_chars": 1200},
        "owner_paste": "深圳的 AI 创作者",
        "display_name": "握手用户",
    })
    assert submitted.status_code == 200

    verified = client.post(f"/api/handshake/{token}/verify", json={
        "verify_code": submitted.json()["verify_code"],
        "owner_consent": True,
        "display_name": "握手用户",
        "platform": "codex",
    })
    assert verified.status_code == 200
    assert verified.json()["success"] is True
    assert client.post(f"/api/handshake/{token}/verify", json={
        "verify_code": submitted.json()["verify_code"],
        "owner_consent": True,
        "display_name": "握手用户",
        "platform": "codex",
    }).status_code == 404


def test_resource_score_stays_on_zero_to_one_hundred_scale():
    owner_a = Owner(
        agent_id=1,
        resources={"looking_for": ["有机蔬菜"]},
    )
    target = Owner(
        agent_id=2,
        resources={
            "industry": "农业",
            "can_offer": ["有机蔬菜"],
            "offer_categories": ["食材供应"],
            "deal_size_band": "3",
        },
    )
    need = Need(
        agent_id=1,
        need_type=NeedType.RESOURCE,
        title="找供应商",
        description="找有机蔬菜供应商",
        spec={
            "category": "食材供应",
            "industry": "农业",
            "requirements": ["有机蔬菜"],
            "budget_band": "3",
        },
    )
    result = matcher.score_resource(need, owner_a, target)
    assert result["total"] == 100.0


def test_rematch_does_not_duplicate_proposed_results(client):
    key_a = _register(client, "Agent-A", "主人A")
    key_b = _register(client, "Agent-B", "主人B")
    headers_a = {"X-API-Key": key_a}
    headers_b = {"X-API-Key": key_b}

    assert client.put("/api/owner", headers=headers_a, json={
        "city": "广州",
        "resources": {"looking_for": ["有机蔬菜"]},
    }).status_code == 200
    assert client.put("/api/owner", headers=headers_b, json={
        "city": "广州",
        "resources": {
            "industry": "农业",
            "can_offer": ["有机蔬菜"],
            "offer_categories": ["食材供应"],
            "deal_size_band": "3",
        },
    }).status_code == 200
    created = client.post("/api/needs", headers=headers_a, json={
        "need_type": "resource",
        "title": "找有机蔬菜",
        "description": "寻找稳定供货",
        "spec": {
            "category": "食材供应",
            "industry": "农业",
            "requirements": ["有机蔬菜"],
            "budget_band": "3",
        },
    })
    assert created.status_code == 200, created.text

    assert client.post("/api/admin/rematch-all", headers=ADMIN_HEADERS).status_code == 200
    assert client.post("/api/admin/rematch-all", headers=ADMIN_HEADERS).status_code == 200
    matches = client.get("/api/matches", headers=headers_a)
    assert matches.status_code == 200
    assert len(matches.json()) == 1


def test_frontend_escapes_api_supplied_html():
    source = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert "function escapeHtml(value)" in source
    assert "function currentV3Platform()" in source
    assert "function continueV3Flow()" in source
    assert "onclick='continueV3Flow()'" in source
    assert "generatePoster(s_matches[" in source
    assert "JSON.stringify(m).replace" not in source
