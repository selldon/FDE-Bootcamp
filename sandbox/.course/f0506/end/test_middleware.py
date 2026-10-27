"""The middleware gives an order only to the customer who owns it."""
from fastapi.testclient import TestClient
from middleware import app

client = TestClient(app)
MAYA = {"customer-id": "10401"}


def test_own_order_is_found():
    reply = client.get("/orders/DS-20417", headers=MAYA)
    assert reply.status_code == 200
    assert reply.json()["items"][0]["tracking"] == "EP-7718204"


def test_someone_elses_order_is_not_found():
    reply = client.get("/orders/DS-20433", headers=MAYA)
    assert reply.status_code == 404


def test_missing_order_is_not_found():
    reply = client.get("/orders/DS-99999", headers=MAYA)
    assert reply.status_code == 404
