"""Fast tests of the one-time code: fake clock, outbox in a temp folder."""
import json

import pytest

from verify import Verifier

MAYA = "maya.ross@example.com"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def outbox(tmp_path):
    return tmp_path / "outbox.jsonl"


@pytest.fixture
def verifier(clock, outbox):
    return Verifier(clock=clock, outbox=str(outbox))


def sent_code(outbox):
    return json.loads(outbox.read_text().splitlines()[-1])["code"]


def test_the_right_code_works(verifier, outbox):
    verifier.start(MAYA)
    code = sent_code(outbox)
    assert len(code) == 6 and code.isdigit()
    assert verifier.check(MAYA, code) is True


def test_a_code_works_only_once(verifier, outbox):
    verifier.start(MAYA)
    code = sent_code(outbox)
    assert verifier.check(MAYA, code) is True
    assert verifier.check(MAYA, code) is False


def test_three_wrong_codes_lock_even_the_right_one(verifier, outbox):
    verifier.start(MAYA)
    code = sent_code(outbox)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(3):
        assert verifier.check(MAYA, wrong) is False
    assert verifier.check(MAYA, code) is False


def test_an_expired_code_fails(verifier, outbox, clock):
    verifier.start(MAYA)
    code = sent_code(outbox)
    clock.now += 601
    assert verifier.check(MAYA, code) is False


def test_a_code_is_still_valid_inside_ten_minutes(verifier, outbox, clock):
    verifier.start(MAYA)
    code = sent_code(outbox)
    clock.now += 599
    assert verifier.check(MAYA, code) is True


def test_unknown_email_writes_nothing_and_looks_the_same(verifier, outbox):
    known = verifier.start(MAYA)
    before = outbox.read_text()
    unknown = verifier.start("nobody@example.com")
    assert unknown == known
    assert outbox.read_text() == before
    assert verifier.check("nobody@example.com", "123456") is False
