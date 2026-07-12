"""IndicatorSpec/PriceLevelAnnotation round-trips and legacy-string upgrade
(§8.1) — indicators must survive from PDF extraction JSON through to a
structured, plottable shape, and pre-existing plain-string specs must still
parse instead of crashing."""

from __future__ import annotations

from src.ai.domain.models import (
    AnnotationType,
    ExtractedStrategySpec,
    IndicatorSpec,
    IndicatorType,
    PriceLevelAnnotation,
    _legacy_indicator_from_token,
)


def test_indicator_spec_round_trips_each_family():
    for type_, period, params in [
        (IndicatorType.EMA, 200, {}),
        (IndicatorType.SMA, 50, {}),
        (IndicatorType.RSI, 14, {}),
        (IndicatorType.MACD, 12, {"slow": 26.0, "signal": 9.0}),
        (IndicatorType.BOLLINGER, 20, {"std_dev": 2.0}),
    ]:
        spec = IndicatorSpec(type=type_, period=period, label=type_.value, params=params)
        assert IndicatorSpec.from_dict(spec.to_dict()) == spec


def test_price_level_annotation_round_trips():
    level = PriceLevelAnnotation(type=AnnotationType.RESISTANCE, price=2050.0, label="2050")
    assert PriceLevelAnnotation.from_dict(level.to_dict()) == level


def test_legacy_token_parses_known_families():
    assert _legacy_indicator_from_token("EMA200") == IndicatorSpec(
        type=IndicatorType.EMA, period=200, label="EMA200"
    )
    assert _legacy_indicator_from_token("RSI(14)") == IndicatorSpec(
        type=IndicatorType.RSI, period=14, label="RSI(14)"
    )
    assert _legacy_indicator_from_token("sma50") == IndicatorSpec(
        type=IndicatorType.SMA, period=50, label="sma50"
    )


def test_legacy_token_rejects_unrecognized_text():
    assert _legacy_indicator_from_token("Ichimoku Cloud") is None
    assert _legacy_indicator_from_token("MACD") is None


def test_from_dict_upgrades_legacy_string_indicators():
    spec = ExtractedStrategySpec.from_dict(
        {
            "name": "legacy",
            "indicators": ["EMA200", "Ichimoku Cloud"],
        }
    )
    assert spec.indicators == (IndicatorSpec(type=IndicatorType.EMA, period=200, label="EMA200"),)
    assert spec.unrecognized_indicators == ("Ichimoku Cloud",)


def test_from_dict_accepts_structured_indicators_and_new_fields():
    spec = ExtractedStrategySpec.from_dict(
        {
            "name": "structured",
            "indicators": [{"type": "rsi", "period": 14, "label": "RSI14"}],
            "unrecognized_indicators": ["Parabolic SAR"],
            "price_levels": [
                {"type": "resistance", "price": 2050.0, "label": "resistance at 2050"}
            ],
            "chart_notes": ["Fibonacci retracement on swing points"],
        }
    )
    assert spec.indicators == (IndicatorSpec(type=IndicatorType.RSI, period=14, label="RSI14"),)
    assert spec.unrecognized_indicators == ("Parabolic SAR",)
    assert spec.price_levels == (
        PriceLevelAnnotation(
            type=AnnotationType.RESISTANCE, price=2050.0, label="resistance at 2050"
        ),
    )
    assert spec.chart_notes == ("Fibonacci retracement on swing points",)


def test_to_dict_from_dict_round_trip_preserves_new_fields():
    original = ExtractedStrategySpec.from_dict(
        {
            "name": "round_trip",
            "indicators": [{"type": "ema", "period": 200, "label": "EMA200"}],
            "price_levels": [
                {"type": "support", "price": 1985.5, "label": "support around 1985.50"}
            ],
            "chart_notes": ["draw a trendline connecting recent lows"],
        }
    )
    assert ExtractedStrategySpec.from_dict(original.to_dict()) == original
