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
