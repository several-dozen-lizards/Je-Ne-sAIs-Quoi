"""Local persona identity media.

Avatar bytes live inside the persona directory; the roster stores only a
relative reference.  Nothing is uploaded to a service and no machine path is
allowed to cross the roster boundary.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import re

import yaml


MAX_AVATAR_BYTES = 8 * 1024 * 1024
_DATA_URL = re.compile(r"^data:([^;,]+);base64,(.+)$", re.DOTALL)
_MIME_EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}
_EXTENSION_MIME = {extension: mime
                   for mime, extension in _MIME_EXTENSIONS.items()}


def _detected_extension(payload: bytes) -> str | None:
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if payload.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if len(payload) >= 12 and payload[:4] == b"RIFF" \
            and payload[8:12] == b"WEBP":
        return "webp"
    if payload.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    return None


def write_roster_scalar(persona_dir: str, key: str, value: str) -> str:
    """Atomically update one top-level quoted roster scalar."""
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", key):
        raise ValueError("invalid roster metadata key")
    path = os.path.join(persona_dir, "roster.yaml")
    if not os.path.isfile(path):
        raise FileNotFoundError("persona roster does not exist")
    with open(path, encoding="utf-8", newline="") as handle:
        original = handle.read()
    newline = "\r\n" if "\r\n" in original else "\n"
    lines = original.splitlines(keepends=True)
    rendered = f"{key}: {json.dumps(value, ensure_ascii=False)}{newline}"
    replaced = False
    for index, line in enumerate(lines):
        if line.startswith(f"{key}:"):
            lines[index] = rendered
            replaced = True
            break
    if not replaced:
        insert_at = next((index + 1 for index, line in enumerate(lines)
                          if line.startswith("display_name:")), None)
        if insert_at is None:
            insert_at = next((index + 1 for index, line in enumerate(lines)
                              if line.startswith("persona:")), 0)
        lines.insert(insert_at, rendered)
    candidate = "".join(lines)
    parsed = yaml.safe_load(candidate)
    if not isinstance(parsed, dict) or parsed.get(key) != value:
        raise ValueError(f"persona {key} edit failed validation")
    with open(path + ".prev", "w", encoding="utf-8", newline="") as handle:
        handle.write(original)
    temporary = path + f".tmp_{key}"
    with open(temporary, "w", encoding="utf-8", newline="") as handle:
        handle.write(candidate)
    os.replace(temporary, path)
    return value


def write_roster_mapping_scalar(persona_dir: str, section: str, key: str,
                                value) -> object:
    """Atomically update one scalar inside a top-level roster mapping.

    The hand-formatted roster remains byte-stable outside the one mapping.
    ``None`` is a meaningful value: it disables an optional route without
    inventing a replacement.
    """
    for name in (section, key):
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", name):
            raise ValueError("invalid roster mapping key")
    path = os.path.join(persona_dir, "roster.yaml")
    if not os.path.isfile(path):
        raise FileNotFoundError("persona roster does not exist")
    with open(path, encoding="utf-8", newline="") as handle:
        original = handle.read()
    newline = "\r\n" if "\r\n" in original else "\n"
    lines = original.splitlines(keepends=True)
    section_index = next((i for i, line in enumerate(lines)
                          if re.match(rf"^{re.escape(section)}:\s*(?:#.*)?(?:\r?\n)?$", line)), None)
    rendered = f"  {key}: {json.dumps(value, ensure_ascii=False)}{newline}"
    if section_index is None:
        insert_at = next((i for i, line in enumerate(lines)
                          if line.startswith(("enabled_organs:", "room:",
                                              "entries:"))), len(lines))
        lines[insert_at:insert_at] = [f"{section}:{newline}", rendered]
    else:
        section_end = next((i for i in range(section_index + 1, len(lines))
                            if lines[i] and not lines[i][0].isspace()
                            and not lines[i].lstrip().startswith("#")), len(lines))
        key_index = next((i for i in range(section_index + 1, section_end)
                          if re.match(rf"^  {re.escape(key)}:", lines[i])), None)
        if key_index is None:
            lines.insert(section_index + 1, rendered)
        else:
            lines[key_index] = rendered
    candidate = "".join(lines)
    parsed = yaml.safe_load(candidate)
    if not isinstance(parsed, dict) or not isinstance(parsed.get(section), dict) \
            or parsed[section].get(key) != value:
        raise ValueError(f"persona {section}.{key} edit failed validation")
    with open(path + ".prev", "w", encoding="utf-8", newline="") as handle:
        handle.write(original)
    temporary = path + f".tmp_{section}_{key}"
    with open(temporary, "w", encoding="utf-8", newline="") as handle:
        handle.write(candidate)
    os.replace(temporary, path)
    return value


def save_persona_avatar(persona_dir: str, data_url: str) -> dict:
    """Validate and atomically store an image under ``<persona>/ui``."""
    match = _DATA_URL.match((data_url or "").strip())
    if not match:
        raise ValueError("avatar must be a base64 image upload")
    declared_mime, encoded = match.groups()
    declared_mime = declared_mime.lower()
    expected_extension = _MIME_EXTENSIONS.get(declared_mime)
    if not expected_extension:
        raise ValueError("avatar must be PNG, JPEG, WebP, or GIF")
    if len(encoded) > (MAX_AVATAR_BYTES * 4 // 3) + 8:
        raise ValueError("avatar image is larger than 8 MiB")
    try:
        payload = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("avatar image data is not valid base64") from error
    if not payload:
        raise ValueError("avatar image is empty")
    if len(payload) > MAX_AVATAR_BYTES:
        raise ValueError("avatar image is larger than 8 MiB")
    detected_extension = _detected_extension(payload)
    if detected_extension != expected_extension:
        raise ValueError("avatar file contents do not match its image type")

    ui_dir = os.path.join(persona_dir, "ui")
    os.makedirs(ui_dir, exist_ok=True)
    filename = f"avatar.{detected_extension}"
    path = os.path.join(ui_dir, filename)
    temporary = path + ".tmp"
    with open(temporary, "wb") as handle:
        handle.write(payload)
    os.replace(temporary, path)
    relative = f"ui/{filename}"
    write_roster_scalar(persona_dir, "avatar", relative)

    # A replacement may change format. Once the roster points to the new
    # image, retire only obsolete avatar siblings created by this feature.
    for old_name in os.listdir(ui_dir):
        if old_name.startswith("avatar.") and old_name != filename \
                and not old_name.endswith(".tmp"):
            old_path = os.path.join(ui_dir, old_name)
            if os.path.isfile(old_path):
                os.remove(old_path)
    return {"path": path, "relative": relative,
            "mime": _EXTENSION_MIME[detected_extension]}


def load_persona_avatar(persona_dir: str) -> dict | None:
    """Resolve a roster avatar while refusing absolute/path-escape values."""
    roster_path = os.path.join(persona_dir, "roster.yaml")
    if not os.path.isfile(roster_path):
        return None
    with open(roster_path, encoding="utf-8") as handle:
        roster = yaml.safe_load(handle) or {}
    relative = str(roster.get("avatar") or "").replace("\\", "/").strip()
    if not relative or os.path.isabs(relative):
        return None
    root = os.path.realpath(persona_dir)
    path = os.path.realpath(os.path.join(root, *relative.split("/")))
    try:
        if os.path.commonpath([root, path]) != root:
            return None
    except ValueError:
        return None
    extension = os.path.splitext(path)[1].lower().lstrip(".")
    mime = _EXTENSION_MIME.get(extension)
    if not mime or not os.path.isfile(path):
        return None
    return {"path": path, "relative": relative, "mime": mime,
            "version": os.stat(path).st_mtime_ns}
