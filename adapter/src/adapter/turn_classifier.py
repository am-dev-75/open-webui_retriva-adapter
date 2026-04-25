# SPDX-License-Identifier: MIT
"""Turn classifier — routes user turns based on directives, files, and questions.

Implements the routing table from SDD 016 architecture:

1. directive only → ``directive_ack`` or ``directive_stop_ack``
2. upload only → ``upload_ack``
3. directive + upload, no question → ``directive_plus_upload_ack``
4. any with substantive question → ``forward``
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from adapter.directive_parser import DirectiveResult, parse_directive
from adapter.logger import get_logger

logger = get_logger(__name__)

Route = Literal[
    "directive_ack",
    "directive_stop_ack",
    "upload_ack",
    "directive_plus_upload_ack",
    "forward",
]


@dataclass(frozen=True, slots=True)
class TurnClassification:
    """Result of classifying a single user turn."""

    has_directive: bool
    has_files: bool
    has_substantive_question: bool
    directive_result: DirectiveResult | None
    stripped_content: str
    filenames: list[str] = field(default_factory=list)
    route: Route = "forward"


# Minimum number of alphabetic characters to consider text a "substantive question"
_MIN_ALPHA_CHARS = 5

# Regex to strip directive blocks from message text
_DIRECTIVE_BLOCK_RE = re.compile(
    r"(?m)^\s*@@ingestion_tag_(?:start|stop)\b[^\n]*(?:\n(?!\s*@@|\s*$)[^\n]*)*",
    re.IGNORECASE,
)


def _strip_directives(text: str) -> str:
    """Remove directive blocks from message text."""
    return _DIRECTIVE_BLOCK_RE.sub("", text).strip()


def _has_substantive_text(text: str) -> bool:
    """Check whether text contains enough alphabetic content to be a question."""
    alpha_only = re.sub(r"[^a-zA-Z]", "", text)
    return len(alpha_only) >= _MIN_ALPHA_CHARS


def _extract_last_user_content(messages: list[dict[str, Any]]) -> str:
    """Extract the content string from the last user-role message."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            # Handle multi-part content (OpenAI vision format)
            if isinstance(content, list):
                parts = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        parts.append(part.get("text", ""))
                return "\n".join(parts)
    return ""


def _extract_files(request_body: dict[str, Any]) -> list[str]:
    """Extract filenames from the request body's files array (OWUI extension)."""
    files = request_body.get("files", [])
    if not isinstance(files, list):
        return []
    filenames: list[str] = []
    for f in files:
        if isinstance(f, dict):
            name = f.get("filename") or f.get("name") or f.get("id", "unnamed")
            filenames.append(str(name))
        elif isinstance(f, str):
            filenames.append(f)
    return filenames


def classify(request_body: dict[str, Any]) -> TurnClassification:
    """Classify a chat completion request into a routing decision.

    Parameters
    ----------
    request_body:
        The full OpenAI-compatible chat completion request JSON body.

    Returns
    -------
    TurnClassification
        Contains the routing decision and extracted metadata.
    """
    messages = request_body.get("messages", [])
    user_content = _extract_last_user_content(messages)

    # 1. Parse directives
    directive_result = parse_directive(user_content)
    has_directive = directive_result.action != "none"

    # 2. Check for files
    filenames = _extract_files(request_body)
    has_files = len(filenames) > 0

    # 3. Check for substantive question
    stripped = _strip_directives(user_content)
    has_substantive_question = _has_substantive_text(stripped)

    # 4. Apply routing table
    route: Route
    if has_substantive_question:
        route = "forward"
    elif has_directive and not has_files:
        route = (
            "directive_stop_ack"
            if directive_result.action == "tag_stop"
            else "directive_ack"
        )
    elif has_files and not has_directive:
        route = "upload_ack"
    elif has_directive and has_files:
        route = "directive_plus_upload_ack"
    else:
        # No directive, no files, no question — forward to LLM
        # (e.g. empty message or trivial non-alphabetic input)
        route = "forward"

    logger.info(
        f"turn_classified route={route} has_directive={has_directive} "
        f"has_files={has_files} has_question={has_substantive_question}"
    )

    return TurnClassification(
        has_directive=has_directive,
        has_files=has_files,
        has_substantive_question=has_substantive_question,
        directive_result=directive_result,
        stripped_content=stripped,
        filenames=filenames,
        route=route,
    )
