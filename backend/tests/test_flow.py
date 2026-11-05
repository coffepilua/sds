import os
import tempfile
from datetime import date, timedelta

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/t.db"
os.environ["UPLOAD_DIR"] = tempfile.mkdtemp()

from fastapi.testclient import TestClient  # noqa: E402

from app import seed  # noqa: E402
from app.main import app  # noqa: E402

seed.run()
A = "/api/v1"
PDF = b"%PDF-1.4 demo"


def as_(email):
    c = TestClient(app)
    r = c.post(f"{A}/auth/login", json={"email": email, "password": seed.PW})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = "Bearer " + r.json()["access_token"]
    return c


def test_full_scenario():
    pat, coord, c1, c2, adm = (as_(f"{x}@demo.test") for x in ("patient", "coord", "clinic1", "clinic2", "admin"))
    assert TestClient(app).post(f"{A}/auth/login", json={"email": "x@x.io", "password": "nope"}).json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert len(pat.get(f"{A}/clinics", params={"country": "Turkey"}).json()["items"]) == 2  # pending-клиника скрыта

    cid = pat.post(f"{A}/cases", json={"specialty_id": 1, "description": "Учебный пример", "target_country": "India", "budget_usd": 8000}).json()["id"]
    assert pat.post(f"{A}/cases/{cid}/documents", files={"file": ("a.exe", b"MZ", "application/pdf")}).status_code == 415
    doc = pat.post(f"{A}/cases/{cid}/documents", files={"file": ("a.pdf", PDF, "application/pdf")})
    assert doc.status_code == 201, doc.text
    did = doc.json()["id"]
    assert pat.post(f"{A}/cases/{cid}/submit").json()["status"] == "submitted"
    assert coord.patch(f"{A}/coordinator/cases/{cid}/status", json={"status": "closed"}).status_code == 409
    assert coord.patch(f"{A}/coordinator/cases/{cid}/status", json={"status": "in_review"}).status_code == 200
    assert coord.post(f"{A}/coordinator/cases/{cid}/share-requests", json={"clinic_id": 5}).status_code == 400  # не проверена
    sh = coord.post(f"{A}/coordinator/cases/{cid}/share-requests", json={"clinic_id": 1})
    assert sh.status_code == 201
    sid = sh.json()["id"]
    assert coord.post(f"{A}/coordinator/cases/{cid}/share-requests", json={"clinic_id": 1}).status_code == 409

    # AC-05: до согласия клиника ничего не видит
    assert c1.get(f"{A}/clinic/cases/{cid}").status_code == 403
    assert c1.get(f"{A}/cases/{cid}/documents/{did}/download").status_code == 403
    assert pat.post(f"{A}/cases/{cid}/shares/{sid}/consent", json={"approved": True}).json()["consent_status"] == "approved"
    assert c1.get(f"{A}/cases/{cid}/documents/{did}/download").content == PDF
    # AC-07: чужая клиника, чужой пациент, обычный пациент в админке
    assert c2.get(f"{A}/clinic/cases/{cid}").status_code == 403
    other = TestClient(app)
    other.post(f"{A}/auth/register", json={"email": "p2@demo.test", "password": "Password123!", "full_name": "Другой"})
    other.headers["Authorization"] = "Bearer " + other.post(f"{A}/auth/login", json={"email": "p2@demo.test", "password": "Password123!"}).json()["access_token"]
    assert other.get(f"{A}/cases/{cid}").status_code == 404
    assert pat.get(f"{A}/admin/metrics").status_code == 403

    q = {"share_id": sid, "currency": "USD", "price_min": 4500, "price_max": 6500, "details": "Учебный диапазон",
         "valid_until": (date.today() + timedelta(days=30)).isoformat()}
    assert c1.post(f"{A}/clinic/cases/{cid}/quotes", json={**q, "price_min": 9000}).status_code == 422
    assert c2.post(f"{A}/clinic/cases/{cid}/quotes", json=q).status_code == 403
    oid = c1.post(f"{A}/clinic/cases/{cid}/quotes", json=q).json()["id"]
    assert pat.get(f"{A}/cases/{cid}").json()["status"] == "offers_received"
    assert pat.post(f"{A}/cases/{cid}/quotes/{oid}/select").json()["status"] == "selected"
    assert pat.post(f"{A}/cases/{cid}/quotes/{oid}/select").status_code == 409

    conv = pat.get(f"{A}/cases/{cid}/conversations").json()[0]["id"]
    assert c1.post(f"{A}/cases/{cid}/conversations/{conv}/messages", json={"body": "Здравствуйте"}).status_code == 201
    assert pat.get(f"{A}/cases/{cid}/conversations/{conv}/messages").json()["items"][0]["sender_name"]
    assert coord.patch(f"{A}/coordinator/cases/{cid}/status", json={"status": "closed"}).json()["status"] == "closed"
    m = adm.get(f"{A}/admin/metrics").json()
    assert m["cases"] == 1 and m["consent_rate"] == 100 and m["select_rate"] == 100


def test_html_dashboards_and_admin():
    for email, paths in {"patient@demo.test": ["/dashboard", "/cases/1"], "coord@demo.test": ["/coordinator", "/coordinator/cases/1"],
                         "clinic1@demo.test": ["/clinic", "/clinic/cases/1"],
                         "admin@demo.test": ["/admin", "/admin/moderation"]}.items():
        c = as_(email)
        for p in paths:
            r = c.get(p)
            assert r.status_code == 200, (email, p, r.status_code)
    adm = as_("admin@demo.test")
    assert "Demo Clinic Izmir" in adm.get("/admin/moderation").text
    assert adm.post("/admin/clinics/5", data={"verification_status": "verified", "back": "/admin/moderation"}).status_code == 200
    assert len(TestClient(app).get(f"{A}/clinics", params={"country": "Turkey"}).json()["items"]) == 3
    assert TestClient(app).get("/dashboard", follow_redirects=False).status_code == 303
    assert TestClient(app).get("/health").json() == {"status": "ok"}
