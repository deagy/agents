"""Normalize common chat export shapes into canonical messages."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROLES = {"system", "user", "assistant", "tool"}


def _digest(value: Any) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _text_of(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(filter(None, (_text_of(item) for item in value))).strip()
    if not isinstance(value, dict):
        return ""
    if isinstance(value.get("parts"), list):
        return _text_of(value["parts"])
    for key in ("text", "content", "value"):
        if key in value:
            return _text_of(value[key])
    return ""


def _date_of(value: Any) -> str | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            seconds = value if value < 1e12 else value / 1000
            parsed = datetime.fromtimestamp(seconds, tz=timezone.utc)
        else:
            candidate = str(value)
            parsed = datetime.fromisoformat(candidate[:-1] + "+00:00" if candidate.endswith("Z") else candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def _role_of(message: dict[str, Any]) -> str:
    author = message.get("author")
    raw = message.get("role", message.get("sender"))
    if raw is None and isinstance(author, dict):
        raw = author.get("role", author.get("name"))
    normalized = str(raw if raw is not None else "unknown").lower()
    if normalized in ROLES:
        return normalized
    if normalized in {"human", "customer"}:
        return "user"
    if normalized in {"ai", "bot", "model"}:
        return "assistant"
    return "unknown"


def _messages_of(conversation: Any) -> list[dict[str, Any]]:
    if not isinstance(conversation, dict):
        return []
    for key in ("messages", "chat", "conversation"):
        if isinstance(conversation.get(key), list):
            return conversation[key]
    mapping = conversation.get("mapping")
    if isinstance(mapping, dict):
        messages = [node.get("message") for node in mapping.values() if isinstance(node, dict) and node.get("message")]
        def timestamp(item: dict[str, Any]) -> float:
            try:
                value = float(item.get("create_time") or 0)
                return value if math.isfinite(value) else 0.0
            except (TypeError, ValueError):
                return 0.0
        return sorted(messages, key=timestamp)
    return []


def _is_message(value: Any) -> bool:
    return isinstance(value, dict) and any(key in value for key in ("content", "text", "message"))


def _canonical_message(message: dict[str, Any], context: dict[str, Any], index: int) -> dict[str, Any] | None:
    content = _text_of(message.get("content", message.get("text", message.get("message"))))
    if not content:
        return None
    message_id = message.get("message_id", message.get("id", message.get("uuid")))
    if message_id is None:
        message_id = _digest(f"{context['source']}|{context['conversation_id']}|{index}|{content}")[:24]
    timestamp = next((message[key] for key in ("created_at", "timestamp", "create_time", "date") if key in message), None)
    return {
        "source": context["source"],
        "source_uri": context["source_uri"],
        "conversation_id": context["conversation_id"],
        "conversation_title": context["title"],
        "message_id": str(message_id),
        "role": _role_of(message),
        "content": content,
        "created_at": _date_of(timestamp),
        "classification": context["classification"],
        "metadata": {"source_format": context["source_format"]},
    }


def _parse_input(raw: str) -> tuple[Any, str]:
    try:
        return json.loads(raw), "json"
    except json.JSONDecodeError:
        values = []
        for index, line in enumerate(line for line in raw.splitlines() if line.strip()):
            try:
                values.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid JSON on JSONL line {index + 1}") from error
        return values, "jsonl"


def normalize_file(input_path: str, *, source: str, classification: str) -> list[dict[str, Any]]:
    absolute = Path(input_path).resolve()
    raw = absolute.read_text(encoding="utf-8")
    value, source_format = _parse_input(raw)
    root = value.get("conversations", value.get("chats", value)) if isinstance(value, dict) else value
    items = root if isinstance(root, list) else [root]
    results: list[dict[str, Any]] = []

    if items and all(_is_message(item) for item in items) and not any(_messages_of(item) for item in items):
        conversation_id = _digest(f"{source}|{absolute}")[:24]
        for index, message in enumerate(items):
            canonical = _canonical_message(message, {
                "source": source, "source_uri": str(absolute), "conversation_id": conversation_id,
                "title": None, "classification": classification, "source_format": source_format,
            }, index)
            if canonical:
                results.append(canonical)
    else:
        for conversation_index, conversation in enumerate(items):
            if not isinstance(conversation, dict):
                continue
            title = conversation.get("title", conversation.get("name"))
            conversation_id = conversation.get("conversation_id", conversation.get("id", conversation.get("uuid")))
            if conversation_id is None:
                conversation_id = _digest(f"{source}|{absolute}|{conversation_index}|{title or ''}")[:24]
            for message_index, message in enumerate(_messages_of(conversation)):
                canonical = _canonical_message(message, {
                    "source": source, "source_uri": str(absolute), "conversation_id": str(conversation_id),
                    "title": title, "classification": classification,
                    "source_format": "mapping-json" if conversation.get("mapping") else source_format,
                }, message_index)
                if canonical:
                    results.append(canonical)
    if not results:
        raise ValueError("No non-empty chat messages were recognized in the input")
    return results
