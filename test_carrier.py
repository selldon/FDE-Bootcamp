"""Fast tests of the carrier's file: a fake folder of files, no network."""
from datetime import date

import pytest

import carrier

GOOD = "tracking,status,place,date\nEP-1,in transit,Leeds depot,2026-10-21\nEP-2,delivered,front door,2026-10-14\n"
WITH_PICKUP = ('tracking,status,pickup_point,place,date\n'
               'EP-3,out for delivery,"Locker 4, Leeds Station",Leeds,2026-10-22\n'
               'EP-4,in transit,,Newark hub,2026-10-22\n')


class FakeFiles:
    """A folder of files behind the same interface as the SFTP server."""

    def __init__(self, files):
        self.files = {n: d.encode("cp1252") for n, d in files.items()}

    def names(self):
        return list(self.files)

    def read(self, name):
        return self.files[name]


def test_newest_of_several_files_is_chosen():
    files = FakeFiles({"carrier-2026-10-20.csv": GOOD, "carrier-2026-10-22.csv": WITH_PICKUP,
                       "carrier-2026-10-21.csv": GOOD, "notes.txt": "x"})
    name, rows = carrier.newest_rows(files)
    assert name == "carrier-2026-10-22.csv"
    assert len(rows) == 2


def test_normal_file_parses_by_header_name():
    rows = carrier.parse(GOOD.encode())
    assert rows[0] == {"tracking": "EP-1", "status": "in transit", "place": "Leeds depot",
                       "date": date(2026, 10, 21), "pickup_point": ""}
    assert carrier.newest_news(rows) == date(2026, 10, 21)


def test_extra_column_and_quoted_comma():
    rows = carrier.parse(WITH_PICKUP.encode())
    assert rows[0]["pickup_point"] == "Locker 4, Leeds Station"
    assert rows[0]["place"] == "Leeds"
    assert rows[1]["pickup_point"] == ""


def test_cp1252_is_decoded():
    rows = carrier.parse("tracking,status,place,date\nEP-9,delivered,Café Zürich,2026-10-20\n".encode("cp1252"))
    assert rows[0]["place"] == "Café Zürich"


@pytest.mark.parametrize("bad, line, text", [
    ("tracking,status,place,date\nEP-1,in transit,Leeds,2026-10-21\nEP-2,delivered\n", 3, "fields"),
    ("tracking,status,place,date\nEP-1,in transit,Leeds,21/10/2026\n", 2, "bad date"),
    ("tracking,status,place,date\n,in transit,Leeds,2026-10-21\n", 2, "empty tracking"),
])
def test_bad_line_fails_loudly_with_its_number(bad, line, text):
    with pytest.raises(carrier.CarrierError) as e:
        carrier.parse(bad.encode(), "f.csv")
    assert f"line {line}" in str(e.value) and text in str(e.value)


def test_missing_column_and_empty_file_fail():
    with pytest.raises(carrier.CarrierError, match="missing columns status"):
        carrier.parse(b"tracking,place,date\nEP-1,x,2026-10-21\n")
    with pytest.raises(carrier.CarrierError, match="empty"):
        carrier.parse(b"")


def test_empty_folder_is_an_error():
    with pytest.raises(carrier.CarrierError, match="no carrier"):
        carrier.newest_rows(FakeFiles({}))
    with pytest.raises(carrier.CarrierError):
        carrier.newest_rows(FakeFiles({"readme.txt": "x"}))


def test_the_date_of_a_file_comes_from_its_name():
    from datetime import date
    assert carrier.file_date("carrier-2026-10-22.csv") == date(2026, 10, 22)
