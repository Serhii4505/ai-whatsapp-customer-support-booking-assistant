import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_public_tree_contains_no_obvious_secrets_or_real_credentials() -> None:
    patterns = {
        "meta token": re.compile(r"\bEAA[A-Za-z0-9]{20,}\b"),
        "google key": re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
        "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        "whatsapp phone id assignment": re.compile(r"WHATSAPP_PHONE_NUMBER_ID\s*=\s*\d+"),
    }
    scanned_suffixes = {".py", ".md", ".toml", ".json", ".example", ".gitignore"}
    violations: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in {".venv", ".git", "__pycache__"} for part in path.parts):
            continue
        if path.suffix not in scanned_suffixes and path.name not in {".env.example", ".gitignore"}:
            continue
        text = path.read_text(encoding="utf-8")
        for label, pattern in patterns.items():
            if pattern.search(text):
                violations.append(f"{path.relative_to(ROOT)}: {label}")
    assert not violations, violations

