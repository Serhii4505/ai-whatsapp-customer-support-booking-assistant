import json
import re
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_readme_local_links_resolve() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    targets = re.findall(r"!?(?:\[[^]]*\])\(([^)]+)\)", readme)
    local_targets = [target.split("#", 1)[0] for target in targets if "://" not in target]
    missing = [target for target in local_targets if not (ROOT / target).exists()]
    assert local_targets
    assert not missing, missing


def test_portfolio_images_have_expected_png_dimensions() -> None:
    expected = {
        "architecture.png": (1600, 900),
        "booking-flow.png": (1600, 900),
        "demo-conversation.png": (1200, 900),
        "demo-booking.png": (1200, 900),
        "demo-handoff.png": (1200, 900),
    }
    for filename, dimensions in expected.items():
        raw = (ROOT / "docs" / "assets" / filename).read_bytes()
        assert raw[:8] == b"\x89PNG\r\n\x1a\n"
        assert struct.unpack(">II", raw[16:24]) == dimensions


def test_demo_records_are_explicitly_synthetic_and_contain_no_contact_fields() -> None:
    paths = sorted((ROOT / "demo").glob("sample_*.json"))
    assert len(paths) == 3
    combined = ""
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["demo_only"] is True
        combined += path.read_text(encoding="utf-8")
    assert not re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", combined)
    assert not re.search(r'"(?:phone|email|address|first_name|last_name)"\s*:', combined, re.I)


def test_publication_documents_state_demo_limits_and_no_publication_claim() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()
    upwork = (ROOT / "docs" / "UPWORK_PORTFOLIO.md").read_text(encoding="utf-8").lower()
    checklist = (ROOT / "docs" / "GITHUB_PUBLICATION_CHECKLIST.md").read_text(
        encoding="utf-8"
    ).lower()
    for content in (readme, upwork):
        assert "portfolio" in content
        assert "synthetic" in content
        assert "not a commercial client" in content or "not a paid client" in content
        assert any(
            phrase in content
            for phrase in ("not connected", "were not connected", "not been connected")
        )
    assert "separate approval" in checklist
    assert "no repository was published" in upwork
