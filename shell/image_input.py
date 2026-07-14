"""Local image intake for cockpit turns.

The browser supplies data URLs because every persona cockpit is local.  This
boundary validates the claimed type against the bytes, stores one
content-addressed copy in the persona's own body, and hands the turn engine a
wire-neutral image record.  Provider-specific shapes belong to adapters.
"""
import base64
import binascii
import hashlib
import os
import re


MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGES_PER_TURN = 4
ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
_DATA_URL = re.compile(
    r"^data:(image/(?:jpeg|png|webp|gif));base64,([A-Za-z0-9+/=\r\n]+)$",
    re.IGNORECASE)


def _detected_type(raw: bytes) -> str:
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return ""


def _safe_name(name: str, mime: str) -> str:
    name = os.path.basename((name or "image").strip())
    stem = os.path.splitext(name)[0]
    stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", stem).strip(" ._")[:80]
    return (stem or "image") + ALLOWED_IMAGE_TYPES[mime]


def decode_image(data_url: str, name: str = "image") -> dict:
    """Validate one browser image and return a wire-neutral record."""
    match = _DATA_URL.match(data_url or "")
    if not match:
        raise ValueError("image must be a base64 PNG, JPEG, WebP, or GIF")
    claimed = match.group(1).lower()
    try:
        raw = base64.b64decode(match.group(2), validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("image contains invalid base64 data")
    if not raw:
        raise ValueError("image is empty")
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("each image must be 10 MB or smaller")
    detected = _detected_type(raw)
    if not detected or detected != claimed:
        raise ValueError("image bytes do not match the declared image type")
    digest = hashlib.sha256(raw).hexdigest()
    return {
        "id": digest,
        "name": _safe_name(name, detected),
        "media_type": detected,
        "data": base64.b64encode(raw).decode("ascii"),
        "bytes": len(raw),
    }


def store_images(persona_dir: str, uploads: list) -> list:
    """Decode and persist a bounded turn's uploads inside the persona."""
    if len(uploads or []) > MAX_IMAGES_PER_TURN:
        raise ValueError(f"a turn can carry at most {MAX_IMAGES_PER_TURN} images")
    records = [decode_image(item.get("data_url"), item.get("name", "image"))
               for item in (uploads or [])]
    total = sum(item["bytes"] for item in records)
    if total > MAX_IMAGE_BYTES * 2:
        raise ValueError("images in one turn must total 20 MB or smaller")
    folder = os.path.join(persona_dir, "body", "perception", "images")
    if records:
        os.makedirs(folder, exist_ok=True)
    for item in records:
        ext = ALLOWED_IMAGE_TYPES[item["media_type"]]
        path = os.path.join(folder, item["id"] + ext)
        if not os.path.exists(path):
            with open(path, "wb") as handle:
                handle.write(base64.b64decode(item["data"]))
        item["path"] = path
        item["url"] = f"/api/images/{item['id']}"
    return records


def public_image_record(item: dict) -> dict:
    """Metadata safe for memory, receipts, and browser hydration."""
    return {key: item[key] for key in
            ("id", "name", "media_type", "bytes", "url") if key in item}


def stored_image_path(persona_dir: str, image_id: str):
    """Resolve a content id without allowing paths to escape the image store."""
    if not re.fullmatch(r"[0-9a-f]{64}", image_id or ""):
        return None
    folder = os.path.join(persona_dir, "body", "perception", "images")
    for ext in ALLOWED_IMAGE_TYPES.values():
        path = os.path.join(folder, image_id + ext)
        if os.path.isfile(path):
            mime = next(k for k, value in ALLOWED_IMAGE_TYPES.items()
                        if value == ext)
            return path, mime
    return None
