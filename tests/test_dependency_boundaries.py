from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_orchestration_runtime_does_not_import_samples():
    violations = []
    for path in (ROOT / "orchestrate").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        if "from samples" in text or "import samples" in text:
            violations.append(str(path.relative_to(ROOT)))

    assert violations == []


def test_host_agent_runtime_does_not_import_application_or_sample_packages():
    violations = []
    for path in (ROOT / "host_agent").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        forbidden = ("from orchestrate", "import orchestrate", "from samples", "import samples", "from common", "import common")
        if any(marker in text for marker in forbidden):
            violations.append(str(path.relative_to(ROOT)))

    assert violations == []


def test_host_agent_runtime_contains_no_demo_credentials():
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "host_agent").rglob("*.py")
        if "__pycache__" not in path.parts
    )

    assert "Admin@123" not in text
