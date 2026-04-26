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
    has_substantive_question: bool
    directive_result: DirectiveResult | None
    stripped_content: str
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


def _has_explicit_intent(text: str) -> bool:
    """Check whether text has explicit interrogative or commanding intent."""
    if "?" in text:
        return True
        
    words = re.findall(r'[a-z]+', text.lower())
    if not words:
        return False
        
    first_word = words[0]
    
    question_starters = {
        "what", "why", "how", "who", "when", "where", "which",
        "can", "could", "would", "will", "do", "does", "did",
        "is", "are", "was", "were"
    }
    if first_word in question_starters:
        return True
        
    action_verbs = {
        "please", "explain", "summarize", "summarise", "tell", "describe",
        "analyze", "analyse", "compare", "help", "read", "review",
        "give", "provide", "extract", "find", "look"
    }
    for word in words[:3]:
        if word in action_verbs:
            return True
            
    if first_word == "i" and len(words) > 1 and words[1] in {"need", "want", "would", "like"}:
        return True
        
    return False


def _has_substantive_text(text: str) -> bool:
    """Check whether text contains enough alphabetic content to be a question."""
    alpha_only = re.sub(r"[^a-zA-Z]", "", text)
    return len(alpha_only) >= _MIN_ALPHA_CHARS


def is_control_prompt(text: str) -> bool:
    """Check if the text is EXCLUSIVELY an OWUI control prompt."""
    if not text or not text.strip():
        return False
    
    # If the text contains a directive, it's NOT a control prompt (it's user intent)
    if "@@ingestion_tag_" in text:
        return False

    OWUI_MARKERS = [
        "### Task:",
        "### Guidelines:",
        "### Output:",
        "Analyze the chat history",
        "Strictly return in JSON format",
        "<chat_history>",
    ]
    # We excluded "Today's date is" from markers because it often prepends human text
    
    # If it starts with a marker and is relatively short, or contains multiple markers,
    # it's likely a control prompt.
    matches = [marker for marker in OWUI_MARKERS if marker in text]
    if len(matches) >= 2:
        return True
    
    if any(text.strip().startswith(marker) for marker in OWUI_MARKERS):
        # If it starts with a marker, it's a control prompt unless it's very long
        # (which might mean it's mixed). 
        # But usually control prompts are the whole message.
        return len(text.strip()) < 500
        
    return False


def _extract_all_user_texts(messages: list[dict[str, Any]]) -> list[str]:
    """Extract all user messages from the turn."""
    user_texts = []
    for msg in messages:
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list):
                parts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
                content_str = "\n".join(parts)
            else:
                content_str = str(content)
            
            if content_str.strip():
                user_texts.append(content_str)
    return user_texts


def classify(request_body: dict[str, Any], is_ingestion_active: bool = False) -> TurnClassification:
    """Classify a chat completion request into a routing decision.

    Parameters
    ----------
    request_body:
        The full OpenAI-compatible chat completion request JSON body.
    is_ingestion_active:
        Whether the ingestion tagging context is currently active for this chat.

    Returns
    -------
    TurnClassification
        Contains the routing decision and extracted metadata.
    """
    messages = request_body.get("messages", [])
    user_texts = _extract_all_user_texts(messages)
    
    # 1. Use the last user text for directive parsing
    user_content = user_texts[-1] if user_texts else ""

    # 2. Parse directives
    directive_result = parse_directive(user_content)
    has_directive = directive_result.action != "none"

    # Context will be active if it was already active, or if this turn starts it
    context_will_be_active = is_ingestion_active
    if directive_result.action == "tag_start":
        context_will_be_active = True
    elif directive_result.action == "tag_stop":
        context_will_be_active = False

    stripped = _strip_directives(user_content)
    
    # 3. Check if there is a real human question
    has_real_question = False
    if user_texts:
        # Check if the text is a control prompt
        if any(is_control_prompt(ut) for ut in user_texts):
            has_real_question = False
        else:
            stripped_clean = stripped.strip()
            is_non_question = False
            if not stripped_clean:
                is_non_question = True
            elif stripped_clean.startswith("{") and stripped_clean.endswith("}"):
                is_non_question = True
            elif stripped_clean.startswith("[") and stripped_clean.endswith("]"):
                is_non_question = True
            elif not _has_explicit_intent(stripped_clean):
                is_non_question = True
                
            if not is_non_question and _has_substantive_text(stripped):
                has_real_question = True

    has_user_role = any(msg.get("role") == "user" for msg in messages)

    # 4. Redefined upload-only classification
    if not has_user_role:
        is_upload_only = False
    elif not user_texts:
        # Purely synthetic or completely empty user turn must be intercepted
        is_upload_only = True
    else:
        # Has user text, but if it lacks a real question, it's upload-only IF context is active
        # BUT only if it's NOT a control prompt
        contains_control = any(is_control_prompt(ut) for ut in user_texts)
        if contains_control:
            is_upload_only = False
        else:
            is_upload_only = not has_real_question and context_will_be_active

    has_substantive_question = has_real_question

    # 4. Apply routing table
    route: Route
    if has_substantive_question:
        route = "forward"
    elif is_upload_only:
        if has_directive:
            route = "directive_plus_upload_ack"
        else:
            route = "upload_ack"
    elif has_directive:
        route = (
            "directive_stop_ack"
            if directive_result.action == "tag_stop"
            else "directive_ack"
        )
    else:
        # Empty text without tagging mode
        route = "forward"

    logger.debug(
        f"turn_classified route={route} has_directive={has_directive} "
        f"is_upload_only={is_upload_only} has_question={has_substantive_question}"
    )

    return TurnClassification(
        has_directive=has_directive,
        has_substantive_question=has_substantive_question,
        directive_result=directive_result,
        stripped_content=stripped,
        route=route,
    )
