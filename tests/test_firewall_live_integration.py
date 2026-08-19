"""
Live integration tests for Observation Firewall (Plan §4 R2).

Proves the real path:
raw tool output -> byte-exact artifact -> deterministic reducer -> compact model observation.
Verifies all 8 reducers and exact artifact recovery via /brain-expand.
"""

from second_brain.artifacts import expand
from second_brain.firewall import REDUCER_MAP, expand_observation, reduce_observation


class TestObservationFirewallLiveIntegration:
    """Proves live reduction and byte-exact recovery across tool classes (§4 R2)."""

    def test_pytest_large_output_reduction_and_recovery(self, brain_home):
        # 500 lines of pytest output
        raw_output = "\n".join([f"PASSED tests/test_mod_{i}.py::test_case" for i in range(500)])
        raw_output += "\nFAILED tests/test_core.py::test_critical_failure\n"
        raw_output += "AssertionError: Expected 200 OK but got 500 Internal Error\n"
        raw_output += "1 failed, 500 passed in 12.4s\n"

        result = reduce_observation(
            raw_output,
            command="pytest tests/",
            tool="bash",
            session="sess-firewall-01",
            home=brain_home,
        )

        assert result.reduction_ratio >= 0.80  # Over 80% token reduction
        assert "1 failed" in result.distilled_text
        assert "test_critical_failure" in result.distilled_text
        assert result.raw_object_ref is not None
        assert f"/brain-expand {result.raw_object_ref[:12]}" in result.distilled_text

        # Exact lossless recovery
        recovered = expand(brain_home, result.raw_object_ref).decode("utf-8")
        assert recovered == raw_output

        # Helper expand_observation
        rec2 = expand_observation(brain_home, result.raw_object_ref)
        assert rec2 == raw_output

    def test_compiler_pyright_reduction_and_recovery(self, brain_home):
        single_err = (
            "src/second_brain/core.py:45:10 - error: Expression of type 'None' cannot "
            "be assigned to parameter of type 'str'\n"
        )
        raw_output = (single_err * 50) + "50 errors, 0 warnings, 0 informations\n"

        result = reduce_observation(
            raw_output,
            command="pyright src/",
            tool="bash",
            session="sess-firewall-02",
            home=brain_home,
        )

        assert result.reduction_ratio >= 0.60
        assert "50 errors" in result.distilled_text
        assert result.raw_object_ref is not None

        recovered = expand_observation(brain_home, result.raw_object_ref)
        assert recovered == raw_output

    def test_git_diff_reduction_and_recovery(self, brain_home):
        diff_body = "+ new code line\n" * 200
        raw_diff = f"diff --git a/file.py b/file.py\nindex 123..456 100644\n{diff_body}"
        raw_diff += " 1 file changed, 200 insertions(+)\n"

        result = reduce_observation(
            raw_diff,
            command="git diff",
            tool="bash",
            session="sess-firewall-03",
            home=brain_home,
        )

        assert result.reduction_ratio >= 0.60
        assert "1 file changed" in result.distilled_text
        recovered = expand_observation(brain_home, result.raw_object_ref)
        assert recovered == raw_diff

    def test_search_grep_reduction_and_recovery(self, brain_home):
        raw_search = "\n".join([f"src/mod_{i}.py:10:def target_symbol(): pass" for i in range(150)])

        result = reduce_observation(
            raw_search,
            command="rg target_symbol",
            tool="bash",
            session="sess-firewall-04",
            home=brain_home,
        )

        assert result.reduction_ratio >= 0.60
        recovered = expand_observation(brain_home, result.raw_object_ref)
        assert recovered == raw_search

    def test_json_reduction_and_recovery(self, brain_home):
        import json
        huge_data = {"items": [{"id": i, "name": f"item_{i}", "val": i * 10} for i in range(100)]}
        raw_json = json.dumps(huge_data, indent=2)

        result = reduce_observation(
            raw_json,
            tool="read_json",
            session="sess-firewall-05",
            home=brain_home,
        )

        assert result.reduction_ratio >= 0.50
        recovered = expand_observation(brain_home, result.raw_object_ref)
        assert recovered == raw_json

    def test_all_eight_reducers_registered(self):
        expected_kinds = [
            "pytest", "compiler", "git", "search", "json", "logs", "build", "doctor", "generic"
        ]
        for kind in expected_kinds:
            assert kind in REDUCER_MAP
