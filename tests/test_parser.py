"""Tests for 13F XML parser."""

import pytest

from thirteen_f.edgar.parser import (
    Holding,
    _normalize_cusip,
    _normalize_text,
    compute_filing_totals,
    parse_13f_info_table,
)


class TestNormalization:
    def test_normalize_text(self):
        assert _normalize_text("  NVIDIA  CORP  ") == "NVIDIA CORP"
        assert _normalize_text("Apple\tInc") == "Apple Inc"

    def test_normalize_cusip(self):
        assert _normalize_cusip("037833100") == "037833100"
        assert _normalize_cusip("03783310") == "03783310 "  # Padded
        assert _normalize_cusip("  037833100  ") == "037833100"


class TestParser:
    def test_parse_simple_xml(self):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
            <infoTable>
                <nameOfIssuer>NVIDIA CORP</nameOfIssuer>
                <titleOfClass>COM</titleOfClass>
                <cusip>67066G104</cusip>
                <value>1000000</value>
                <shrsOrPrnAmt>
                    <sshPrnamt>10000</sshPrnamt>
                    <sshPrnamtType>SH</sshPrnamtType>
                </shrsOrPrnAmt>
                <investmentDiscretion>SOLE</investmentDiscretion>
                <votingAuthority>
                    <Sole>10000</Sole>
                    <Shared>0</Shared>
                    <None>0</None>
                </votingAuthority>
            </infoTable>
        </informationTable>
        """
        holdings = parse_13f_info_table(xml)
        assert len(holdings) == 1

        h = holdings[0]
        assert h.issuer_name == "NVIDIA CORP"
        assert h.cusip == "67066G104"
        assert h.value_thousands == 1000000
        assert h.value_usd == 1000000000
        assert h.shares_or_principal == 10000
        assert h.shares_type == "SH"

    def test_parse_with_put_call(self):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
            <infoTable>
                <nameOfIssuer>APPLE INC</nameOfIssuer>
                <titleOfClass>COM</titleOfClass>
                <cusip>037833100</cusip>
                <value>500000</value>
                <shrsOrPrnAmt>
                    <sshPrnamt>5000</sshPrnamt>
                    <sshPrnamtType>SH</sshPrnamtType>
                </shrsOrPrnAmt>
                <putCall>Put</putCall>
                <investmentDiscretion>SOLE</investmentDiscretion>
                <votingAuthority>
                    <Sole>0</Sole>
                    <Shared>0</Shared>
                    <None>5000</None>
                </votingAuthority>
            </infoTable>
        </informationTable>
        """
        holdings = parse_13f_info_table(xml)
        assert len(holdings) == 1
        assert holdings[0].put_call == "Put"

    def test_parse_empty_xml(self):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
        </informationTable>
        """
        holdings = parse_13f_info_table(xml)
        assert len(holdings) == 0


class TestFilingTotals:
    def test_compute_totals(self):
        holdings = [
            Holding(
                issuer_name="A",
                title_of_class="COM",
                cusip="000000000",
                figi=None,
                value_thousands=1000,
                value_usd=1000000,
                shares_or_principal=100,
                shares_type="SH",
                put_call=None,
                investment_discretion="SOLE",
                voting_sole=100,
                voting_shared=0,
                voting_none=0,
            ),
            Holding(
                issuer_name="B",
                title_of_class="COM",
                cusip="111111111",
                figi=None,
                value_thousands=2000,
                value_usd=2000000,
                shares_or_principal=200,
                shares_type="SH",
                put_call=None,
                investment_discretion="SOLE",
                voting_sole=200,
                voting_shared=0,
                voting_none=0,
            ),
        ]

        total_value, count = compute_filing_totals(holdings)
        assert total_value == 3000000
        assert count == 2
