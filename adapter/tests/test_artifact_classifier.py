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

import pytest
from adapter.artifact_classifier import classify_artifact_request

@pytest.mark.parametrize("text, expected_type, expected_format", [
    ("create a pdf list of documents", "document_list", "pdf"),
    ("generate a markdown report", "basic_report", "markdown"),
    ("export docx list", "document_list", "docx"),
    ("make an excel spreadsheet", "document_list", "xlsx"),
    ("give me a list of my files in pdf", "document_list", "pdf"),
    ("generate report", "basic_report", "pdf"),  # default format
    ("export to odt", "document_list", "odt"),
])
def test_artifact_detection_positive(text, expected_type, expected_format):
    result = classify_artifact_request(text)
    assert result is not None
    assert result.artifact_type == expected_type
    assert result.format == expected_format

@pytest.mark.parametrize("text", [
    "what is a pdf?",
    "how do I create a project?",
    "tell me a story",
    "list my files",  # Too ambiguous without creation verb or format?
    "summarize this document",
])
def test_artifact_detection_negative(text):
    result = classify_artifact_request(text)
    assert result is None
