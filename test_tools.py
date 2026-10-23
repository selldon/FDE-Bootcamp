"""Fast tests of the order tools: fake data only, no call to Claude."""
from tools import find_order


def test_no_order_data_before_the_code_is_checked():
    assert "error" in find_order("DS-20417", None)


def test_someone_elses_order_gives_nothing():
    assert "error" in find_order("DS-20417", "ben.taylor@example.com")


def test_the_owner_gets_the_order():
    assert find_order("DS-20417", "maya.ross@example.com")["status"] == "shipped"
