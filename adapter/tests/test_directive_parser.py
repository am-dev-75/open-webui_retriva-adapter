# SPDX-License-Identifier: MIT
"""Tests for adapter.directive_parser — directive extraction from chat messages."""

from __future__ import annotations

from adapter.directive_parser import DirectiveResult, parse_directive


class TestParseTagStart:
    """Tests for @@ingestion_tag_start parsing."""

    def test_tag_start_with_single_kv(self) -> None:
        msg = "@@ingestion_tag_start\nproject: Apollo"
        result = parse_directive(msg)
        assert result.action == "tag_start"
        assert result.metadata == {"project": "Apollo"}

    def test_tag_start_with_multiple_kv(self) -> None:
        msg = "@@ingestion_tag_start\nproject: Apollo\nmilestone: M4\nteam: engineering"
        result = parse_directive(msg)
        assert result.action == "tag_start"
        assert result.metadata == {
            "project": "Apollo",
            "milestone": "M4",
            "team": "engineering",
        }

    def test_tag_start_no_metadata(self) -> None:
        """tag_start with no key:value lines → active with empty metadata."""
        msg = "@@ingestion_tag_start"
        result = parse_directive(msg)
        assert result.action == "tag_start"
        assert result.metadata == {}

    def test_tag_start_blank_line_terminates_metadata(self) -> None:
        msg = "@@ingestion_tag_start\nproject: Apollo\n\nthis is not metadata"
        result = parse_directive(msg)
        assert result.action == "tag_start"
        assert result.metadata == {"project": "Apollo"}

    def test_tag_start_leading_whitespace(self) -> None:
        """Leading whitespace before the directive is tolerated."""
        msg = "  @@ingestion_tag_start\nproject: Apollo"
        result = parse_directive(msg)
        assert result.action == "tag_start"
        assert result.metadata == {"project": "Apollo"}


class TestParseTagStop:
    """Tests for @@ingestion_tag_stop parsing."""

    def test_tag_stop(self) -> None:
        result = parse_directive("@@ingestion_tag_stop")
        assert result.action == "tag_stop"
        assert result.metadata == {}

    def test_tag_stop_with_leading_whitespace(self) -> None:
        result = parse_directive("  @@ingestion_tag_stop")
        assert result.action == "tag_stop"

    def test_tag_stop_case_insensitive(self) -> None:
        result = parse_directive("@@INGESTION_TAG_STOP")
        assert result.action == "tag_stop"


class TestParseNone:
    """Tests for messages with no directive."""

    def test_regular_message(self) -> None:
        result = parse_directive("Hello, how are you?")
        assert result.action == "none"

    def test_empty_message(self) -> None:
        result = parse_directive("")
        assert result.action == "none"

    def test_whitespace_only(self) -> None:
        result = parse_directive("   \n  \n  ")
        assert result.action == "none"

    def test_directive_in_middle_of_word(self) -> None:
        """Directive must be a standalone line, not embedded in text."""
        result = parse_directive("text @@ingestion_tag_start more text")
        assert result.action == "none"


class TestParseEdgeCases:
    """Edge cases for directive parsing."""

    def test_colon_in_value(self) -> None:
        """Values may contain colons (e.g. URLs, timestamps)."""
        msg = "@@ingestion_tag_start\nurl: https://example.com:8080/path"
        result = parse_directive(msg)
        assert result.action == "tag_start"
        assert result.metadata == {"url": "https://example.com:8080/path"}

    def test_whitespace_trimming(self) -> None:
        msg = "@@ingestion_tag_start\n  project :  Apollo  \n  milestone :  M4  "
        result = parse_directive(msg)
        assert result.metadata == {"project": "Apollo", "milestone": "M4"}

    def test_empty_value(self) -> None:
        msg = "@@ingestion_tag_start\nproject:"
        result = parse_directive(msg)
        assert result.metadata == {"project": ""}

    def test_invalid_kv_line_skipped(self) -> None:
        """Lines without a colon are silently skipped."""
        msg = "@@ingestion_tag_start\nvalid_key: value\nnot a key value pair\nanother: pair"
        result = parse_directive(msg)
        assert result.metadata == {"valid_key": "value", "another": "pair"}

    def test_last_directive_wins(self) -> None:
        """If both tag_start and tag_stop appear, last one wins."""
        msg = "@@ingestion_tag_start\nproject: X\n@@ingestion_tag_stop"
        result = parse_directive(msg)
        assert result.action == "tag_stop"

    def test_case_insensitive_directive(self) -> None:
        msg = "@@INGESTION_TAG_START\nProject: Alpha"
        result = parse_directive(msg)
        assert result.action == "tag_start"
        assert result.metadata == {"Project": "Alpha"}

    def test_frozen_result(self) -> None:
        """DirectiveResult is immutable."""
        result = parse_directive("@@ingestion_tag_start\nk: v")
        assert result.action == "tag_start"
        # Frozen dataclass — assignment should raise
        try:
            result.action = "none"  # type: ignore[misc]
            assert False, "Should have raised"
        except AttributeError:
            pass
