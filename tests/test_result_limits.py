"""Tests for result-size control on history and statistics tools."""

import pytest

from app.server import _downsample, _flatten_history, _limit_statistics, _trim_attributes


def _states(n):
    """n synthetic history states, each carrying a fat attribute dict."""
    return [
        [
            {
                "entity_id": "climate.hallway",
                "state": "cool",
                "last_changed": f"2026-05-15T{i // 60:02d}:{i % 60:02d}:00+00:00",
                "attributes": {
                    "hvac_action": "cooling" if i % 2 else "idle",
                    "current_temperature": 70 + (i % 5),
                    "friendly_name": "Hallway",
                    "target_temp_high": None,
                    "fan_mode": "off",
                },
            }
            for i in range(n)
        ]
    ]


class TestDownsample:
    def test_returns_input_when_under_limit(self):
        points = [1, 2, 3]
        assert _downsample(points, 10) == points
        assert _downsample(points, None) == points

    def test_caps_at_limit(self):
        assert len(_downsample(list(range(1000)), 50)) == 50

    def test_keeps_first_and_last(self):
        sampled = _downsample(list(range(1000)), 10)
        assert sampled[0] == 0
        assert sampled[-1] == 999

    def test_samples_evenly_rather_than_truncating(self):
        # A head-truncation would return 0..9 and hide the rest of the window.
        sampled = _downsample(list(range(100)), 10)
        assert sampled != list(range(10))
        assert sampled == sorted(sampled)

    def test_limit_of_one_returns_latest(self):
        assert _downsample(list(range(50)), 1) == [49]

    def test_non_positive_limit_is_ignored(self):
        points = list(range(5))
        assert _downsample(points, 0) == points


class TestTrimAttributes:
    def test_none_keeps_everything(self):
        states = _states(1)[0]
        assert _trim_attributes(states, None)[0]["attributes"] == states[0]["attributes"]

    def test_empty_list_drops_all_attributes(self):
        assert _trim_attributes(_states(1)[0], [])[0]["attributes"] == {}

    def test_selects_requested_keys_only(self):
        trimmed = _trim_attributes(_states(1)[0], ["hvac_action"])
        assert trimmed[0]["attributes"] == {"hvac_action": "idle"}

    def test_does_not_mutate_input(self):
        states = _states(1)[0]
        _trim_attributes(states, [])
        assert "hvac_action" in states[0]["attributes"]

    def test_missing_key_is_skipped(self):
        trimmed = _trim_attributes(_states(1)[0], ["nope"])
        assert trimmed[0]["attributes"] == {}


class TestFlattenHistory:
    def test_defaults_unchanged(self):
        result = _flatten_history(_states(30), "climate.hallway")
        assert result["count"] == 30
        assert "downsampled" not in result
        assert "total_count" not in result

    def test_limit_reports_truncation(self):
        result = _flatten_history(_states(500), "climate.hallway", limit=25)
        assert result["count"] == 25
        assert result["total_count"] == 500
        assert result["downsampled"] is True

    def test_span_is_preserved_when_downsampled(self):
        full = _flatten_history(_states(500), "climate.hallway")
        limited = _flatten_history(_states(500), "climate.hallway", limit=25)
        assert limited["first_changed"] == full["first_changed"]
        assert limited["last_changed"] == full["last_changed"]

    def test_attributes_filter_applies(self):
        result = _flatten_history(
            _states(10), "climate.hallway", attributes=["hvac_action"]
        )
        assert all(set(s["attributes"]) == {"hvac_action"} for s in result["states"])

    def test_error_passthrough(self):
        result = _flatten_history({"error": "boom"}, "climate.hallway", limit=5)
        assert result["error"] == "boom"
        assert result["states"] == []

    def test_empty_history(self):
        result = _flatten_history([], "climate.hallway", limit=5)
        assert result["count"] == 0
        assert "note" in result


class TestLimitStatistics:
    def _result(self, n):
        return {
            "entity_id": "sensor.power",
            "period": "5minute",
            "statistics": [{"start": i, "mean": float(i)} for i in range(n)],
        }

    def test_no_limit_is_unchanged(self):
        result = self._result(600)
        assert _limit_statistics(result, None) == result

    def test_under_limit_is_unchanged(self):
        result = self._result(10)
        assert _limit_statistics(result, 50) == result

    def test_caps_and_annotates(self):
        limited = _limit_statistics(self._result(576), 50)
        assert len(limited["statistics"]) == 50
        assert limited["total_count"] == 576
        assert limited["downsampled"] is True

    def test_preserves_other_keys(self):
        limited = _limit_statistics(self._result(576), 50)
        assert limited["entity_id"] == "sensor.power"
        assert limited["period"] == "5minute"

    def test_keeps_latest_point(self):
        limited = _limit_statistics(self._result(576), 50)
        assert limited["statistics"][-1]["start"] == 575

    def test_error_result_passthrough(self):
        err = {"entity_id": "sensor.power", "error": "nope", "statistics": []}
        assert _limit_statistics(err, 50) == err
