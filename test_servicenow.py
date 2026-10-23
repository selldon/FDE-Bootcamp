"""Fast tests of the ServiceNow module (Phase 6): the fake, one task per key, the two creates, no network."""
import json
from decimal import Decimal
from pathlib import Path

import pytest

import servicenow
from servicenow import FakeServiceNow, ServiceNowError

DRAFT = {"req_id": 1, "order": "DS-1", "line": 2, "amount": Decimal("36.01"), "key": "a" * 64, "status": "W"}


def test_one_task_per_key():
    sn = FakeServiceNow()
    first = sn.create_approval_task(DRAFT)
    second = sn.create_approval_task(DRAFT)
    assert len(sn.tasks) == 1 and first == second
    assert sn.tasks[0]["u_draft"] == DRAFT["key"]


def test_a_different_draft_is_a_different_task():
    sn = FakeServiceNow()
    sn.create_approval_task(DRAFT)
    sn.create_approval_task(dict(DRAFT, key="b" * 64, line=1))
    assert len(sn.tasks) == 2


def test_retry_after_draft_written_and_task_failed_makes_one_task():
    sn = FakeServiceNow()
    sn.fail, sn.fail_after_lookup = ServiceNowError("down"), True
    with pytest.raises(ServiceNowError):
        sn.create_approval_task(DRAFT)
    assert sn.tasks == []
    sn.fail = None
    sn.create_approval_task(DRAFT)
    sn.create_approval_task(DRAFT)
    assert len(sn.tasks) == 1


def test_failure_raises_a_clear_error():
    sn = FakeServiceNow()
    sn.fail = ServiceNowError("ServiceNow answered 500")
    with pytest.raises(ServiceNowError, match="500"):
        sn.create_approval_task(DRAFT)
    with pytest.raises(ServiceNowError):
        sn.create_case("s", [], "c")
    assert sn.tasks == [] and sn.cases == []


def test_short_description_has_order_item_amount_and_no_more():
    text = servicenow.task_text(DRAFT)
    assert "DS-1" in text and "2" in text and "36.01" in text
    assert DRAFT["key"] not in text
    sn = FakeServiceNow()
    sn.create_approval_task(DRAFT)
    assert set(sn.tasks[0]) == {"short_description", "u_draft", "sys_id"}


def test_create_case_sends_only_two_fields_and_never_reads():
    sn = FakeServiceNow()
    history = [{"role": "user", "content": "I want a person"}]
    sn.create_case("Order DS-1: wants a person", history, "cust-1")
    assert [m for m, _ in sn.calls] == ["POST"]
    case = sn.cases[0]
    assert set(case) == {"short_description", "u_conversation", "sys_id"}
    assert json.loads(case["u_conversation"]) == history
    assert "cust-1" not in json.dumps(case)


def test_only_two_tables_and_two_verbs():
    sn = FakeServiceNow()
    sn.create_approval_task(DRAFT)
    sn.create_case("s", [], "c")
    allowed = {("GET", servicenow.TASKS), ("POST", servicenow.TASKS), ("POST", servicenow.CASES)}
    assert {(m, p.split("?")[0]) for m, p in sn.calls} <= allowed


def test_real_send_wraps_http_and_network_errors(monkeypatch):
    monkeypatch.setenv("SERVICENOW_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("SERVICENOW_USER", "u")
    monkeypatch.setenv("SERVICENOW_PASSWORD", "p")

    def refuse(*args, **kwargs):
        raise OSError("refused")
    monkeypatch.setattr(servicenow.urllib.request, "urlopen", refuse)
    with pytest.raises(ServiceNowError, match="refused"):
        servicenow.send("GET", servicenow.TASKS)


def test_module_has_no_put_patch_delete():
    source = Path(servicenow.__file__).read_text()
    for verb in ("PUT", "PATCH", "DELETE"):
        assert f'"{verb}"' not in source
