"""shell/env_store.py — the gitignored .env at the repo root, loaded
into the process environment at import, plus a VALIDATE-FIRST, atomic
writer so the settings UI can add keys.

KEY LAW (repo-wide): a key VALUE lives in the environment (here, the
.env) and NEVER in a spec, a log, or an API response. Specs NAME the env
var; this module is the only thing that moves values.

PRECEDENCE: a var already set in the real process env (shell-exported,
or inherited from a parent that already loaded .env) WINS over the file
— load uses setdefault. A power user's export overrides the UI file, and
a child subprocess that inherited the router's env isn't stomped by a
re-parse.

UI SEMANTICS: set_key writes the file AND updates THIS process's
os.environ at once (presence reflects immediately). Persona SUBPROCESSES
already running don't see a new key until their next Start — they
inherit the router's env at spawn. Stated honestly in the panel."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(ROOT, ".env")
_NAME_RE = re.compile(r"[A-Z][A-Z0-9_]*$")  # UPPER_SNAKE env var NAME


def _parse(text: str):
    """[(kind, key, rawline)] preserving order & comments. kind is 'kv'
    (KEY=value with an UPPER_SNAKE name) or 'raw' (comment/blank/other)."""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if (s and not s.startswith("#") and "=" in s
                and not s.startswith("export ")):
            key = s.split("=", 1)[0].strip()
            if _NAME_RE.match(key):
                out.append(("kv", key, line))
                continue
        out.append(("raw", None, line))
    return out


def _value_of(line: str) -> str:
    return line.split("=", 1)[1].strip().strip('"').strip("'")


def load_env(path: str = ENV_PATH) -> int:
    """setdefault each KEY=VALUE from .env into os.environ (env wins over
    file). Returns count newly set. Missing file is fine (fresh checkout,
    no keys yet — this is the normal first-run state)."""
    if not os.path.exists(path):
        return 0
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    n = 0
    for kind, key, line in _parse(text):
        if kind == "kv" and key not in os.environ:
            os.environ[key] = _value_of(line)
            n += 1
    return n


def validate_name(name: str) -> str:
    name = (name or "").strip()
    if not _NAME_RE.match(name):
        raise ValueError(f"env var NAME must be UPPER_SNAKE, e.g. "
                         f"OPENAI_API_KEY (got '{name}')")
    return name


def _atomic_write(path: str, text: str):
    """unique tmp + os.replace — the 07-05 atomic-persist pattern."""
    tmp = f"{path}.tmp_{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def set_key(name: str, value: str, path: str = ENV_PATH) -> dict:
    """VALIDATE-FIRST atomic upsert of KEY=value, then update THIS
    process's os.environ live. Preserves other lines & comments. NEVER
    returns or logs the value — presence only."""
    name = validate_name(name)
    if value is None or value == "":
        raise ValueError("value must be non-empty "
                         "(to remove a key use unset_key)")
    if "\n" in value or "\r" in value:
        raise ValueError("value must be a single line")
    existing = ""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            existing = f.read()
    new_line = f'{name}="{value}"'
    lines, replaced = [], False
    for kind, key, line in _parse(existing):
        if kind == "kv" and key == name:
            lines.append(new_line)
            replaced = True
        else:
            lines.append(line)
    if not replaced:
        if lines and lines[-1].strip() != "":
            lines.append("")
        lines.append(new_line)
    _atomic_write(path, "\n".join(lines).rstrip("\n") + "\n")
    os.environ[name] = value  # live in THIS process
    return {"env": name, "set": True}  # <- never the value


def unset_key(name: str, path: str = ENV_PATH) -> dict:
    """Remove a key from .env and from this process's os.environ."""
    name = validate_name(name)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            existing = f.read()
        lines = [line for kind, key, line in _parse(existing)
                 if not (kind == "kv" and key == name)]
        _atomic_write(path, "\n".join(lines).rstrip("\n") + "\n")
    os.environ.pop(name, None)
    return {"env": name, "set": False}


def presence(names) -> dict:
    """{name: bool(set)} — presence ONLY, values never leave this module."""
    return {n: bool(os.environ.get(n)) for n in names}


# Load on import: any process entry point that imports env_store gets the
# .env applied to os.environ BEFORE it constructs model clients. The
# router imports this (after its sys.path shim) so children inherit the
# keys at spawn; cockpit imports it too for standalone/dev runs.
load_env()
