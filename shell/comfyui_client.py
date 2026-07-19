"""Loopback-only ComfyUI renderer for the private Atelier.

The client submits one closed core-node workflow, waits on ComfyUI's event
stream, retrieves one output, and returns bytes to the Atelier host boundary.
It cannot address a remote server and never sends API keys or partner-node
credentials.  Artifact validation and durable storage remain core.atelier's
job rather than ComfyUI's.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Mapping


CORE_WORKFLOW_NODES = frozenset({
    "CheckpointLoaderSimple", "EmptyLatentImage", "CLIPTextEncode",
    "KSampler", "VAEDecode", "SaveImage",
})
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _finite(value: Any, fallback=0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(fallback)
    return number if math.isfinite(number) else float(fallback)


def _unit(value: Any, fallback=0.0) -> float:
    return max(0.0, min(1.0, _finite(value, fallback)))


def _round64(value: float) -> int:
    return max(512, min(1024, int(round(float(value) / 64.0) * 64)))


def derive_diffusion_parameters(source_digest: str,
                                expression_vector: Mapping[str, Any],
                                aspect: float) -> dict:
    """Map the current vector into bounded SDXL sampling parameters."""
    vector = dict(expression_vector or {})
    coherence = _unit(vector.get("band.coherence"), .5)
    curiosity = _unit(vector.get("cocktail.curiosity"), .5)
    warmth = _unit(vector.get("cocktail.warmth"), .5)
    aspect = max(.625, min(1.6, _finite(aspect, 1.0)))
    # A continuous pixel budget and aspect become Comfy's required 64-pixel
    # lattice only at the renderer boundary.  Nothing cognitive maps to a
    # named visual style or emotion preset.
    pixel_budget = 589_824.0 + 196_608.0 * coherence
    width = _round64(math.sqrt(pixel_budget * aspect))
    height = _round64(math.sqrt(pixel_budget / aspect))
    seed_material = f"{source_digest}|{coherence:.6f}|{curiosity:.6f}|{warmth:.6f}"
    seed = int(hashlib.sha256(seed_material.encode("utf-8")).hexdigest()[:15], 16)
    return {
        "seed": seed,
        "width": width,
        "height": height,
        "steps": 20 + int(round(10.0 * coherence)),
        "cfg": round(5.0 + 1.4 * (0.65 * curiosity + 0.35 * warmth), 3),
        "sampler_name": "dpmpp_2m",
        "scheduler": "karras",
    }


def build_sdxl_workflow(*, checkpoint: str, prompt: str,
                        negative_prompt: str, parameters: Mapping[str, Any],
                        filename_prefix: str) -> dict:
    checkpoint = str(checkpoint or "").strip()
    prompt = str(prompt or "").strip()
    if not checkpoint or not prompt:
        raise ValueError("diffusion requires a checkpoint and positive prompt")
    if len(checkpoint) > 260 or len(prompt) > 6000 \
            or len(str(negative_prompt or "")) > 3000:
        raise ValueError("diffusion workflow text exceeds its boundary")
    if not str(filename_prefix or "").startswith("jnsq_atelier/"):
        raise ValueError("diffusion output prefix escaped the Atelier namespace")
    p = dict(parameters or {})
    workflow = {
        "3": {"class_type": "KSampler", "inputs": {
            "seed": int(p["seed"]), "steps": int(p["steps"]),
            "cfg": float(p["cfg"]), "sampler_name": str(p["sampler_name"]),
            "scheduler": str(p["scheduler"]), "denoise": 1.0,
            "model": ["4", 0], "positive": ["6", 0],
            "negative": ["7", 0], "latent_image": ["5", 0],
        }},
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {
            "ckpt_name": checkpoint}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {
            "width": int(p["width"]), "height": int(p["height"]),
            "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {
            "text": prompt, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {
            "text": str(negative_prompt or ""), "clip": ["4", 1]}},
        "8": {"class_type": "VAEDecode", "inputs": {
            "samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {
            "filename_prefix": filename_prefix, "images": ["8", 0]}},
    }
    classes = {node["class_type"] for node in workflow.values()}
    if not classes <= CORE_WORKFLOW_NODES:
        raise ValueError("diffusion workflow contains a non-core node")
    return workflow


@dataclass(frozen=True)
class ComfyUIConfig:
    endpoint: str = "http://127.0.0.1:8188"
    checkpoint: str = "sd_xl_base_1.0.safetensors"
    execution_timeout: float = 420.0

    def __post_init__(self):
        parsed = urllib.parse.urlsplit(str(self.endpoint or ""))
        if parsed.scheme != "http" or parsed.hostname not in LOOPBACK_HOSTS \
                or parsed.username or parsed.password \
                or parsed.path.rstrip("/") or parsed.query or parsed.fragment:
            raise ValueError("ComfyUI endpoint must be an unauthenticated loopback HTTP origin")
        if not str(self.checkpoint or "").strip() \
                or len(str(self.checkpoint)) > 260:
            raise ValueError("ComfyUI checkpoint must be explicitly named")
        if not 30 <= float(self.execution_timeout) <= 1800:
            raise ValueError("ComfyUI execution timeout must be 30 through 1800 seconds")
        object.__setattr__(self, "endpoint", self.endpoint.rstrip("/"))
        object.__setattr__(self, "checkpoint", str(self.checkpoint).strip())


class ComfyUIClient:
    def __init__(self, config: ComfyUIConfig, *,
                 json_request: Callable = None,
                 bytes_request: Callable = None,
                 websocket_factory: Callable = None,
                 now_fn=time.monotonic):
        self.config = config
        self._json_request = json_request or self._default_json
        self._bytes_request = bytes_request or self._default_bytes
        self._websocket_factory = websocket_factory
        self._now = now_fn
        self.last_probe = None

    def _url(self, path: str, query: Mapping[str, Any] = None) -> str:
        if not str(path).startswith("/"):
            raise ValueError("ComfyUI path must be absolute")
        return self.config.endpoint + path + (
            "?" + urllib.parse.urlencode(dict(query or {})) if query else "")

    @staticmethod
    def _default_json(url: str, *, payload=None, timeout=5.0):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _default_bytes(url: str, *, timeout=30.0):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=timeout) as response:
            data = response.read(32 * 1024 * 1024 + 1)
            if len(data) > 32 * 1024 * 1024:
                raise ValueError("ComfyUI output exceeded the byte boundary")
            return data

    def probe(self) -> dict:
        started = self._now()
        try:
            stats = self._json_request(
                self._url("/system_stats"), timeout=3.0)
            checkpoints = self._json_request(
                self._url("/models/checkpoints"), timeout=3.0)
            names = [str(value) for value in checkpoints] \
                if isinstance(checkpoints, list) else []
            checkpoint_ready = self.config.checkpoint in names
            result = {
                "reachable": True, "checkpoint_ready": checkpoint_ready,
                "checkpoint": self.config.checkpoint,
                "available_checkpoints": len(names),
                "device_count": len(dict(stats or {}).get("devices") or []),
                "latency_ms": round((self._now() - started) * 1000.0, 3),
                "reason": ("ready" if checkpoint_ready
                           else "configured checkpoint is not installed"),
            }
        except Exception as exc:
            result = {
                "reachable": False, "checkpoint_ready": False,
                "checkpoint": self.config.checkpoint,
                "available_checkpoints": 0, "device_count": 0,
                "latency_ms": round((self._now() - started) * 1000.0, 3),
                "reason": f"ComfyUI unavailable: {type(exc).__name__}",
            }
        self.last_probe = result
        return dict(result)

    def _websocket(self, client_id: str):
        parsed = urllib.parse.urlsplit(self.config.endpoint)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        url = urllib.parse.urlunsplit((
            scheme, parsed.netloc, "/ws", f"clientId={client_id}", ""))
        if self._websocket_factory is not None:
            return self._websocket_factory(url, timeout=1.0)
        import websocket
        return websocket.create_connection(
            url, timeout=1.0, http_proxy_host=None,
            http_no_proxy=["127.0.0.1", "localhost", "::1"])

    def generate(self, *, prompt: str, negative_prompt: str,
                 source_digest: str, expression_vector: Mapping[str, Any],
                 aspect: float, cancellation=None) -> dict:
        health = self.probe()
        if not health["reachable"] or not health["checkpoint_ready"]:
            raise RuntimeError(health["reason"])
        parameters = derive_diffusion_parameters(
            source_digest, expression_vector, aspect)
        client_id = uuid.uuid4().hex
        prefix = f"jnsq_atelier/{str(source_digest)[:16]}"
        workflow = build_sdxl_workflow(
            checkpoint=self.config.checkpoint, prompt=prompt,
            negative_prompt=negative_prompt, parameters=parameters,
            filename_prefix=prefix)
        socket = self._websocket(client_id)
        prompt_id = None
        deadline = self._now() + self.config.execution_timeout
        try:
            queued = self._json_request(
                self._url("/prompt"),
                payload={"prompt": workflow, "client_id": client_id},
                timeout=10.0)
            prompt_id = str(dict(queued or {}).get("prompt_id") or "")
            if not prompt_id:
                raise RuntimeError("ComfyUI did not return a prompt id")
            while self._now() < deadline:
                if cancellation is not None:
                    cancellation.raise_if_cancelled()
                try:
                    message = socket.recv()
                except TimeoutError:
                    continue
                except Exception as exc:
                    if type(exc).__name__ in {"WebSocketTimeoutException", "TimeoutError"}:
                        continue
                    raise
                if not isinstance(message, str):
                    continue
                event = json.loads(message)
                kind = str(event.get("type") or "")
                data = dict(event.get("data") or {})
                if str(data.get("prompt_id") or "") != prompt_id:
                    continue
                if kind in {"execution_error", "execution_interrupted"}:
                    raise RuntimeError(f"ComfyUI {kind}")
                if kind == "execution_success" or (
                        kind == "executing" and data.get("node") is None):
                    break
            else:
                raise TimeoutError("ComfyUI execution did not reach a terminal event")
        finally:
            try:
                socket.close()
            except Exception:
                pass
        history = self._json_request(
            self._url(f"/history/{urllib.parse.quote(prompt_id, safe='')}"),
            timeout=10.0)
        entry = dict(dict(history or {}).get(prompt_id) or {})
        outputs = dict(entry.get("outputs") or {})
        images = []
        for node in outputs.values():
            images.extend(dict(node or {}).get("images") or [])
        if len(images) != 1:
            raise RuntimeError("ComfyUI did not produce exactly one image")
        image = dict(images[0] or {})
        descriptor = {
            "filename": str(image.get("filename") or ""),
            "subfolder": str(image.get("subfolder") or ""),
            "type": str(image.get("type") or "output"),
        }
        if not descriptor["filename"] or any(
                len(value) > 500 for value in descriptor.values()):
            raise RuntimeError("ComfyUI returned an invalid output descriptor")
        raw = self._bytes_request(
            self._url("/view", descriptor), timeout=30.0)
        return {
            "data": bytes(raw), "medium": "png", "prompt_id": prompt_id,
            "parameters": parameters, "workflow_nodes": len(workflow),
            "http_attempts": 4, "checkpoint": self.config.checkpoint,
            "renderer": "comfyui", "renderer_locality": "local",
        }
