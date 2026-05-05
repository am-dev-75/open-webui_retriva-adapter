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
    "create", "generate", "export", "make", "produce", "list", "report", "download"
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
    "list": "document_list",
    "document list": "document_list",
    "report": "basic_report",
    "basic report": "basic_report",
}


def classify_artifact_request(text: str, default_format: str = "pdf") -> ArtifactRequest | None:
    """Check if the text contains an explicit artifact generation request.
    
    Returns ArtifactRequest if detected, else None.
    """
    if not text:
        return None

    clean_text = text.lower().strip()
    
    # Avoid questions unless they have explicit creation intent
    is_question = "?" in text or clean_text.startswith(("what", "how", "why", "who", "when", "where", "can", "could"))

    # 1. Check for creation intent (verb)
    words = re.findall(r'[a-z0-9]+', clean_text)
    if not words:
        return None
        
    has_verb = any(verb in words[:5] for verb in _CREATION_VERBS)
    
    if is_question and not has_verb:
        return None

    if not has_verb:
        # Check for direct format mentions like "pdf of my docs"
        if not any(fmt in words for fmt in _FORMAT_MAP):
            return None

    # 2. Extract format
    detected_format = default_format
    for word in words:
        if word in _FORMAT_MAP:
            detected_format = _FORMAT_MAP[word]
            break

    # 3. Extract type
    detected_type = "document_list"  # Default type
    for phrase, artifact_type in _TYPE_MAP.items():
        if phrase in clean_text:
            detected_type = artifact_type
            break
            
    # Special case: "list of documents" -> document_list
    if "list" in words and "document" in words:
        detected_type = "document_list"
    elif "report" in words:
        detected_type = "basic_report"

    # 4. Final validation: must have some "artifact-y" keywords to avoid false positives
    artifact_keywords = {
        "pdf", "markdown", "report", "list", "document", "file", "export",
        "excel", "spreadsheet", "word", "docx", "xlsx", "csv"
    }
    if not any(kw in words for kw in artifact_keywords):
        return None

    logger.info(f"artifact_request_detected type={detected_type} format={detected_format}")
    
    return ArtifactRequest(
        artifact_type=detected_type,
        format=detected_format,
        parameters={},
    )
