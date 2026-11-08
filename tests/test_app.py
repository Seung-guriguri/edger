"""Smoke test: render the whole app headlessly with the offline DEMO company."""
from streamlit.testing.v1 import AppTest


def test_demo_renders_without_errors():
    at = AppTest.from_file("../app.py", default_timeout=60)
    at.query_params["t"] = "DEMO"
    at.run()
    assert not at.exception, at.exception
    assert not at.error
    labels = [m.label for m in at.metric]
    assert any(label.startswith("매출") for label in labels)
    assert len(at.tabs) == 3


def test_empty_state():
    at = AppTest.from_file("../app.py", default_timeout=60)
    at.run()
    assert not at.exception
    assert any("DEMO" in i.value for i in at.info)
