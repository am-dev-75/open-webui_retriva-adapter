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

"""Artifact classifier — detects explicit document generation requests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from adapter.logger import get_logger

logger = get_logger(__name__)

@dataclass(frozen=True, slots=True)
class ArtifactRequest:
    """Extracted details of an artifact generation request."""

    artifact_type: str
    format: str
    parameters: dict[str, Any]


_CREATION_VERBS = {
    "create", "generate", "export", "make", "produce", "download"
}

_FORMAT_MAP = {
    "pdf": "pdf",
    "markdown": "markdown",
    "md": "markdown",
    "docx": "docx",
    "word": "docx",
    "xlsx": "xlsx",
    "excel": "xlsx",
    "spreadsheet": "xlsx",
    "odt": "odt",
    "ods": "ods",
    "odp": "odp",
}

_TYPE_MAP = {
    "document list": "document_list",
    "basic report": "basic_report",
}


def classify_artifact_request(text: str, default_format: str = "pdf") -> ArtifactRequest | None:
    """Check if the text contains an explicit artifact generation request.
    
    Returns ArtifactRequest if detected, else None.
    """
    if not text:
        return None

    clean_text = text.lower().strip()
    
    # 1. Check for creation intent (verb)
    words = re.findall(r'[a-z0-9]+', clean_text)
    if not words:
        return None
        
    # Creation verbs are strong signals
    has_creation_verb = any(verb in words[:5] for verb in _CREATION_VERBS)
    
    # Formats are also strong signals
    mentioned_format = next((word for word in words if word in _FORMAT_MAP), None)
    
    # Requirement: Must have either a creation verb OR a file format mention
    if not has_creation_verb and not mentioned_format:
        return None

    # Avoid questions unless they have strong creation intent
    # "What is a PDF?" -> False
    # "Can you make a PDF?" -> True
    # "Give me a PDF" -> True
    is_question = "?" in text or clean_text.startswith(("what", "how", "why", "who", "when", "where", "can", "could"))
    if is_question and not has_creation_verb:
        # Check for other action words if it's a question mentioning a format
        action_words = {"give", "send", "provide", "make", "get", "save", "show", "list"}
        if not any(word in words for word in action_words):
            return None

    # 2. Extract format
    detected_format = _FORMAT_MAP.get(mentioned_format) if mentioned_format else default_format

    # 3. Extract type
    detected_type = "document_list"  # Default type
    for phrase, artifact_type in _TYPE_MAP.items():
        if phrase in clean_text:
            detected_type = artifact_type
            break
            
    # Heuristics for type
    if "report" in words:
        detected_type = "basic_report"
    elif "list" in words:
        detected_type = "document_list"

    # 4. Extract query (crude but effective)
    # We take the whole text and strip common leading/trailing patterns
    query = text
    # Strip common leading patterns
    query = re.sub(r'(?i)^(generate|create|make|export|download|list|show)\s+(a|an)?\s+(\w+\s+)?(file|artifact|report|list)?\s+(of|about|dealing with|listing|regarding)?\s+', '', query)
    # Strip common trailing patterns
    query = re.sub(r'(?i)\s+in\s+\w+\s+format$', '', query)
    query = re.sub(r'(?i)\s+as\s+(a|an)?\s+\w+$', '', query)
    query = query.strip()

    # Final validation: must have some "artifact-y" keywords to avoid false positives
    artifact_keywords = {
        "pdf", "markdown", "report", "document", "file", "export",
        "excel", "spreadsheet", "word", "docx", "xlsx", "csv", "odt", "ods", "odp"
    }
    if not any(kw in words for kw in artifact_keywords):
        return None

    logger.info(f"artifact_request_detected type={detected_type} format={detected_format} query='{query}'")
    
    return ArtifactRequest(
        artifact_type=detected_type,
        format=detected_format,
        parameters={"query": query},
    )
