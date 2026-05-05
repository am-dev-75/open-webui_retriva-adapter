import sys
import os
import asyncio
from unittest.mock import AsyncMock, MagicMock

# Add src to path
sys.path.append(os.path.join(os.getcwd(), "adapter/src"))

from adapter.turn_classifier import classify
from adapter.artifact_classifier import classify_artifact_request
from adapter.retriva_client import RetrivaClientV2

def test_assertion_1_classification():
    text = "Generate a PDF file listing all documents dealing with CRA"
    body = {"messages": [{"role": "user", "content": text}]}
    result = classify(body)
    assert result.route == "artifact_request", f"Expected artifact_request, got {result.route}"
    assert result.artifact_request.artifact_type == "document_list"
    assert result.artifact_request.format == "pdf"
    print("Assertion 1: Passed")

async def test_assertion_2_and_3_client_call_and_ack():
    # We test the orchestrator/main logic implicitly or just the client
    mock_settings = MagicMock()
    mock_settings.retriva_ingestion_url = "http://localhost:8000"
    mock_settings.RETRIVA_API_KEY = "test-key"
    mock_settings.RETRIVA_ARTIFACTS_API_BASE_URL = ""
    
    mock_http = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = 202
    mock_response.json.return_value = {"job_id": "job-123", "artifact_id": "art-456", "status": "accepted"}
    mock_http.post.return_value = mock_response
    
    client = RetrivaClientV2(mock_settings, mock_http)
    result = await client.generate_artifact("document_list", "pdf", {}, {})
    
    # Verify call
    mock_http.post.assert_called_once()
    args, kwargs = mock_http.post.call_args
    assert args[0] == "http://localhost:8000/api/v2/artifacts"
    assert kwargs["json"]["artifact_type"] == "document_list"
    assert kwargs["json"]["format"] == "pdf"
    
    assert result["job_id"] == "job-123"
    print("Assertion 2 & 3: Passed (Client part)")

def test_assertion_5_mappings():
    formats = [
        ("markdown", "markdown"),
        ("pdf", "pdf"),
        ("docx", "docx"),
        ("word", "docx"),
        ("xlsx", "xlsx"),
        ("excel", "xlsx"),
        ("odt", "odt"),
        ("ods", "ods"),
        ("odp", "odp"),
    ]
    for text, expected in formats:
        res = classify_artifact_request(f"create a {text} list")
        assert res.format == expected, f"Failed mapping for {text}: expected {expected}, got {res.format}"
    print("Assertion 5: Passed")

def test_assertion_6_owui_synthetic():
    body = {"messages": [{"role": "user", "content": "### Task: Generate a PDF report"}]}
    result = classify(body)
    assert result.route != "artifact_request", "OWUI markers should prevent artifact request classification"
    print("Assertion 6: Passed")

def test_assertion_7_8_9_regressions():
    # Already tested in standalone_regression_tests.py
    # non-artifact chat
    body = {"messages": [{"role": "user", "content": "Hello"}]}
    assert classify(body).route == "forward"
    
    # upload-only (synthetic turn)
    body = {"messages": [{"role": "user", "content": "### Task: Summarize"}]}
    assert classify(body, is_ingestion_active=True).route == "upload_ack"
    
    # directives
    body = {"messages": [{"role": "user", "content": "@@ingestion_tag_start"}]}
    assert classify(body).route == "directive_ack"
    
    print("Assertion 7, 8, 9: Passed")

if __name__ == "__main__":
    try:
        test_assertion_1_classification()
        asyncio.run(test_assertion_2_and_3_client_call_and_ack())
        test_assertion_5_mappings()
        test_assertion_6_owui_synthetic()
        test_assertion_7_8_9_regressions()
        print("\nAll final verification assertions passed!")
    except AssertionError as e:
        print(f"\nVerification failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nAn error occurred: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
