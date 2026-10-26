"""Is everything ready for the course? Checks your environment and DemoStore's systems; it only reads, nothing is changed.

    python doctor.py              everything, with one tiny call to Claude to check your key (a fraction of a cent)
    python doctor.py --no-call    everything except the call

Settings come from the environment first, then from .env (the product) and sandbox/.env (the labs).
"""
import importlib
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OK, BAD, WARN = "  ok  ", "  NO  ", " note "
problems: list[str] = []


def say(mark, what, detail=""):
    print(f"[{mark}] {what}" + (f": {detail}" if detail else ""))
    if mark == BAD:
        problems.append(what)


def settings():
    """The values of both .env files, the environment winning (as python-dotenv does)."""
    values = {}
    for file in (HERE / "sandbox" / ".env", HERE / ".env"):
        if file.exists():
            for line in file.read_text().splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    name, value = line.split("=", 1)
                    values.setdefault(name.strip(), value.strip().strip('"'))
    values.update(os.environ)
    return values


def tools():
    print("Your tools")
    v = sys.version_info
    say(OK if v >= (3, 12) else BAD, "Python", f"{v.major}.{v.minor}.{v.micro}" + ("" if v >= (3, 12) else ", the course needs 3.12 or newer"))
    missing = []
    for module in ["anthropic", "dotenv", "fastapi", "uvicorn", "httpx", "pytest", "oracledb", "psycopg", "paramiko",
                   "pandas", "fastembed", "pgvector", "ruff", "mypy", "pre_commit"]:
        try:
            importlib.import_module(module)
        except ImportError:
            missing.append(module)
    say(BAD if missing else OK, "Python packages",
        f"missing {', '.join(missing)}: pip install -r requirements.txt -r sandbox/requirements.txt" if missing else "all there")
    for tool, why in [("node", "the widget"), ("npm", "the widget"), ("docker", "DemoStore's systems"), ("git", "the tags"),
                      ("claude", "the build lessons (Claude Code)")]:
        path = shutil.which(tool)
        if not path:
            say(WARN if tool in ("claude", "docker") else BAD, tool, f"not found, needed for {why}")
            continue
        out = subprocess.run([tool, "--version"], capture_output=True, text=True, timeout=20, check=False).stdout.strip().splitlines()
        say(OK, tool, out[0] if out else path)
    say(OK if (HERE / "widget" / "node_modules").exists() else WARN, "widget packages",
        "installed" if (HERE / "widget" / "node_modules").exists() else "not yet: cd widget && npm ci")


def port(host, number):
    try:
        with socket.create_connection((host, number), timeout=2):
            return True
    except OSError:
        return False


def get(url, auth=None):
    import httpx
    return httpx.get(url, auth=auth, timeout=5)


def systems(s):
    print("\nDemoStore's systems (start them: docker compose -f sandbox/systems/compose.yaml up -d)")
    try:
        import oracledb
        dsn = s.get("LEDGERLINE_DSN", "localhost:1521/FREEPDB1")
        with oracledb.connect(user=s.get("LEDGERLINE_USER", "LL_READER"), password=s.get("LEDGERLINE_PASSWORD", "reader"), dsn=dsn) as db:
            orders = db.cursor().execute("SELECT COUNT(*) FROM LEDGERLINE.LL_ORD_HDR").fetchone()[0]
        say(OK, "Ledgerline (the ERP)", f"{orders} orders, read-only account")
    except Exception as e:  # noqa: BLE001 - a doctor reports every failure, whatever its kind
        say(BAD, "Ledgerline (the ERP)", f"{type(e).__name__}: {str(e).splitlines()[0][:90]} (the first start takes a few minutes)")
    try:
        import paramiko
        t = paramiko.Transport((s.get("CARRIER_HOST", "127.0.0.1"), int(s.get("CARRIER_PORT", "2222"))))
        t.connect(username=s.get("CARRIER_USER", "demostore"), password=s.get("CARRIER_PASSWORD", "feed"))
        files = paramiko.SFTPClient.from_transport(t).listdir("upload")
        t.close()
        say(OK, "carrier SFTP", f"{len(files)} nightly files")
    except Exception as e:  # noqa: BLE001
        say(BAD, "carrier SFTP", f"{type(e).__name__}: {str(e)[:90]}")
    try:
        import psycopg
        for name, url in [("labs", s.get("OURDB_URL", "postgresql://demostore:demostore@127.0.0.1:5432/assistant")),
                          ("product", s.get("STORE_URL", "postgresql://demostore:demostore@127.0.0.1:5432/product"))]:
            with psycopg.connect(url, connect_timeout=5) as db:
                vector = db.execute("SELECT count(*) FROM pg_available_extensions WHERE name = 'vector'").fetchone()[0]
            say(OK if vector else BAD, f"our PostgreSQL, {name} database", "pgvector available" if vector else "pgvector missing")
    except Exception as e:  # noqa: BLE001
        say(BAD, "our PostgreSQL", f"{type(e).__name__}: {str(e).splitlines()[0][:90]}")
    checks = [("Mailpit (one-time codes)", s.get("MAILPIT_URL", "http://127.0.0.1:8025") + "/api/v1/info", None),
              ("ServiceNow stand-in", s.get("SERVICENOW_URL", "http://127.0.0.1:8020") + "/live", None),
              ("Atlas stand-in", s.get("ATLAS_URL", "http://127.0.0.1:8030") + "/products", None),
              ("Confluence stand-in", s.get("CONFLUENCE_URL", "http://127.0.0.1:8040") + "/rest/api/content?spaceKey=POL", None)]
    for what, url, auth in checks:
        try:
            r = get(url, auth)
            say(OK if r.status_code == 200 else BAD, what, f"HTTP {r.status_code}")
        except Exception as e:  # noqa: BLE001
            say(BAD, what, f"{type(e).__name__} at {url.split('/')[2]}")
    busy = [p for p in (8000, 5173) if port("127.0.0.1", p)]
    say(WARN if busy else OK, "ports for the chat (8000) and the widget (5173)",
        f"in use now: {busy} (fine if it is your own chat service)" if busy else "free")


def key(s, call):
    print("\nYour Claude API key")
    value = s.get("ANTHROPIC_API_KEY", "")
    if not value or "your-key-here" in value:
        say(BAD, "ANTHROPIC_API_KEY", "not set: a Codespaces secret, or the line in .env (never commit .env)")
        return
    say(OK, "ANTHROPIC_API_KEY", "set")
    if not call:
        return
    try:
        import anthropic
        reply = anthropic.Anthropic(api_key=value).messages.create(
            model="claude-haiku-5-5", max_tokens=5, messages=[{"role": "user", "content": "Say OK."}])
        say(OK, "one call to Claude", f"answered, {reply.usage.input_tokens} + {reply.usage.output_tokens} tokens")
    except Exception as e:  # noqa: BLE001
        say(BAD, "one call to Claude", f"{type(e).__name__}: {str(e)[:120]}")
    print("[ note ] Set a monthly spend limit for this key in the Claude Console (Settings, Limits) before the labs.")


if __name__ == "__main__":
    s = settings()
    tools()
    systems(s)
    key(s, "--no-call" not in sys.argv)
    print("\nAll green." if not problems else f"\n{len(problems)} to fix: {', '.join(problems)}")
    sys.exit(1 if problems else 0)
