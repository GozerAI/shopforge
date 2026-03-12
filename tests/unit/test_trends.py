"""Tests for TrendEnricher."""

from unittest.mock import patch

from shopforge.trends import TrendEnricher


def _mock_trends():
    return [
        {"name": "pets", "direction": "rising", "strength": 80, "category": "market"},
        {"name": "tech", "direction": "falling", "strength": 60, "category": "market"},
        {"name": "wellness", "direction": "rising", "strength": 50, "category": "market"},
    ]


class TestTrendEnricher:
    def test_calculate_trend_score_with_rising_tag(self):
        enricher = TrendEnricher()
        enricher._trends_cache = _mock_trends()

        product = {"title": "Dog Leash", "tags": ["pets", "dog"], "segments": [], "price": 25}
        result = enricher.calculate_trend_score(product)

        assert result["trend_score"] is not None
        assert result["trend_score"] > 50  # Rising trend should boost score
        assert len(result["trend_signals"]) > 0

    def test_calculate_trend_score_with_falling_tag(self):
        enricher = TrendEnricher()
        enricher._trends_cache = _mock_trends()

        product = {"title": "Phone Case", "tags": ["tech", "electronics"], "segments": [], "price": 15}
        result = enricher.calculate_trend_score(product)

        assert result["trend_score"] is not None
        assert result["trend_score"] < 55  # Falling trend should lower score

    def test_calculate_trend_score_no_trends(self):
        enricher = TrendEnricher()
        enricher._trends_cache = []

        product = {"title": "Widget", "tags": ["misc"], "segments": [], "price": 10}
        result = enricher.calculate_trend_score(product)

        assert result["trend_score"] is None
        assert result["opportunity_score"] is None
        assert result["trend_signals"] == []

    def test_enrich_products(self):
        enricher = TrendEnricher()
        enricher._trends_cache = _mock_trends()

        products = [
            {"title": "Cat Toy", "tags": ["pets"], "segments": [], "price": 10},
            {"title": "Yoga Mat", "tags": ["wellness"], "segments": [], "price": 30},
        ]
        enriched = enricher.enrich_products(products)

        assert len(enriched) == 2
        assert "trend_score" in enriched[0]
        assert "opportunity_score" in enriched[1]

    def test_segment_trend_analysis(self):
        enricher = TrendEnricher()
        enricher._trends_cache = _mock_trends()

        products = [
            {"title": "Dog Leash", "tags": ["pets"], "segments": ["pets"], "price": 25},
            {"title": "Cat Toy", "tags": ["pets"], "segments": ["pets"], "price": 10},
            {"title": "Charger", "tags": ["tech"], "segments": ["tech"], "price": 20},
        ]
        analysis = enricher.get_segment_trend_analysis(products)

        assert "pets" in analysis
        assert "tech" in analysis
        assert analysis["pets"]["products"] == 2
        assert analysis["tech"]["products"] == 1
        assert analysis["pets"]["trend_sentiment"] in ("positive", "negative", "neutral")
