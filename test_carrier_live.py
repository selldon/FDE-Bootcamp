"""Live check: reads the real newest carrier file. Run on request."""
import pytest

import carrier

pytestmark = pytest.mark.live


def test_newest_real_file_parses():
    with carrier.connect() as files:
        name, rows = carrier.newest_rows(files)
    print(f"{name}: {len(rows)} rows, newest news {carrier.newest_news(rows)}")
    assert rows
