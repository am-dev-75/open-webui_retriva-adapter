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

"""Directive parser — extracts ingestion tag commands from chat messages.

Recognised directives:

    @@ingestion_tag_start
    project: Apollo
    milestone: M4

    @@ingestion_tag_stop

The parser is a **pure function** — it carries no state.  Replacement and
state-machine semantics are handled by :class:`~adapter.ingestion_context.IngestionContext`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from adapter.logger import get_logger

logger = get_logger(__name__)

@dataclass(frozen=True, slots=True)
class DirectiveResult:
    """Result of parsing a single chat message for directives."""

    action: Literal["tag_start", "tag_stop", "none"]
    metadata: dict[str, str] = field(default_factory=dict)


_TAG_START = "@@ingestion_tag_start"
_TAG_STOP = "@@ingestion_tag_stop"


def parse_directive(message: str) -> DirectiveResult:
    """Parse a chat message and return a :class:`DirectiveResult`.

    Rules
    -----
    * ``@@ingestion_tag_start`` must appear at the **start of a line**
      (leading whitespace is tolerated).
    * Subsequent lines are treated as ``key: value`` metadata pairs until
      a blank line or the end of the message.
    * ``@@ingestion_tag_stop`` must appear at the start of a line.
    * If both directives appear in the same message, only the **last**
      directive wins (edge-case guard — callers should avoid this).
    * If neither directive is found the action is ``"none"``.
    """
    if not message or not message.strip():
        return DirectiveResult(action="none")

    lines = message.splitlines()

    # Scan for the last directive in the message
    last_directive_idx: int | None = None
    last_directive_type: str | None = None

    for idx, raw_line in enumerate(lines):
        stripped = raw_line.strip().lower()
        if stripped == _TAG_STOP:
            logger.debug(f"Found @@ingestion_tag_stop at line {idx}")
            last_directive_idx = idx
            last_directive_type = "tag_stop"
        elif stripped == _TAG_START:
            logger.debug(f"Found @@ingestion_tag_start at line {idx}")
            last_directive_idx = idx
            last_directive_type = "tag_start"

    if last_directive_idx is None or last_directive_type is None:
        return DirectiveResult(action="none")

    if last_directive_type == "tag_stop":
        return DirectiveResult(action="tag_stop")

    # --- tag_start: collect key:value pairs from lines after the directive ---
    metadata: dict[str, str] = {}
    for line in lines[last_directive_idx + 1 :]:
        stripped = line.strip()
        if not stripped:
            break  # blank line terminates metadata block

        colon_pos = stripped.find(":")
        if colon_pos <= 0:
            # Not a valid key:value — skip (tolerant parsing)
            continue

        key = stripped[:colon_pos].strip()
        value = stripped[colon_pos + 1 :].strip()
        if key:
            metadata[key] = value
    
    if metadata != {}:
        logger.debug(f"Found @@ingestion_tag_start with metadata: {metadata}")   
    else:
        logger.info("Found @@ingestion_tag_start without metadata")

    return DirectiveResult(action="tag_start", metadata=metadata)