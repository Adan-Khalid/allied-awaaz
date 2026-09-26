from sqlalchemy import select

from app.models import Intervention
from app.seed import seed

RM = {"Authorization": "Bearer dev-rm-token"}
SUP = {"Authorization": "Bearer dev-sup-token"}


def test_sweep_drafts_and_approval_gate(client, db):
    db.query(__import__("app.models", fromlist=["Device"]).Device).delete()
    db.query(__import__("app.models", fromlist=["Merchant"]).Merchant).delete()
    db.commit()
    assert seed(db)

    merchants = client.get("/v1/console/merchants", headers=RM).json()
    statuses = {m["name"]: (m["status"], m["primary_reason"]) for m in merchants}
    assert statuses["Hamza Auto Workshop"][1] == "NEVER_ACTIVATED"
    assert statuses["Fresh Cuts Salon"][1] == "DORMANT"
    assert statuses["City Care Pharmacy"][1] in {"DEVICE_OFFLINE", "DECLINING"}
    assert statuses["Bismillah Kiryana"][1] == "EXCEPTION_SPIKE"
    assert statuses["Ahmed Pharmacy"][0] == "HEALTHY"

    sweep = client.post("/v1/console/activation/sweep", headers=RM).json()
    assert sweep["examined"] == 25 and len(sweep["drafted"]) >= 8
    # idempotent: second sweep drafts nothing new
    assert set(client.post("/v1/console/activation/sweep", headers=RM).json()["drafted"]) <= set(sweep["drafted"])

    items = client.get("/v1/console/interventions?status=PENDING_APPROVAL", headers=RM).json()
    wa = next(i for i in items if i["channel"] == "whatsapp")
    call = next(i for i in items if i["channel"] in {"rm_call", "field_visit"})

    assert client.post(f"/v1/console/interventions/{wa['id']}/approve", json={}, headers=RM).status_code == 403
    ok = client.post(f"/v1/console/interventions/{wa['id']}/approve", json={"note": "ok"}, headers=SUP).json()
    assert ok["status"] == "EXECUTED" and ok["decided_by"] == "Imran (Supervisor)"
    rej = client.post(f"/v1/console/interventions/{call['id']}/reject", json={"note": "visited yesterday"}, headers=RM)
    assert rej.json()["status"] == "REJECTED"
    assert client.post(f"/v1/console/interventions/{call['id']}/approve", json={}, headers=RM).status_code == 409

    audit = client.get("/v1/console/audit", headers=SUP).json()
    actions = {a["action"] for a in audit}
    assert {"intervention.approved", "intervention.executed", "intervention.rejected", "activation.sweep"} <= actions


def test_summary_and_run_lookup(client):
    s = client.get("/v1/console/summary", headers=RM).json()
    assert set(s) == {"merchants", "pending_approvals", "open_exceptions"}
    sweep = client.post("/v1/console/activation/sweep", headers=RM).json()
    run = client.get(f"/v1/console/agent-runs/{sweep['run_id']}", headers=RM).json()
    assert run["agent"] == "activation" and run["steps"][-1]["step"] == "respond"
    assert client.get("/v1/console/agent-runs/run_missing", headers=RM).status_code == 404
