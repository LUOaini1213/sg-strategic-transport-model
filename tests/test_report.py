"""README.md and docs/validation_report.md are generated from results/; they must match a fresh rendering."""
from pathlib import Path

import pytest

from stm import report


def test_snapshot_documents_match_results():
    for dst, text in report.render_all().items():
        assert Path(dst).read_text(encoding="utf-8") == text, f"{dst.name} is stale: run scripts/run_all.py"


def test_unfilled_placeholder_is_an_error():
    with pytest.raises(KeyError):
        report.fill("{{no_such_value}}", {})
    assert report.fill("a {{x}} b", {"x": "1"}) == "a 1 b"
