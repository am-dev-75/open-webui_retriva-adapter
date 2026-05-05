import sys
import os

# Add src to path
sys.path.append(os.path.join(os.getcwd(), "adapter/src"))

from adapter.turn_classifier import classify

def test_regression_non_artifact_chat():
    body = {"messages": [{"role": "user", "content": "What is the capital of France?"}]}
    result = classify(body)
    assert result.route == "forward"
    assert result.artifact_request is None
    print("test_regression_non_artifact_chat passed")

def test_regression_upload_only():
    body = {"messages": [{"role": "user", "content": "Today's date is: 2026-05-05\n### Task: Summarize\n<chat_history>\n"}]}
    result = classify(body, is_ingestion_active=True)
    assert result.route == "upload_ack"
    assert result.artifact_request is None
    print("test_regression_upload_only passed")

def test_regression_directives():
    body = {"messages": [{"role": "user", "content": "@@ingestion_tag_start\nproject: Apollo"}]}
    result = classify(body)
    assert result.route == "directive_ack"
    assert result.has_directive is True
    assert result.artifact_request is None
    print("test_regression_directives passed")

def test_regression_owui_synthetic_prompts():
    body = {"messages": [{"role": "user", "content": "### Task: Generate a list of documents\nStrictly return JSON"}]}
    result = classify(body)
    # It is classified as upload_ack because it's non-human text with markers and no USER text.
    assert result.route == "upload_ack"
    assert result.artifact_request is None
    print("test_regression_owui_synthetic_prompts passed")

def test_regression_combined_artifact_and_question():
    body = {"messages": [{"role": "user", "content": "Can you explain how to create a PDF?"}]}
    result = classify(body)
    assert result.route == "forward"
    assert result.artifact_request is None
    print("test_regression_combined_artifact_and_question passed")

if __name__ == "__main__":
    import traceback
    try:
        test_regression_non_artifact_chat()
        test_regression_upload_only()
        test_regression_directives()
        test_regression_owui_synthetic_prompts()
        test_regression_combined_artifact_and_question()
        print("All regression tests passed!")
    except AssertionError:
        print("Regression test failed!")
        traceback.print_exc()
        sys.exit(1)
    except Exception:
        print("An unexpected error occurred!")
        traceback.print_exc()
        sys.exit(1)
