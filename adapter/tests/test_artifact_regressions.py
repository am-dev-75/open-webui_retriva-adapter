import pytest
from adapter.turn_classifier import classify

def test_regression_non_artifact_chat():
    """Verify that a normal question is still routed to 'forward'."""
    body = {
        "messages": [
            {"role": "user", "content": "What is the capital of France?"}
        ]
    }
    result = classify(body)
    assert result.route == "forward"
    assert result.artifact_request is None

def test_regression_upload_only():
    """Verify that an upload-only turn is still routed correctly."""
    # Simulation of OWUI upload turn: empty user text + OWUI markers
    body = {
        "messages": [
            {
                "role": "user", 
                "content": "Today's date is: 2026-05-05\n### Task: Summarize\n<chat_history>\n"
            }
        ]
    }
    # Upload only route depends on is_upload_only logic which checks markers and content
    result = classify(body, is_ingestion_active=True)
    assert result.route == "upload_ack"
    assert result.artifact_request is None

def test_regression_directives():
    """Verify that ingestion directives are still routed correctly."""
    body = {
        "messages": [
            {"role": "user", "content": "@@ingestion_tag_start\nproject: Apollo"}
        ]
    }
    result = classify(body)
    assert result.route == "directive_ack"
    assert result.has_directive is True
    assert result.artifact_request is None

def test_regression_owui_synthetic_prompts():
    """Verify that OWUI synthetic prompts do not trigger artifact requests."""
    body = {
        "messages": [
            {"role": "user", "content": "### Task: Generate a list of documents\nStrictly return JSON"}
        ]
    }
    # This contains artifact-like words but should be ignored because it has OWUI markers
    result = classify(body)
    assert result.route == "forward"
    assert result.artifact_request is None

def test_regression_combined_artifact_and_question():
    """Verify that a question with artifact-y words is forwarded if it's not a pure request."""
    body = {
        "messages": [
            {"role": "user", "content": "Can you explain how to create a PDF?"}
        ]
    }
    # "create" and "pdf" are present, but it's a "how to" question
    result = classify(body)
    assert result.route == "forward"
    assert result.artifact_request is None
