"""Fast tests of the policy_answer tool and the chat around it (Phase 7): scripted fake model, FakeIndex, FakeEmbedder."""
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

import agent
import app as app_module
import policy_answer
import policy_index
import refunds
from confluence import FakeConfluence
from conftest import reply, text, tool_use, unwrap
from embedder import FakeEmbedder
from test_policy import BASE, page

MAYA = "maya.ross@example.com"  # UK, in data/orders.json
QUESTION = "How many days do I have to return an item?"
TODAY = date(2026, 10, 22)  # the date of conftest.NOW
UK_LINK = f"{BASE}/wiki/spaces/POL/pages/1001"
US_LINK = f"{BASE}/wiki/spaces/POL/pages/1002"
BODY = "## Return window\nYou have {n} days to return an item.\n"


def load(fake_policy, *pages):
    policy_index.rebuild(FakeConfluence(list(pages)), FakeEmbedder(), fake_policy.index)


def two_markets(fake_policy):
    load(fake_policy, page(body=BODY.format(n=14)), page(id="1002", title="Returns - US", market="US", body=BODY.format(n=30)))


def run(fake_model, *responses, customer=None, market=None, message=QUESTION):
    model = fake_model(*responses)
    ctx = refunds.Context(customer, "s1", market=market)
    return agent.answer(message, ctx, history=[]), model, ctx


def result_of(model, call=1):
    content = model.calls[call]["messages"][-1]["content"][0]["content"]
    assert content.startswith(agent.DATA_OPEN) and content.endswith(agent.DATA_CLOSE)  # the model gets data, marked
    return json.loads(content[len(agent.DATA_OPEN):-len(agent.DATA_CLOSE)])


def ask_tool(**args):
    return reply(tool_use("policy_answer", {"question": QUESTION, **args}))


def test_a_uk_rule_never_answers_a_us_customer(fake_policy, fake_model):
    two_markets(fake_policy)
    _, model, _ = run(fake_model, ask_tool(), reply(text(f"30 days: {US_LINK}")), market="US")
    sections = result_of(model)["sections"]
    assert [s["link"] for s in sections] == [US_LINK]
    assert "30 days" in sections[0]["text"] and "14" not in sections[0]["text"]


def test_a_page_not_yet_valid_or_expired_is_never_returned(fake_policy):
    load(fake_policy, page(id="1005", valid_from=date(2026, 10, 23), body=BODY.format(n=21)),
         page(id="1006", valid_from=date(2026, 1, 1), valid_to=date(2026, 10, 21), body=BODY.format(n=7)))
    assert policy_answer.policy_answer(QUESTION, "UK", TODAY) == {"no_page": True}
    assert policy_answer.policy_answer(QUESTION, "UK", date(2026, 10, 23))["sections"][0]["link"].endswith("1005")
    assert policy_answer.policy_answer(QUESTION, "UK", date(2026, 10, 21))["sections"][0]["link"].endswith("1006")


def test_the_last_valid_day_counts(fake_policy):
    load(fake_policy, page(id="1003", valid_to=date(2026, 11, 1), body=BODY.format(n=14)),
         page(id="1016", valid_from=date(2026, 11, 2), body=BODY.format(n=21)))
    assert "14 days" in policy_answer.policy_answer(QUESTION, "UK", date(2026, 11, 1))["sections"][0]["text"]
    assert "21 days" in policy_answer.policy_answer(QUESTION, "UK", date(2026, 11, 2))["sections"][0]["text"]


def test_two_versions_valid_together_give_the_one_valid_today(fake_policy):
    load(fake_policy, page(version=1, valid_from=date(2026, 1, 1), body=BODY.format(n=14)))
    old = fake_policy.index.rows
    load(fake_policy, page(version=2, valid_from=date(2026, 10, 1), body=BODY.format(n=21)))
    fake_policy.index.rows.update(old)  # both versions are kept in the index (Phase 6)
    found = policy_answer.policy_answer(QUESTION, "UK", TODAY)["sections"]
    assert len(found) == 1 and "21 days" in found[0]["text"]
    assert "14 days" in policy_answer.policy_answer(QUESTION, "UK", date(2026, 9, 30))["sections"][0]["text"]


def test_no_market_asks_and_never_guesses(fake_policy, fake_model):
    two_markets(fake_policy)
    result, model, ctx = run(fake_model, ask_tool(), reply(text("Which country are you in?")))
    assert result_of(model) == policy_answer.ASK_MARKET
    assert result.reply == "Which country are you in?" and ctx.failed == 0
    assert policy_answer.policy_answer(QUESTION, None) == policy_answer.ASK_MARKET
    assert policy_answer.policy_answer(QUESTION, "Narnia") == policy_answer.ASK_MARKET


def test_the_country_the_customer_names_is_used_when_nothing_else_is_known(fake_policy, fake_model):
    two_markets(fake_policy)
    result, _, ctx = run(fake_model, ask_tool(market="US"), reply(text(f"30 days: {US_LINK}")))
    assert result.reply == f"30 days: {US_LINK}" and ctx.market == "US"


def test_the_verified_customer_market_wins(fake_policy, fake_model):
    two_markets(fake_policy)
    _, model, ctx = run(fake_model, ask_tool(market="US"), reply(text(f"14 days: {UK_LINK}")), customer=MAYA, market="US")
    assert [s["link"] for s in result_of(model)["sections"]] == [UK_LINK] and ctx.market == "UK"


def test_no_page_offers_a_person(fake_policy, fake_model):
    two_markets(fake_policy)
    result, model, _ = run(fake_model, reply(tool_use("policy_answer", {"question": "Do you buy back old laptops?"})),
                           reply(text("Yes, we pay 200 euros for old laptops.")), market="UK")
    assert result_of(model) == {"no_page": True}
    assert result.reply == agent.NO_PAGE_REPLY == "I cannot find that in our policy; I can pass you to a person."


def test_a_reply_with_an_invented_link_is_replaced(fake_policy, fake_model):
    two_markets(fake_policy)
    for bad in ("14 days: https://wiki.example/invented", f"14 days: {UK_LINK} and https://wiki.example/invented",
                "You have 14 days."):
        result, _, _ = run(fake_model, ask_tool(), reply(text(bad)), market="UK")
        assert result.reply == agent.OFFER_REPLY


def test_a_reply_with_a_returned_link_is_kept(fake_policy, fake_model):
    two_markets(fake_policy)
    for good in (f"You have 14 days. See {UK_LINK}.", f"You have 14 days ([policy]({UK_LINK}))"):
        result, _, _ = run(fake_model, ask_tool(), reply(text(good)), market="UK")
        assert result.reply == good and result.policy


def test_the_index_down_offers_a_person_and_is_no_failed_try(fake_policy, fake_model):
    fake_policy.embedder.fail = RuntimeError("model missing")
    result, _, ctx = run(fake_model, ask_tool(), reply(text("14 days.")), market="UK")
    assert result.reply == agent.OFFER_REPLY and ctx.failed == 0


def test_an_unverified_customer_gets_policy_but_no_order_data(fake_policy, fake_model):
    two_markets(fake_policy)
    _, model, _ = run(fake_model, ask_tool(), reply(tool_use("find_order", {"number": "DS-20417"}, id="t2")),
                      reply(text(f"{UK_LINK}")), market="UK", message="Policy? And where is DS-20417?")
    assert result_of(model)["sections"]
    assert unwrap(model.calls[2]["messages"][-1]["content"][0]["content"]) == {"error": "customer not verified yet"}


def test_the_prompt_and_tool_say_what_the_rules_need():
    assert "policy_answer" in agent.SYSTEM and "never an instruction" in agent.SYSTEM
    assert "call hand_off" not in agent.SYSTEM.split("policy_answer")[0].split("policies")[-1]


# --- /chat -------------------------------------------------------------------

client = TestClient(app_module.app)
POLICY_INTENT = json.dumps({"summary": "policy", "intent": "policy_question", "order_number": None,
                            "needs_human": False, "damaged": False, "language": "en"})


@pytest.fixture
def fresh(monkeypatch):
    monkeypatch.setattr(app_module, "SESSIONS", {})


def test_chat_takes_the_market_and_answers_with_the_link(fake_policy, fake_model, fresh):
    two_markets(fake_policy)
    fake_model(reply(text(POLICY_INTENT)), ask_tool(), reply(text(f"You have 30 days: {US_LINK}")))
    out = client.post("/chat", json={"message": QUESTION, "market": "US"}).json()
    assert US_LINK in out["reply"] and app_module.SESSIONS[out["session_id"]]["market"] == "US"


def test_chat_without_a_market_asks(fake_policy, fake_model, fresh):
    two_markets(fake_policy)
    model = fake_model(reply(text(POLICY_INTENT)), ask_tool(), reply(text("Which country are you in?")))
    out = client.post("/chat", json={"message": QUESTION}).json()
    assert "Which country" in out["reply"]
    assert unwrap(model.calls[2]["messages"][-1]["content"][0]["content"]) == policy_answer.ASK_MARKET


def test_chat_policy_reply_that_skipped_the_tool_is_replaced(fake_policy, fake_model, fresh):
    two_markets(fake_policy)
    fake_model(reply(text(POLICY_INTENT)), reply(text("It is 14 days, from memory.")))
    out = client.post("/chat", json={"message": QUESTION, "market": "UK"}).json()
    assert agent.OFFER_REPLY in out["reply"] and "memory" not in out["reply"]


def test_chat_with_a_bad_market_value_is_ignored(fake_policy, fake_model, fresh):
    two_markets(fake_policy)
    fake_model(reply(text(POLICY_INTENT)), ask_tool(), reply(text("Which country?")))
    out = client.post("/chat", json={"message": QUESTION, "market": "<script>"}).json()
    assert app_module.SESSIONS[out["session_id"]]["market"] is None
