"""Machine-local solo-chat background storage.

The file is deliberately separate from theme JSON: opacity and selection are
theme tokens, while the potentially large private image remains one local
asset that presets can reference without copying it.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import tempfile

MAX_BYTES = 12 * 1024 * 1024
ALLOWED = {"image/png", "image/jpeg", "image/webp", "image/gif"}
KINDS = {
    "outer": "conversation_background",
    "conversation_area": "conversation_area_background",
    "nexus": "nexus_background",
}


def _paths(repo: str, kind: str = "outer"):
    stem = KINDS.get(kind)
    if not stem:
        raise ValueError("unknown background image kind")
    root = os.path.join(repo, "shell", "ui")
    return (os.path.join(root, stem + ".bin"),
            os.path.join(root, stem + ".json"))


def load_background(repo: str, kind: str):
    image_path, meta_path = _paths(repo, kind)
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        mime = meta.get("mime")
        if mime not in ALLOWED or not os.path.isfile(image_path):
            return None
        return {"path": image_path, "mime": mime,
                "revision": meta.get("revision") or "0"}
    except (OSError, ValueError, TypeError):
        return None


def save_background(repo: str, kind: str, data_url: str):
    if not isinstance(data_url, str) or not data_url.startswith("data:"):
        raise ValueError("background must be an image data URL")
    header, sep, encoded = data_url.partition(",")
    mime = header[5:].split(";", 1)[0].lower()
    if not sep or ";base64" not in header or mime not in ALLOWED:
        raise ValueError("background must be PNG, JPEG, WebP, or GIF")
    if len(encoded) > (MAX_BYTES * 4 // 3) + 8:
        raise ValueError("background image exceeds the 12 MB limit")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("background image is not valid base64")
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("background image is empty or exceeds the 12 MB limit")
    signatures = {
        "image/png": raw.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg": raw.startswith(b"\xff\xd8\xff"),
        "image/webp": raw.startswith(b"RIFF") and raw[8:12] == b"WEBP",
        "image/gif": raw.startswith((b"GIF87a", b"GIF89a")),
    }
    if not signatures[mime]:
        raise ValueError("background bytes do not match the declared image type")
    image_path, meta_path = _paths(repo, kind)
    os.makedirs(os.path.dirname(image_path), exist_ok=True)
    revision = hashlib.sha256(raw).hexdigest()[:16]
    for path, payload, binary in (
            (image_path, raw, True),
            (meta_path, json.dumps({"mime": mime, "revision": revision},
                                   indent=2) + "\n", False)):
        fd, tmp = tempfile.mkstemp(prefix=f".{KINDS[kind]}-",
                                   dir=os.path.dirname(path))
        try:
            mode = "wb" if binary else "w"
            with os.fdopen(fd, mode, encoding=None if binary else "utf-8") as f:
                f.write(payload)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    return load_background(repo, kind)


def delete_background(repo: str, kind: str) -> bool:
    removed = False
    for path in _paths(repo, kind):
        if os.path.exists(path):
            os.unlink(path)
            removed = True
    return removed


def load_conversation_background(repo: str):
    """Backward-compatible name for the outer solo-chat wallpaper."""
    return load_background(repo, "outer")


def save_conversation_background(repo: str, data_url: str):
    return save_background(repo, "outer", data_url)


def delete_conversation_background(repo: str) -> bool:
    return delete_background(repo, "outer")


def load_conversation_area_background(repo: str):
    return load_background(repo, "conversation_area")


def save_conversation_area_background(repo: str, data_url: str):
    return save_background(repo, "conversation_area", data_url)


def delete_conversation_area_background(repo: str) -> bool:
    return delete_background(repo, "conversation_area")


def load_nexus_background(repo: str):
    """Load the Nexus-only wallpaper without touching household media."""
    return load_background(repo, "nexus")


def save_nexus_background(repo: str, data_url: str):
    return save_background(repo, "nexus", data_url)


def delete_nexus_background(repo: str) -> bool:
    return delete_background(repo, "nexus")
