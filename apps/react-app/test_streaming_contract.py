"""Smoke-test the AiChemy streaming contract.

Usage:
    STREAM_TEST_BASE_URL=http://localhost:8000 python test_streaming_contract.py
    STREAM_TEST_BASE_URL=https://...aws.databricksapps.com \
      STREAM_TEST_BEARER_TOKEN=$(databricks auth token ... | jq -r .access_token) \
      python test_streaming_contract.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import requests


BASE_URL = os.getenv("STREAM_TEST_BASE_URL", "http://localhost:8000").rstrip("/")
BEARER_TOKEN = os.getenv("STREAM_TEST_BEARER_TOKEN")


@dataclass
class StreamResult:
    text_chunks: list[str] = field(default_factory=list)
    tool_events: int = 0
    errors: list[str] = field(default_factory=list)
    raw_events: list[dict[str, Any] | str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "".join(self.text_chunks)


def _message_item_text(item: dict[str, Any]) -> str:
    parts = []
    for part in item.get("content", []):
        if isinstance(part, str):
            parts.append(part)
        elif isinstance(part, dict):
            text = part.get("text") or part.get("content")
            if text:
                parts.append(text)
    return "\n".join(parts)


def stream_prompt(prompt: str) -> StreamResult:
    headers = {"Content-Type": "application/json"}
    if BEARER_TOKEN:
        headers["Authorization"] = f"Bearer {BEARER_TOKEN}"

    payload = {
        "input": [{"role": "user", "content": prompt}],
        "custom_inputs": {
            "thread_id": f"stream-test-{int(time.time())}",
            "user_id": "stream-test-user",
        },
    }

    result = StreamResult()
    streamed_item_ids = set()
    emitted_final_texts = set()

    with requests.post(
        f"{BASE_URL}/api/agent/stream",
        headers=headers,
        json=payload,
        stream=True,
        timeout=(30, 300),
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            data = line.removeprefix("data: ")
            if data == "[DONE]":
                break
            event = json.loads(data)
            result.raw_events.append(event)
            event_type = event.get("type")

            if event_type in {"text", "response.output_text.delta"}:
                text = event.get("content") or event.get("delta") or ""
                if text:
                    if event.get("item_id"):
                        streamed_item_ids.add(event["item_id"])
                    result.text_chunks.append(text)
            elif event_type == "response.content_part.done":
                text = event.get("part", {}).get("text", "")
                item_id = event.get("item_id")
                if text and item_id and item_id not in streamed_item_ids:
                    streamed_item_ids.add(item_id)
                    result.text_chunks.append(text)
            elif event_type in {"tool_call_start", "tool_call_done", "tool_call_result"}:
                result.tool_events += 1
            elif event_type in {"response.output_item.added", "response.output_item.done"}:
                item = event.get("item") or {}
                if item.get("type") == "function_call":
                    result.tool_events += 1
                elif item.get("type") == "function_call_output":
                    result.tool_events += 1
                elif (
                    event_type == "response.output_item.done"
                    and item.get("type") == "message"
                    and item.get("id") not in streamed_item_ids
                ):
                    text = _message_item_text(item)
                    if text and text not in emitted_final_texts:
                        emitted_final_texts.add(text)
                        result.text_chunks.append(text)
            elif event_type == "error":
                error = event.get("content") or event.get("error", {}).get("message") or str(event)
                result.errors.append(error)

    return result


def assert_non_empty_once(prompt: str, forbidden_echo: str | None = None) -> None:
    result = stream_prompt(prompt)
    if result.errors:
        raise AssertionError(f"{prompt!r} returned errors: {result.errors}")
    if not result.text.strip():
        raise AssertionError(f"{prompt!r} produced no assistant text. Raw events: {result.raw_events[:5]}")
    if forbidden_echo and result.text.strip() == forbidden_echo.strip():
        raise AssertionError(f"{prompt!r} was echoed as assistant text")


def main() -> int:
    assert_non_empty_once("hello", forbidden_echo="hello")
    assert_non_empty_once("What diseases are associated with EGFR?")
    print("Streaming contract checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
