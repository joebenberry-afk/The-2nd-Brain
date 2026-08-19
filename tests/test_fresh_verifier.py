"""Tests for Fresh Verifier 'record' plumbing (Plan §15, Phase R9)."""

from second_brain.fresh_verifier import (
    VerifierProvenance,
    parse_verdict,
    record_verifier_response,
)


class TestParseVerdict:
    """parse_verdict never guesses: only the exact expected marker counts."""

    def test_parses_pass(self):
        v = parse_verdict("Conclusion: fine\nResult: PASS\n")
        assert v.verdict == "PASS"
        assert v.confidence is None

    def test_parses_fail_case_insensitive_and_verdict_label(self):
        v = parse_verdict("some text\nverdict: fail\nmore text\n")
        assert v.verdict == "FAIL"

    def test_parses_partial_with_confidence(self):
        v = parse_verdict("Result: PARTIAL\nConfidence: 0.65\n")
        assert v.verdict == "PARTIAL"
        assert v.confidence == 0.65

    def test_unparseable_when_no_marker_line_present(self):
        v = parse_verdict("This response never states a clear result.\n")
        assert v.verdict == "UNPARSEABLE"
        assert v.confidence is None

    def test_unparseable_on_empty_string(self):
        assert parse_verdict("").verdict == "UNPARSEABLE"

    def test_does_not_match_the_word_pass_inside_other_text(self):
        # "Result: PASS" must be its own line matching the exact pattern;
        # a mention of "pass" in prose must never be mistaken for a verdict.
        v = parse_verdict("This will pass eventually, I hope.\n")
        assert v.verdict == "UNPARSEABLE"


class TestVerifierProvenance:
    def test_missing_session_id_recorded_as_unavailable_not_invented(self):
        p = VerifierProvenance(provider="anthropic", model="claude-sonnet-5", host="claude-code")
        assert p.session_id_dict() == {
            "available": False,
            "reason": "host does not expose provider run ID",
        }

    def test_present_session_id_recorded_as_available(self):
        p = VerifierProvenance(
            provider="anthropic", model="claude-sonnet-5", host="claude-code", session_id="sess-123"
        )
        assert p.session_id_dict() == {"available": True, "value": "sess-123"}

    def test_missing_usage_recorded_as_null_not_zero(self):
        p = VerifierProvenance(provider=None, model=None, host=None)
        assert p.usage_dict() == {
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
        }

    def test_present_usage_computes_total(self):
        p = VerifierProvenance(
            provider=None, model=None, host=None, input_tokens=100, output_tokens=40
        )
        assert p.usage_dict()["total_tokens"] == 140


class TestRecordVerifierResponse:
    """The verdict is only ever parsed from a raw_response the caller
    already has — record_verifier_response cannot be called before one
    exists (it's a required positional argument)."""

    def test_bundles_prompt_raw_response_provenance_and_verdict(self):
        provenance = VerifierProvenance(
            provider="anthropic", model="claude-sonnet-5", host="claude-code", session_id="sess-1"
        )
        evidence = record_verifier_response(
            prompt="## Requirement\nDo the thing.\n",
            raw_response="Conclusion: works\nResult: PASS\n",
            provenance=provenance,
        )
        assert evidence.prompt == "## Requirement\nDo the thing.\n"
        assert evidence.raw_response == "Conclusion: works\nResult: PASS\n"
        assert evidence.verdict.verdict == "PASS"
        d = evidence.to_dict()
        assert d["provider"] == "anthropic"
        assert d["session_id"] == {"available": True, "value": "sess-1"}
        assert isinstance(d["captured_at"], str) and d["captured_at"]

    def test_never_fabricates_a_verdict_for_an_ambiguous_response(self):
        provenance = VerifierProvenance(provider=None, model=None, host=None)
        evidence = record_verifier_response(
            prompt="p", raw_response="I think it's probably okay.", provenance=provenance
        )
        assert evidence.verdict.verdict == "UNPARSEABLE"
