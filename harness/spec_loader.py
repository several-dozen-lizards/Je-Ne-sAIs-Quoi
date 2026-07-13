"""Spec loader — reads declarative model specs from specs/models/."""
import os
import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC_DIR = os.path.join(REPO_ROOT, "specs", "models")


def load_spec(name: str) -> dict:
    path = os.path.join(SPEC_DIR, f"{name}.yaml")
    if not os.path.exists(path):
        raise FileNotFoundError(f"No spec: {path}")
    with open(path, "r", encoding="utf-8") as f:
        spec = yaml.safe_load(f)
    spec["_spec_path"] = path
    return spec


def load_all() -> list:
    specs = []
    for fn in sorted(os.listdir(SPEC_DIR)):
        if fn.endswith(".yaml") and fn != "SCHEMA.yaml":
            specs.append(load_spec(fn[:-5]))
    return specs
