import pytest
import tomlkit
from unittest.mock import patch

import recordimporter

GOOD_AUTH = {"Authorization": "Bearer test-secret-key"}
BAD_AUTH  = {"Authorization": "Bearer wrong-key"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    recordimporter.app.config["TESTING"] = True
    with recordimporter.app.test_client() as c:
        yield c


def _make_toml(hosts=None, cnames=None):
    doc = tomlkit.document()
    dns = tomlkit.table()
    dns.add("hosts", hosts if hosts is not None else tomlkit.array())
    dns.add("cnameRecords", cnames if cnames is not None else tomlkit.array())
    doc.add("dns", dns)
    return doc


@pytest.fixture
def toml_file(tmp_path):
    p = tmp_path / "pihole.toml"
    p.write_text(tomlkit.dumps(_make_toml()), encoding="utf-8")
    return p


@pytest.fixture(autouse=True)
def patch_toml_path(toml_file, monkeypatch):
    monkeypatch.setattr(recordimporter, "TOML_PATH", str(toml_file))


def _read_hosts(toml_file):
    return tomlkit.parse(toml_file.read_text(encoding="utf-8"))["dns"]["hosts"]


def _read_cnames(toml_file):
    return tomlkit.parse(toml_file.read_text(encoding="utf-8"))["dns"]["cnameRecords"]


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------

def test_no_auth_header(client):
    r = client.post("/add-a-record", json={"domain": "foo.local", "ip": "1.2.3.4"})
    assert r.status_code == 401


def test_bad_bearer_token(client):
    r = client.post("/add-a-record", json={"domain": "foo.local", "ip": "1.2.3.4"},
                    headers=BAD_AUTH)
    assert r.status_code == 401


def test_missing_bearer_prefix(client):
    r = client.post("/add-a-record", json={"domain": "foo.local", "ip": "1.2.3.4"},
                    headers={"Authorization": "test-secret-key"})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /add-a-record
# ---------------------------------------------------------------------------

def test_add_a_record_happy_path(client, toml_file):
    r = client.post("/add-a-record", json={"domain": "foo.local", "ip": "1.2.3.4"},
                    headers=GOOD_AUTH)
    assert r.status_code == 200
    assert "1.2.3.4 foo.local" in _read_hosts(toml_file)


def test_add_a_record_idempotent(client, toml_file):
    # Pre-populate
    doc = _make_toml(hosts=["1.2.3.4 foo.local"])
    toml_file.write_text(tomlkit.dumps(doc), encoding="utf-8")

    r = client.post("/add-a-record", json={"domain": "foo.local", "ip": "1.2.3.4"},
                    headers=GOOD_AUTH)
    assert r.status_code == 200
    assert r.get_json().get("message") == "Record already exists"
    assert len(_read_hosts(toml_file)) == 1  # no duplicate added


def test_add_a_record_missing_domain(client):
    r = client.post("/add-a-record", json={"ip": "1.2.3.4"}, headers=GOOD_AUTH)
    assert r.status_code == 400


def test_add_a_record_missing_ip(client):
    r = client.post("/add-a-record", json={"domain": "foo.local"}, headers=GOOD_AUTH)
    assert r.status_code == 400


def test_add_a_record_empty_body(client):
    r = client.post("/add-a-record", json={}, headers=GOOD_AUTH)
    assert r.status_code == 400


def test_add_a_record_toml_read_failure(client):
    with patch.object(recordimporter, "_load_toml", side_effect=OSError("permission denied")):
        r = client.post("/add-a-record", json={"domain": "foo.local", "ip": "1.2.3.4"},
                        headers=GOOD_AUTH)
    assert r.status_code == 500


def test_add_a_record_toml_write_failure(client, toml_file):
    with patch.object(recordimporter, "_save_toml", side_effect=OSError("disk full")):
        r = client.post("/add-a-record", json={"domain": "foo.local", "ip": "1.2.3.4"},
                        headers=GOOD_AUTH)
    assert r.status_code == 500


# ---------------------------------------------------------------------------
# DELETE /delete-a-record
# ---------------------------------------------------------------------------

def test_delete_a_record_happy_path(client, toml_file):
    doc = _make_toml(hosts=["1.2.3.4 foo.local"])
    toml_file.write_text(tomlkit.dumps(doc), encoding="utf-8")

    r = client.delete("/delete-a-record", json={"domain": "foo.local"}, headers=GOOD_AUTH)
    assert r.status_code == 200
    assert "1.2.3.4 foo.local" not in _read_hosts(toml_file)


def test_delete_a_record_not_found(client):
    r = client.delete("/delete-a-record", json={"domain": "foo.local"}, headers=GOOD_AUTH)
    assert r.status_code == 404


def test_delete_a_record_missing_domain(client):
    r = client.delete("/delete-a-record", json={}, headers=GOOD_AUTH)
    assert r.status_code == 400


def test_delete_a_record_toml_read_failure(client):
    with patch.object(recordimporter, "_load_toml", side_effect=OSError("permission denied")):
        r = client.delete("/delete-a-record", json={"domain": "foo.local"}, headers=GOOD_AUTH)
    assert r.status_code == 500


def test_delete_a_record_toml_write_failure(client, toml_file):
    doc = _make_toml(hosts=["1.2.3.4 foo.local"])
    toml_file.write_text(tomlkit.dumps(doc), encoding="utf-8")

    with patch.object(recordimporter, "_save_toml", side_effect=OSError("disk full")):
        r = client.delete("/delete-a-record", json={"domain": "foo.local"}, headers=GOOD_AUTH)
    assert r.status_code == 500


# ---------------------------------------------------------------------------
# POST /add-cname-record
# ---------------------------------------------------------------------------

def test_add_cname_happy_path(client, toml_file):
    r = client.post("/add-cname-record",
                    json={"domain": "alias.local", "target": "real.local"},
                    headers=GOOD_AUTH)
    assert r.status_code == 200
    assert "alias.local,real.local" in _read_cnames(toml_file)


def test_add_cname_idempotent(client, toml_file):
    doc = _make_toml(cnames=["alias.local,real.local"])
    toml_file.write_text(tomlkit.dumps(doc), encoding="utf-8")

    r = client.post("/add-cname-record",
                    json={"domain": "alias.local", "target": "other.local"},
                    headers=GOOD_AUTH)
    assert r.status_code == 200
    assert r.get_json().get("message") == "Record already exists"
    assert len(_read_cnames(toml_file)) == 1


def test_add_cname_missing_domain(client):
    r = client.post("/add-cname-record", json={"target": "real.local"}, headers=GOOD_AUTH)
    assert r.status_code == 400


def test_add_cname_missing_target(client):
    r = client.post("/add-cname-record", json={"domain": "alias.local"}, headers=GOOD_AUTH)
    assert r.status_code == 400


def test_add_cname_toml_read_failure(client):
    with patch.object(recordimporter, "_load_toml", side_effect=OSError("permission denied")):
        r = client.post("/add-cname-record",
                        json={"domain": "alias.local", "target": "real.local"},
                        headers=GOOD_AUTH)
    assert r.status_code == 500


def test_add_cname_toml_write_failure(client, toml_file):
    with patch.object(recordimporter, "_save_toml", side_effect=OSError("disk full")):
        r = client.post("/add-cname-record",
                        json={"domain": "alias.local", "target": "real.local"},
                        headers=GOOD_AUTH)
    assert r.status_code == 500


# ---------------------------------------------------------------------------
# DELETE /delete-cname-record
# ---------------------------------------------------------------------------

def test_delete_cname_happy_path(client, toml_file):
    doc = _make_toml(cnames=["alias.local,real.local"])
    toml_file.write_text(tomlkit.dumps(doc), encoding="utf-8")

    r = client.delete("/delete-cname-record", json={"domain": "alias.local"}, headers=GOOD_AUTH)
    assert r.status_code == 200
    assert "alias.local,real.local" not in _read_cnames(toml_file)


def test_delete_cname_not_found(client):
    r = client.delete("/delete-cname-record", json={"domain": "alias.local"}, headers=GOOD_AUTH)
    assert r.status_code == 404


def test_delete_cname_missing_domain(client):
    r = client.delete("/delete-cname-record", json={}, headers=GOOD_AUTH)
    assert r.status_code == 400


def test_delete_cname_toml_read_failure(client):
    with patch.object(recordimporter, "_load_toml", side_effect=OSError("permission denied")):
        r = client.delete("/delete-cname-record", json={"domain": "alias.local"},
                          headers=GOOD_AUTH)
    assert r.status_code == 500


def test_delete_cname_toml_write_failure(client, toml_file):
    doc = _make_toml(cnames=["alias.local,real.local"])
    toml_file.write_text(tomlkit.dumps(doc), encoding="utf-8")

    with patch.object(recordimporter, "_save_toml", side_effect=OSError("disk full")):
        r = client.delete("/delete-cname-record", json={"domain": "alias.local"},
                          headers=GOOD_AUTH)
    assert r.status_code == 500
