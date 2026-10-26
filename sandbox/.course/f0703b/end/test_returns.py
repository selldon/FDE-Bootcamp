"""The edges of the return rules, one test each."""
from returns import can_return

LAPTOP = {"market": "UK", "product": "laptop", "delivered": "2026-10-02",
          "today": "2026-10-22", "opened": True, "business": False}


def test_opened_laptop_after_20_days_in_the_uk():
    assert can_return(LAPTOP) == "not eligible"


def test_the_last_day_of_the_window():
    assert can_return(LAPTOP | {"today": "2026-10-16"}) == "eligible"


def test_the_day_after_the_window():
    assert can_return(LAPTOP | {"today": "2026-10-17"}) == "not eligible"


def test_opened_in_the_us_15_days():
    us = LAPTOP | {"market": "US", "today": "2026-10-17"}
    assert can_return(us) == "eligible"
    assert can_return(us | {"today": "2026-10-18"}) == "not eligible"


def test_a_company_customer_gets_a_person():
    assert can_return(LAPTOP | {"business": True}) == "person"
