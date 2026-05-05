# Copyright (C) 2026 Andrea Marson (am.dev.75@gmail.com)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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


def _build_content(classification: TurnClassification, artifact_result: dict[str, Any] | None = None) -> str:
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
        return "✅ Document received and queued for ingestion."

    if route == "directive_plus_upload_ack":
        meta_block = ""
        if directive and directive.metadata:
            meta_block = f"\n\n**Active metadata:**\n{_format_metadata(directive.metadata)}"
        return f"✅ Document received and queued for ingestion.{meta_block}"

    if route == "artifact_request":
        req = classification.artifact_request
        if req:
            msg = f"🛠️ **Artifact generation started**\n- **Type**: {req.artifact_type}\n- **Format**: {req.format}"
            if artifact_result:
                job_id = artifact_result.get("job_id")
                artifact_id = artifact_result.get("artifact_id")
                status = artifact_result.get("status", "accepted")
                
                if job_id:
                    msg += f"\n- **Job ID**: `{job_id}`"
                if artifact_id:
                    msg += f"\n- **Artifact ID**: `{artifact_id}`"
                if status:
                    msg += f"\n- **Status**: {status}"
                
                # Construct download URL (simulated/inferred from Core API)
                if artifact_id:
                    # In a real scenario, this URL should be reachable from the user's browser
                    # or redirected by the adapter.
                    msg += f"\n- **Download**: [Link](/api/v2/artifacts/{artifact_id})"

            msg += "\n\nYou will be notified when the file is ready for download."
            return msg
        return "🛠️ Artifact generation started."

    # Should not be called for "forward" route, but handle gracefully
    return ""


def build_response(classification: TurnClassification, artifact_result: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a complete OpenAI-compatible chat.completion response.

    Parameters
    ----------
    classification:
        The turn classification result (must have a non-``forward`` route).
    artifact_result:
        Optional result from the artifact generation API.

    Returns
    -------
    dict
        A JSON-serialisable dict matching the OpenAI chat.completion shape.
    """
    content = _build_content(classification, artifact_result)
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