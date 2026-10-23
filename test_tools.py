"""Fast tests of the order tools: fake data only, no call to Claude."""
from tools import delivery_status, find_order

MAYA = "maya.ross@example.com"


def test_no_order_data_before_the_code_is_checked():
    assert "error" in find_order("DS-20417", None)


def test_someone_elses_order_gives_nothing():
    assert "error" in find_order("DS-20417", "ben.taylor@example.com")


def test_the_owner_gets_the_order():
    assert find_order("DS-20417", "maya.ross@example.com")["status"] == "shipped"


def test_no_parcel_data_before_the_code_is_checked():
    assert delivery_status("EP-7718204", None) == {
        "error": "customer not verified yet"}


def test_someone_elses_parcel_gives_nothing():
    other = delivery_status("EP-7718204", "tom.baker@example.com")
    assert other == delivery_status("EP-0000000", MAYA)


def test_the_owner_gets_the_parcel():
    assert delivery_status("EP-7718204", MAYA)["place"] == "Leeds depot"


def test_an_unknown_parcel_gives_an_error():
    assert "error" in delivery_status("EP-0000000", MAYA)
