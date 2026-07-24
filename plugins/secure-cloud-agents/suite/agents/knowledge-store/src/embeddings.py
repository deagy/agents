"""Deterministic local and OpenAI-compatible embedding providers."""

from __future__ import annotations

import hashlib
import json
import math
import os
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request: Any, file_pointer: Any, code: int, message: str, headers: Any, new_url: str) -> None:
        return None


def _open_request(request: urllib.request.Request, timeout: float) -> Any:
    return urllib.request.build_opener(_RejectRedirects()).open(request, timeout=timeout)


def _normalize(vector: list[float]) -> list[float]:
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) for value in vector):
        raise ValueError("Embedding vector must contain only finite numbers")
    magnitude = math.sqrt(sum(float(value) * float(value) for value in vector))
    return [float(value) / magnitude for value in vector] if magnitude else [float(value) for value in vector]


def _tokens(text: str) -> list[str]:
    words: list[str] = []
    current: list[str] = []
    for character in text.lower():
        category = unicodedata.category(character)
        if character in {"_", "-"} or category.startswith(("L", "N")):
            current.append(character)
        elif current:
            words.append("".join(current))
            current = []
    if current:
        words.append("".join(current))
    return words


def hashing_embedding(text: str, dimensions: int) -> list[float]:
    words = _tokens(text)
    features = list(words) + [f"{words[index]}::{words[index + 1]}" for index in range(len(words) - 1)]
    vector = [0.0] * dimensions
    for feature in features:
        digest = hashlib.sha256(feature.encode("utf-8")).digest()
        position = int.from_bytes(digest[0:4], "little") % dimensions
        sign = 1.0 if int.from_bytes(digest[4:8], "little") % 2 == 0 else -1.0
        vector[position] += sign
    return _normalize(vector)


def _remote_embeddings(texts: list[str], config: dict[str, Any]) -> list[list[float]]:
    base_url = config.get("base_url")
    if not isinstance(base_url, str) or not base_url or "example.invalid" in base_url:
        raise ValueError("Set embedding.base_url for the openai-compatible provider")
    parsed_url = urllib.parse.urlparse(base_url)
    if parsed_url.scheme != "https" or not parsed_url.netloc or parsed_url.username or parsed_url.password:
        raise ValueError("embedding.base_url must be an HTTPS URL without embedded credentials")
    key_name = config.get("api_key_env")
    if not isinstance(key_name, str) or not key_name:
        raise ValueError("embedding.api_key_env must be a non-empty string")
    key = os.environ.get(key_name)
    if not key:
        raise ValueError(f"Missing embedding credential in {key_name}")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/embeddings",
        data=json.dumps({"model": config["model"], "input": texts}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    try:
        with _open_request(request, timeout=float(config.get("timeout_seconds", 30))) as response:
            if response.status < 200 or response.status >= 300:
                raise RuntimeError(f"Embedding endpoint returned HTTP {response.status}")
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Embedding endpoint returned HTTP {error.code}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Embedding endpoint request failed: {error.reason}") from error
    except (TimeoutError, OSError) as error:
        raise RuntimeError("Embedding endpoint request timed out or failed") from error
    except json.JSONDecodeError as error:
        raise RuntimeError("Embedding endpoint returned invalid JSON") from error

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise RuntimeError("Embedding endpoint returned an invalid response")
    try:
        if any(
            not isinstance(item, dict)
            or isinstance(item.get("index"), bool)
            or not isinstance(item.get("index"), int)
            for item in data
        ):
            raise TypeError
        ordered = sorted(data, key=lambda item: item["index"])
        if [item["index"] for item in ordered] != list(range(len(texts))):
            raise ValueError
        vectors = [item["embedding"] for item in ordered]
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("Embedding endpoint returned an invalid response") from error
    if len(vectors) != len(texts) or any(not isinstance(vector, list) for vector in vectors):
        raise RuntimeError("Embedding endpoint returned an invalid response")
    dimensions = config["dimensions"]
    if any(len(vector) != dimensions for vector in vectors):
        raise RuntimeError(f"Embedding endpoint vectors must have exactly {dimensions} dimensions")
    try:
        return [_normalize(vector) for vector in vectors]
    except (TypeError, ValueError) as error:
        raise RuntimeError("Embedding endpoint returned invalid vector values") from error


def embed_texts(texts: list[str], config: dict[str, Any]) -> list[list[float]]:
    if config["provider"] == "hashing":
        return [hashing_embedding(text, config["dimensions"]) for text in texts]
    vectors: list[list[float]] = []
    batch_size = config["batch_size"]
    for start in range(0, len(texts), batch_size):
        vectors.extend(_remote_embeddings(texts[start:start + batch_size], config))
    return vectors


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return float("-inf")
    if not all(math.isfinite(value) for value in right):
        return float("-inf")
    return sum(left[index] * right[index] for index in range(len(left)))
