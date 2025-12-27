"""Tests for clustering."""

import pytest

from thirteen_f.analysis.clustering import assign_cluster, cluster_holdings, summarize_clusters


class TestAssignCluster:
    def test_ai_semiconductors(self):
        assert assign_cluster("NVIDIA CORP") == "AI/Semiconductors"
        assert assign_cluster("ADVANCED MICRO DEVICES INC") == "AI/Semiconductors"
        assert assign_cluster("TAIWAN SEMICONDUCTOR MFG CO LTD") == "AI/Semiconductors"

    def test_cloud_saas(self):
        assert assign_cluster("SALESFORCE INC") == "Cloud/SaaS"
        assert assign_cluster("SNOWFLAKE INC") == "Cloud/SaaS"
        assert assign_cluster("DATADOG INC") == "Cloud/SaaS"

    def test_fintech(self):
        assert assign_cluster("VISA INC") == "Fintech/Payments"
        assert assign_cluster("MASTERCARD INC") == "Fintech/Payments"
        assert assign_cluster("BLOCK INC") == "Fintech/Payments"

    def test_social_advertising(self):
        assert assign_cluster("META PLATFORMS INC") == "Social/Advertising"
        assert assign_cluster("ALPHABET INC") == "Social/Advertising"

    def test_healthcare(self):
        assert assign_cluster("UNITEDHEALTH GROUP INC") == "Healthcare/Biotech"
        assert assign_cluster("ELI LILLY AND CO") == "Healthcare/Biotech"

    def test_other(self):
        assert assign_cluster("RANDOM UNKNOWN COMPANY") == "Other"
        assert assign_cluster("XYZ HOLDINGS LLC") == "Other"


class TestClusterHoldings:
    def test_cluster_multiple_holdings(self):
        holdings = [
            ("NVIDIA CORP", 1000000, 0.10),
            ("AMD INC", 500000, 0.05),
            ("SALESFORCE INC", 300000, 0.03),
            ("RANDOM COMPANY", 100000, 0.01),
        ]
        clusters = cluster_holdings(holdings)

        assert "AI/Semiconductors" in clusters
        assert len(clusters["AI/Semiconductors"]) == 2
        assert "Cloud/SaaS" in clusters
        assert "Other" in clusters


class TestSummarizeClusters:
    def test_summarize(self):
        holdings = [
            ("NVIDIA CORP", 1000000, 0.10),
            ("AMD INC", 500000, 0.05),
            ("SALESFORCE INC", 300000, 0.03),
        ]
        summaries = summarize_clusters(holdings)

        # Should be sorted by value descending
        assert summaries[0][0] == "AI/Semiconductors"
        assert summaries[0][1] == 1500000  # Total value
        assert summaries[0][2] == 0.15  # Total weight
        assert summaries[0][3] == 2  # Count
