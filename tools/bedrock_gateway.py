"""Optional, isolated Bedrock Converse gateway. No inference during setup."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "local_services" / "bedrock_gateway"
LITELLM_REQUIREMENT = "litellm[proxy]==1.103.1"
# This LiteLLM release imports Prisma while classifying authentication errors,
# even without a database. Its proxy extra does not include that dependency.
GATEWAY_REQUIREMENTS = (LITELLM_REQUIREMENT, "prisma==0.15.0")
INSTALL_RECEIPT = "\n".join(GATEWAY_REQUIREMENTS)
KEY_SLOT = "JNAIQ_BEDROCK_GATEWAY_KEY"


def gateway_config(model: str, region: str, port: int = 4000) -> dict:
    model = model.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*", model):
        raise ValueError("Copy a Bedrock model or inference profile ID from AWS.")
    if not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d+", region):
        raise ValueError("Enter an AWS region such as us-east-1.")
    if not 1024 <= port <= 65535:
        raise ValueError("The local port must be between 1024 and 65535.")
    return {
        "model_list": [{"model_name": "bedrock-chat", "litellm_params": {
            "model": "bedrock/converse/" + model,
            "aws_region_name": region,
            "api_key": "os.environ/AWS_BEARER_TOKEN_BEDROCK",
        }}],
        "general_settings": {"master_key": "os.environ/" + KEY_SLOT},
        # Shed parameters the target rejects; never invent a system message,
        # switch models, or install provider logging callbacks.
        "litellm_settings": {"drop_params": True, "set_verbose": False},
        "jnaiq": {"port": port},
    }


def child_environment(current_key) -> dict:
    env = os.environ.copy()
    for name in ("AWS_BEARER_TOKEN_BEDROCK", KEY_SLOT):
        value = current_key(name)
        if not value:
            raise ValueError(
                f"{name} is missing. Save the Bedrock API key in JNAIQ "
                "Settings → API keys, then run this launcher again.")
        env[name] = value
    env["LITELLM_TELEMETRY"] = "False"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configure", action="store_true",
                        help="Choose a new model/region; preserve the previous config.")
    parser.add_argument("--model", help="Bedrock model or inference profile ID")
    parser.add_argument("--region", help="AWS region")
    parser.add_argument("--port", type=int, default=4000)
    args = parser.parse_args(argv)
    sys.path.insert(0, str(ROOT))
    from shell import env_store

    print("JNAIQ Bedrock gateway · optional setup")
    print("This gateway relays conversations to AWS. AWS inference charges apply.")
    config_path = GATEWAY / "config.json"
    if args.configure or args.model or not config_path.exists():
        model = args.model or input("Bedrock model / inference profile ID: ").strip()
        region = args.region or input("AWS region [us-east-1]: ").strip() or "us-east-1"
        config = gateway_config(model, region, args.port)
        if not env_store.current_key("AWS_BEARER_TOKEN_BEDROCK"):
            raise ValueError("Save AWS_BEARER_TOKEN_BEDROCK in JNAIQ Settings → "
                             "API keys first. The secret never goes in this configuration.")
        if not env_store.current_key(KEY_SLOT):
            env_store.set_key(KEY_SLOT, "sk-" + secrets.token_urlsafe(32))
        GATEWAY.mkdir(parents=True, exist_ok=True)
        if config_path.exists():
            config_path.with_suffix(".json.prev").write_bytes(config_path.read_bytes())
        # JSON is a YAML subset and safely encodes identifiers without interpolation.
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    else:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    port = int(config.get("jnaiq", {}).get("port", 4000))
    if not 1024 <= port <= 65535:
        raise ValueError("The saved local port must be between 1024 and 65535.")
    env = child_environment(env_store.current_key)
    environment = GATEWAY / ".venv"
    binaries = environment / ("Scripts" if os.name == "nt" else "bin")
    python = binaries / ("python.exe" if os.name == "nt" else "python")
    executable = binaries / ("litellm.exe" if os.name == "nt" else "litellm")
    receipt = GATEWAY / "installed-version.txt"
    if not python.exists():
        print("Creating the gateway's separate environment…")
        venv.create(environment, with_pip=True)
    if not executable.exists() or not receipt.exists() \
            or receipt.read_text().strip() != INSTALL_RECEIPT:
        print("Installing the optional gateway dependencies; JNAIQ's environment stays separate…")
        subprocess.run([str(python), "-m", "pip", "install",
                        "--disable-pip-version-check", *GATEWAY_REQUIREMENTS], check=True)
        receipt.write_text(INSTALL_RECEIPT + "\n", encoding="utf-8")
    print(f"In JNAIQ: Install model → OpenAI-compatible → Amazon Bedrock · Converse gateway.")
    print(f"Base URL: http://127.0.0.1:{port}/v1 · model ID: bedrock-chat")
    print("Keep this window open while using the gateway. Ctrl+C stops it.")
    return subprocess.call([str(executable), "--config", str(config_path),
                            "--host", "127.0.0.1", "--port", str(port),
                            "--telemetry", "False"], env=env)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        # Never print a subprocess environment or provider response.
        print(f"Gateway setup stopped: {error}", file=sys.stderr)
        raise SystemExit(1)
