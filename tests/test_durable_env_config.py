import os

import durable_execution


def test_blank_durable_cost_falls_back_to_video_cap(monkeypatch):
    monkeypatch.setenv("DURABLE_JOB_MAX_COST_USD", "")
    monkeypatch.setenv("MAX_VIDEO_COST_USD", "12.50")

    value = durable_execution.normalize_durable_job_max_cost_env()

    assert value == 12.5
    assert os.environ["DURABLE_JOB_MAX_COST_USD"] == "12.50"


def test_blank_costs_fall_back_to_default(monkeypatch):
    monkeypatch.setenv("DURABLE_JOB_MAX_COST_USD", "   ")
    monkeypatch.setenv("MAX_VIDEO_COST_USD", "")

    value = durable_execution.normalize_durable_job_max_cost_env()

    assert value == 10.0
    assert os.environ["DURABLE_JOB_MAX_COST_USD"] == "10.00"


def test_valid_durable_cost_takes_precedence(monkeypatch):
    monkeypatch.setenv("DURABLE_JOB_MAX_COST_USD", "7.25")
    monkeypatch.setenv("MAX_VIDEO_COST_USD", "15")

    value = durable_execution.normalize_durable_job_max_cost_env()

    assert value == 7.25
    assert os.environ["DURABLE_JOB_MAX_COST_USD"] == "7.25"


def test_invalid_numeric_value_is_treated_as_unset(monkeypatch):
    monkeypatch.setenv("DURABLE_JOB_MAX_COST_USD", "not-a-number")
    monkeypatch.setenv("MAX_VIDEO_COST_USD", "9.5")

    value = durable_execution.normalize_durable_job_max_cost_env()

    assert value == 9.5
    assert os.environ["DURABLE_JOB_MAX_COST_USD"] == "9.5"
