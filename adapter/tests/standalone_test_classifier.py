import sys
import os

# Add src to path
sys.path.append(os.path.join(os.getcwd(), "adapter/src"))

from adapter.artifact_classifier import classify_artifact_request

def test_positive():
    cases = [
        ("create a pdf list of documents", "document_list", "pdf"),
        ("generate a markdown report", "basic_report", "markdown"),
        ("export docx list", "document_list", "docx"),
        ("make an excel spreadsheet", "document_list", "xlsx"),
        ("give me a list of my files in pdf", "document_list", "pdf"),
        ("generate report", "basic_report", "pdf"),
        ("export to odt", "document_list", "odt"),
    ]
    for text, expected_type, expected_format in cases:
        result = classify_artifact_request(text)
        assert result is not None, f"Failed for: {text}"
        assert result.artifact_type == expected_type, f"Type mismatch for {text}: {result.artifact_type} != {expected_type}"
        assert result.format == expected_format, f"Format mismatch for {text}: {result.format} != {expected_format}"
    print("Positive cases passed!")

def test_negative():
    cases = [
        "what is a pdf?",
        "how do I create a project?",
        "tell me a story",
        "summarize this document",
    ]
    for text in cases:
        result = classify_artifact_request(text)
        assert result is None, f"Should have been None for: {text}"
    print("Negative cases passed!")

if __name__ == "__main__":
    try:
        test_positive()
        test_negative()
        print("All classifier tests passed!")
    except AssertionError as e:
        print(f"Test failed: {e}")
        sys.exit(1)
