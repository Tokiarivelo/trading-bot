"""Wire schemas for the `/news` HTTP API. Mirrors `news/domain/models.py`;
times are epoch seconds UTC, matching the market-data/candle convention.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class NewsEventOut(BaseModel):
    """One upcoming calendar release."""

    name: str
    time: int = Field(description="Scheduled release time, epoch seconds UTC.")
    impact: str = Field(description="'low', 'medium', or 'high'.")
    currency: str = Field(description="Affected currency/country code, e.g. 'USD'.")
    skill: str | None = Field(
        default=None,
        description="Matched news skill name from `configs/news.yaml: tracked_events`, "
        "if any — null means this event never activates a news window.",
    )
    forecast: str | None = Field(
        default=None,
        description="Consensus estimate, formatted as the source publishes it "
        "(e.g. '8.5%', '1950B'). Null if the source doesn't provide one.",
    )
    previous: str | None = Field(
        default=None, description="Prior period's reading, same formatting caveat as `forecast`."
    )
    actual: str | None = Field(
        default=None,
        description="Released value, if the event has already happened and the source "
        "reports it. ForexFactory's calendar never populates this; Finnhub does once "
        "released.",
    )


class NewsWindowOut(BaseModel):
    """A currently-active before/after window around one calendar event."""

    event: NewsEventOut
    skill: str = Field(description="The news skill whose activation window is active.")
    window_start: int = Field(description="Epoch seconds UTC.")
    window_end: int = Field(description="Epoch seconds UTC.")
    phase: str = Field(description="'pre' (before the release) or 'post' (after it).")
    symbols: list[str] = Field(
        description="Symbols this window affects (`skills/news/<skill>.yaml: "
        "activation.symbols`) — the chart uses this to shade only the symbols "
        "actually under a news skill right now."
    )
