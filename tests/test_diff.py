"""Tests for diff engine."""

import pytest

from thirteen_f.analysis.diff import PositionDiff


class TestPositionDiff:
    def test_new_position(self):
        diff = PositionDiff(
            cusip="67066G104",
            issuer_name="NVIDIA CORP",
            title_of_class="COM",
            prev_value_usd=None,
            now_value_usd=1000000,
            delta_value_usd=1000000,
            prev_shares=None,
            now_shares=1000,
            delta_shares=1000,
            prev_weight=None,
            now_weight=0.05,
            growth_rate=None,  # Infinite for new positions
            portfolio_impact=0.05,
            change_type="NEW",
            is_starter=False,
        )
        assert diff.change_type == "NEW"
        assert diff.growth_rate is None
        assert diff.delta_value_usd == 1000000

    def test_exit_position(self):
        diff = PositionDiff(
            cusip="037833100",
            issuer_name="APPLE INC",
            title_of_class="COM",
            prev_value_usd=500000,
            now_value_usd=None,
            delta_value_usd=-500000,
            prev_shares=500,
            now_shares=None,
            delta_shares=-500,
            prev_weight=0.025,
            now_weight=None,
            growth_rate=-1.0,
            portfolio_impact=-0.025,
            change_type="EXIT",
            is_starter=False,
        )
        assert diff.change_type == "EXIT"
        assert diff.delta_value_usd == -500000

    def test_increase_position(self):
        diff = PositionDiff(
            cusip="594918104",
            issuer_name="MICROSOFT CORP",
            title_of_class="COM",
            prev_value_usd=1000000,
            now_value_usd=1500000,
            delta_value_usd=500000,
            prev_shares=1000,
            now_shares=1500,
            delta_shares=500,
            prev_weight=0.05,
            now_weight=0.075,
            growth_rate=0.5,  # 50% increase
            portfolio_impact=0.025,
            change_type="INCREASE",
            is_starter=False,
        )
        assert diff.change_type == "INCREASE"
        assert diff.growth_rate == 0.5
        assert diff.delta_value_usd == 500000

    def test_starter_position(self):
        diff = PositionDiff(
            cusip="000000000",
            issuer_name="SMALL POSITION",
            title_of_class="COM",
            prev_value_usd=None,
            now_value_usd=2000000,  # $2M - below $5M threshold
            delta_value_usd=2000000,
            prev_shares=None,
            now_shares=100,
            delta_shares=100,
            prev_weight=None,
            now_weight=0.001,  # 0.1% - within 0.01%-0.25% range
            growth_rate=None,
            portfolio_impact=0.001,
            change_type="NEW",
            is_starter=True,
        )
        assert diff.is_starter is True

    def test_to_dict(self):
        diff = PositionDiff(
            cusip="67066G104",
            issuer_name="NVIDIA",
            title_of_class="COM",
            prev_value_usd=100,
            now_value_usd=200,
            delta_value_usd=100,
            prev_shares=10,
            now_shares=20,
            delta_shares=10,
            prev_weight=0.01,
            now_weight=0.02,
            growth_rate=1.0,
            portfolio_impact=0.01,
            change_type="INCREASE",
            is_starter=False,
        )
        d = diff.to_dict()
        assert d["cusip"] == "67066G104"
        assert d["growth_rate"] == 1.0
        assert d["change_type"] == "INCREASE"
