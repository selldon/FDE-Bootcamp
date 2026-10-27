"""Fast tests that keep docs/runbook.md true (docs/brief-handover.md, item 5): it fails when the runbook names a file, a script,
a flag, an endpoint, a workflow, a service, a name in the code or an alert message that no longer exists. Reads text only: no
network, no database, no Claude."""
import ast
import re
from pathlib import Path

import pytest

from app import app

ROOT = Path(__file__).parent
RUNBOOK = (ROOT / "docs" / "runbook.md").read_text()
README = (ROOT / "README.md").read_text()

FILE_EXT = r"(?:py|md|yml|yaml|sh|tsx|ts|json|sql|toml)"
FILE = re.compile(rf"`([A-Za-z0-9_][A-Za-z0-9_./-]*\.{FILE_EXT})(?::(\d+)(?:-(\d+))?)?`")
SCRIPT = re.compile(r"\bpython3? (?:-m \w+ )?([A-Za-z0-9_][A-Za-z0-9_./-]*\.py)((?: --[\w-]+)*)")


def lines_in(path):
    return len(path.read_text().splitlines())


# ---- files, scripts, flags -------------------------------------------------------------------------------------------

def test_every_file_the_runbook_names_exists_and_every_line_number_is_inside_it():
    found = FILE.findall(RUNBOOK)
    assert len(found) > 20, "the pattern found almost nothing: the test is not reading the runbook"
    for name, first, last in found:
        path = ROOT / name
        assert path.is_file(), f"the runbook names {name}, which does not exist"
        for number in (first, last):
            if number:
                assert int(number) <= lines_in(path), f"the runbook names {name}:{number}, past the end of the file"


def test_every_script_the_runbook_runs_exists_and_knows_the_flags_it_is_given():
    found = SCRIPT.findall(RUNBOOK)
    assert {"pipeline.py", "policy_index.py", "replay.py"} <= {name for name, _ in found}
    for name, flags in found:
        path = ROOT / name
        assert path.is_file(), f"the runbook runs {name}, which does not exist"
        for flag in flags.split():
            assert flag in path.read_text(), f"the runbook runs {name} {flag}, and {name} has no {flag}"


# ---- endpoints and pages ---------------------------------------------------------------------------------------------

ENDPOINT = re.compile(r"/(?:api/[A-Za-z0-9_/]+|openapi\.json|golive|pilot)(?![\w])")


def routes():
    return {(route.path, method) for route in app.routes for method in getattr(route, "methods", None) or ()}


def test_every_endpoint_and_page_the_runbook_names_exists():
    paths = {path for path, _ in routes()} | {app.openapi_url}
    pages = (ROOT / "widget" / "src" / "App.tsx").read_text()
    found = set(ENDPOINT.findall(RUNBOOK))
    assert {"/api/golive", "/api/golive/switch", "/golive", "/openapi.json"} <= found
    for endpoint in found:
        if endpoint.startswith("/api/") or endpoint == "/openapi.json":
            assert endpoint in paths, f"the runbook names {endpoint}, which the chat service does not serve"
        else:
            assert f'location.pathname === "{endpoint}"' in pages, f"the runbook names the page {endpoint}, which the widget lacks"


def test_every_curl_in_the_runbook_uses_a_method_the_endpoint_answers():
    curls = [line for line in RUNBOOK.splitlines() if line.strip().startswith("curl ")]
    assert curls
    for line in curls:
        endpoint = re.search(r"localhost:8080(/api/[A-Za-z0-9_/]+)", line)
        if endpoint:
            method = "POST" if "-X POST" in line else "GET"
            assert (endpoint.group(1), method) in routes(), f"{method} {endpoint.group(1)} is not a route: {line.strip()}"


# ---- workflows, services ---------------------------------------------------------------------------------------------

def test_every_workflow_and_input_the_runbook_names_exists():
    names = set(re.findall(r"(?:gh workflow run|--workflow) (\w+)", RUNBOOK))
    assert {"deploy", "nightly"} <= names
    for name in names:
        assert (ROOT / ".github" / "workflows" / f"{name}.yml").is_file(), f"no workflow {name}"
    deploy = (ROOT / ".github" / "workflows" / "deploy.yml").read_text()
    for key in re.findall(r"gh workflow run deploy[^\n]* -f (\w+)=", RUNBOOK):
        assert re.search(rf"^      {key}:", deploy, re.MULTILINE), f"deploy.yml has no input {key}"


def test_every_compose_service_the_runbook_names_exists():
    compose = (ROOT / "compose.yaml").read_text()
    services = set(re.findall(r"^  (\w+):", compose, re.MULTILINE))
    named = set(re.findall(r"\bdc restart (\w+)", RUNBOOK)) | set(re.findall(r"\bdc run --rm -T (\w+)", RUNBOOK))
    named |= set(re.findall(r"\bdc logs [^\n|]*?(\w+)\s*(?:2>&1|\||$)", RUNBOOK, re.MULTILINE))
    assert {"chat", "shadow", "jobs"} <= named
    assert named <= services, f"not in compose.yaml: {sorted(named - services)}"


# ---- names in the code -----------------------------------------------------------------------------------------------

def defined_names(path):
    """Top-level names of a module, and 'Class.method' for the methods of its classes."""
    names = set()
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
            if isinstance(node, ast.ClassDef):
                names |= {f"{node.name}.{m.name}" for m in node.body if isinstance(m, ast.FunctionDef | ast.AsyncFunctionDef)}
        elif isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def test_every_name_in_the_code_that_the_runbook_cites_exists():
    cited = re.findall(r"`([A-Za-z_]\w*)\.([A-Za-z_][\w.]*)`", RUNBOOK)
    checked = 0
    for module, name in cited:
        path = ROOT / f"{module}.py"
        if name.split(".")[0] in {"py", "md", "yml", "json", "tsx"} or not path.is_file():
            continue  # a file name, or not a module of ours
        assert name in defined_names(path), f"the runbook cites {module}.{name}, which {module}.py does not define"
        checked += 1
    assert checked >= 8, "the pattern found almost nothing: the test is not reading the runbook"


# ---- the alerts: the words the runbook shows are the words the code prints --------------------------------------------

MESSAGES = [
    ("pipeline stopped, nothing written", "pipeline.py"),
    ("pipeline ok:", "pipeline.py"),
    ("carrier: file carrier-", "checks.py"),
    ("RETURN WINDOW DIFFERS", "policy_index.py"),
    ("return windows: code and pages agree", "policy_index.py"),
    ("policy index not rebuilt", "policy_index.py"),
    ("sections stored", "policy_index.py"),
    ("the assistant failed; the chat goes to a person", "app.py"),
    ("Something went wrong. Please ask for a person.", "widget/src/App.tsx"),
    ("ALERT: the assistant gave a confidently wrong answer on the latest day", "widget/src/GoLive.tsx"),
    ("Switch the assistant off", "widget/src/GoLive.tsx"),
    ("The assistant is now", "widget/src/GoLive.tsx"),
    ("NOT UP:", "deploy/check.sh"),
    ("check failed: empty reply", "deploy/check.sh"),
    ("no source link in the reply", "deploy/check.sh"),
    ("check ok", "deploy/check.sh"),
]


@pytest.mark.parametrize(("message", "source"), MESSAGES)
def test_an_alert_message_in_the_runbook_is_in_the_code(message, source):
    assert message in " ".join(RUNBOOK.split()), f"the runbook no longer shows {message!r}: update this list"
    assert message in (ROOT / source).read_text(), f"{source} no longer says {message!r}: update the runbook"


# ---- the shape of the runbook, and the links to it -------------------------------------------------------------------

def test_the_runbook_has_its_parts_and_no_secret():
    for heading in ("## Before you start", "## Gaps", "## Owners after we leave"):
        assert heading in RUNBOOK
    entries = re.findall(r"^## (\d+)\. ", RUNBOOK, re.MULTILINE)
    assert entries == [str(n) for n in range(1, len(entries) + 1)] and len(entries) == 7
    for part in ("**What it means", "**First check", "**How to act", "**How to see it worked", "**Who next"):
        assert RUNBOOK.count(part) >= 6, f"fewer than six entries have {part}"
    assert "sk-ant" not in RUNBOOK and not re.search(r"\b[\w.+-]+@[\w-]+\.\w+", RUNBOOK)


def test_the_readme_links_the_runbook_and_the_decision_record():
    records = sorted((ROOT / "docs" / "adr").glob("0001-*.md"))
    assert len(records) == 1
    for target in ("docs/runbook.md", f"docs/adr/{records[0].name}"):
        assert f"]({target})" in README, f"the README does not link {target}"
