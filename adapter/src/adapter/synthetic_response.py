# SPDX-License-Identifier: MIT
"""Synthetic response generator — builds OpenAI-compatible acknowledgements.

Generates local ``chat.completion`` response payloads for intercepted turns
(directive-only, upload-only, or combined) so the user receives immediate
feedback without a round-trip to the chat LLM.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from adapter.turn_classifier import Route, TurnClassification
from adapter.logger import get_logger

logger = get_logger(__name__)


def _format_metadata(metadata: dict[str, str]) -> str:
    """Format metadata as a bulleted list."""
    if not metadata:
        return ""
    lines = [f"- **{k}**: {v}" for k, v in metadata.items()]
    return "\n".join(lines)


def _format_filenames(filenames: list[str]) -> str:
    """Format filenames as a bulleted list."""
    if not filenames:
        return ""
    lines = [f"- {name}" for name in filenames]
    return "\n".join(lines)


def _build_content(classification: TurnClassification) -> str:
    """Build the human-readable acknowledgement text for the given route."""
    route = classification.route
    directive = classification.directive_result

    if route == "directive_ack":
        meta_block = ""
        if directive and directive.metadata:
            meta_block = f"\n\n**Active metadata:**\n{_format_metadata(directive.metadata)}"
        return f"✅ Ingestion tagging activated.{meta_block}"

    if route == "directive_stop_ack":
        return "🛑 Ingestion tagging deactivated."

    if route == "upload_ack":
        file_block = ""
        if classification.filenames:
            file_block = f"\n{_format_filenames(classification.filenames)}"
        return f"📄 File(s) received for ingestion:{file_block}\n\nProcessing will begin shortly."

    if route == "directive_plus_upload_ack":
        meta_block = ""
        if directive and directive.metadata:
            meta_block = f"\n\n**Active metadata:**\n{_format_metadata(directive.metadata)}"
        file_block = ""
        if classification.filenames:
            file_block = f"\n{_format_filenames(classification.filenames)}"
        return (
            f"✅ Ingestion tagging activated.{meta_block}\n\n"
            f"📄 File(s) received for ingestion:{file_block}\n\n"
            f"Processing will begin shortly."
        )

    # Should not be called for "forward" route, but handle gracefully
    return ""


def build_response(classification: TurnClassification) -> dict[str, Any]:
    """Build a complete OpenAI-compatible chat.completion response.

    Parameters
    ----------
    classification:
        The turn classification result (must have a non-``forward`` route).

    Returns
    -------
    dict
        A JSON-serialisable dict matching the OpenAI chat.completion shape.
    """
    content = _build_content(classification)
    response_id = f"chatcmpl-adapter-{uuid.uuid4().hex[:12]}"
    created = int(time.time())

    response: dict[str, Any] = {
        "id": response_id,
        "object": "chat.completion",
        "created": created,
        "model": "retriva-adapter",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": "stop",
            },
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }

    logger.info(f"synthetic_response_built route={classification.route} id={response_id}")
    return response
