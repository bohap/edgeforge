import json

import pytest

from edgeforge.core.config import LogFormat, Settings
from edgeforge.core.logging import configure_logging, get_logger


def test_json_logs_include_level_timestamp_and_fields(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(Settings(_env_file=None, log_format=LogFormat.JSON, log_level="INFO"))

    get_logger("test").info("match_normalized", match_id="m1", dq_issues=2)

    record = json.loads(capsys.readouterr().out.strip())
    assert record["event"] == "match_normalized"
    assert record["match_id"] == "m1"
    assert record["dq_issues"] == 2
    assert record["level"] == "info"
    assert record["timestamp"].endswith("Z")


def test_level_filter_drops_lower_levels(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(Settings(_env_file=None, log_format=LogFormat.JSON, log_level="WARNING"))

    get_logger("test").info("hidden")
    get_logger("test").warning("shown")

    lines = capsys.readouterr().out.strip().splitlines()
    assert [json.loads(line)["event"] for line in lines] == ["shown"]
