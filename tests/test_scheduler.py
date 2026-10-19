import pytest

from bgm_factory.config import ScheduleSettings


def test_three_daily_production_times_are_parsed() -> None:
    settings = ScheduleSettings(production_times=["06:00", "13:00", "20:00"])

    assert settings.parsed_production_times() == [(6, 0), (13, 0), (20, 0)]


def test_duplicate_production_times_are_rejected() -> None:
    settings = ScheduleSettings(production_times=["06:00", "06:00"])

    with pytest.raises(ValueError, match="unique"):
        settings.parsed_production_times()
