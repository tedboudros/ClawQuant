"""Finnhub market data provider -- fetches via httpx (no extra dependencies).

Supports stocks, ETFs, and crypto using Yahoo-style ticker formats.
Automatically maps Yahoo tickers to Finnhub's symbol conventions:
  BTC-USD  → BINANCE:BTCUSDT  (crypto)
  EURUSD=X → OANDA:EUR_USD    (forex)
  AAPL     → AAPL             (stocks / ETFs, pass-through)

Free API key required: https://finnhub.io/register
Free tier: 60 requests/minute — no credit card needed.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import httpx

from core.models.market import MarketData

logger = logging.getLogger(__name__)

PLUGIN_META = {
    "name": "finnhub",
    "display_name": "Finnhub",
    "description": "Stocks, ETFs, crypto — real-time data, free API key required (60 req/min)",
    "category": "market_data",
    "protocols": ["market_data"],
    "class_name": "FinnhubProvider",
    "pip_dependencies": [],
    "setup_instructions": """
Finnhub provides real-time stock quotes and historical OHLCV data.
A free API key is required (60 requests/minute, no credit card needed).

Sign up at: https://finnhub.io/register

Then add the key to your ~/.clawquant/.env file:
  FINNHUB_API_KEY=your_key_here

And reference it in config.yaml:
  market_data:
    providers:
      finnhub:
        enabled: true
        api_key: ${FINNHUB_API_KEY}
        tickers: [AAPL, NVDA, SPY, BTC-USD]

Supported ticker formats (same as Yahoo Finance):
  Stocks/ETFs: AAPL, NVDA, SPY, QQQ
  Crypto:      BTC-USD, ETH-USD, SOL-USD  (mapped to BINANCE:XYZUSDT)
  Forex:       EURUSD=X, GBPUSD=X         (mapped to OANDA:EUR_USD)
""",
    "config_fields": [
        {
            "key": "api_key",
            "label": "Finnhub API Key",
            "type": "secret",
            "required": True,
            "env_var": "FINNHUB_API_KEY",
            "description": "Your Finnhub API key (get one free at finnhub.io/register)",
            "placeholder": "your_finnhub_api_key_here",
        },
        {
            "key": "tickers",
            "label": "Tickers to track",
            "type": "list",
            "required": False,
            "default": ["AAPL", "NVDA", "SPY", "QQQ", "BTC-USD"],
            "description": "Comma-separated ticker symbols (same format as Yahoo Finance)",
            "placeholder": "AAPL, NVDA, SPY, BTC-USD, ETH-USD",
        },
    ],
}

_BASE_URL = "https://finnhub.io/api/v1"

# Explicit crypto mapping: Yahoo-style "ASSET-USD" → Finnhub "EXCHANGE:SYMBOLUSDT"
# Covers the most commonly tracked coins. Unknown -USD tickers are auto-mapped.
_CRYPTO_MAP: dict[str, str] = {
    "BTC-USD": "BINANCE:BTCUSDT",
    "ETH-USD": "BINANCE:ETHUSDT",
    "SOL-USD": "BINANCE:SOLUSDT",
    "BNB-USD": "BINANCE:BNBUSDT",
    "XRP-USD": "BINANCE:XRPUSDT",
    "DOGE-USD": "BINANCE:DOGEUSDT",
    "ADA-USD": "BINANCE:ADAUSDT",
    "AVAX-USD": "BINANCE:AVAXUSDT",
    "DOT-USD": "BINANCE:DOTUSDT",
    "MATIC-USD": "BINANCE:MATICUSDT",
    "LINK-USD": "BINANCE:LINKUSDT",
    "LTC-USD": "BINANCE:LTCUSDT",
    "UNI-USD": "BINANCE:UNIUSDT",
    "ATOM-USD": "BINANCE:ATOMUSDT",
    "TRX-USD": "BINANCE:TRXUSDT",
    "TON-USD": "BINANCE:TONUSDT",
    "SHIB-USD": "BINANCE:SHIBUSDT",
    "BCH-USD": "BINANCE:BCHUSDT",
    "NEAR-USD": "BINANCE:NEARUSDT",
    "APT-USD": "BINANCE:APTUSDT",
    "ARB-USD": "BINANCE:ARBUSDT",
    "OP-USD": "BINANCE:OPUSDT",
    "INJ-USD": "BINANCE:INJUSDT",
    "SUI-USD": "BINANCE:SUIUSDT",
}

# Pattern to recognise Yahoo-style forex tickers: XXXYYY=X (e.g. EURUSD=X)
_FOREX_RE = re.compile(r"^([A-Z]{3})([A-Z]{3})=X$")


def _yahoo_forex_to_oanda(ticker: str) -> str | None:
    """Convert Yahoo forex ticker (EURUSD=X) to OANDA:EUR_USD."""
    match = _FOREX_RE.match(ticker.upper())
    if not match:
        return None
    return f"OANDA:{match.group(1)}_{match.group(2)}"


def _classify_ticker(ticker: str) -> str:
    """Return 'crypto', 'forex', or 'stock'."""
    upper = ticker.upper()
    if upper in _CRYPTO_MAP or upper.endswith("-USD"):
        return "crypto"
    if _FOREX_RE.match(upper):
        return "forex"
    return "stock"


def _to_finnhub_symbol(ticker: str) -> str | None:
    """Convert a Yahoo-style ticker to Finnhub's expected symbol string.

    Returns None when no mapping is possible.
    """
    upper = ticker.upper()
    kind = _classify_ticker(upper)

    if kind == "crypto":
        explicit = _CRYPTO_MAP.get(upper)
        if explicit:
            return explicit
        # Generic fallback: "FOO-USD" → "BINANCE:FOOUSDT"
        base = upper.removesuffix("-USD")
        return f"BINANCE:{base}USDT"

    if kind == "forex":
        return _yahoo_forex_to_oanda(upper)

    # Stocks / ETFs — Finnhub uses plain symbols (US markets).
    # Strip index prefix (^) that Yahoo uses: ^SPX → SPX
    return upper.lstrip("^")


class FinnhubProvider:
    """Fetches market data from Finnhub using their free REST API.

    Implements the MarketDataProvider protocol.
    Requires a free API key from https://finnhub.io/register.
    """

    def __init__(self, api_key: str, tickers: list[str] | None = None) -> None:
        self._api_key = (api_key or "").strip()
        self._tickers: set[str] = {t.upper() for t in (tickers or [])}
        self._client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "X-Finnhub-Token": self._api_key,
                "User-Agent": "ClawQuant/0.1",
            },
        )

    @property
    def name(self) -> str:
        return "finnhub"

    def supports(self, ticker: str) -> bool:
        """Return True if this provider can handle the given ticker."""
        if not self._api_key:
            return False

        upper = ticker.upper()

        if self._tickers:
            return upper in self._tickers

        # If no explicit ticker list was configured, accept anything we can map.
        return _to_finnhub_symbol(upper) is not None

    async def fetch(
        self,
        tickers: list[str],
        start: datetime,
        end: datetime,
    ) -> list[MarketData]:
        """Fetch historical daily OHLCV data for the given tickers."""
        if not self._api_key:
            logger.warning("Finnhub: no API key configured, skipping fetch")
            return []

        results: list[MarketData] = []
        for ticker in tickers:
            try:
                data = await self._fetch_ticker(ticker, start, end)
                results.extend(data)
            except Exception:
                logger.exception("Finnhub: failed to fetch data for %s", ticker)

        return results

    async def _fetch_ticker(
        self,
        ticker: str,
        start: datetime,
        end: datetime,
    ) -> list[MarketData]:
        """Fetch candle data for a single ticker."""
        finnhub_symbol = _to_finnhub_symbol(ticker)
        if finnhub_symbol is None:
            logger.warning("Finnhub: no symbol mapping for ticker %s", ticker)
            return []

        kind = _classify_ticker(ticker)
        if kind == "crypto":
            endpoint = f"{_BASE_URL}/crypto/candle"
        elif kind == "forex":
            endpoint = f"{_BASE_URL}/forex/candle"
        else:
            endpoint = f"{_BASE_URL}/stock/candle"

        params = {
            "symbol": finnhub_symbol,
            "resolution": "D",  # daily candles
            "from": int(start.timestamp()),
            "to": int(end.timestamp()),
        }

        try:
            response = await self._client.get(endpoint, params=params)
        except httpx.RequestError as exc:
            logger.warning("Finnhub: request error for %s: %s", ticker, exc)
            return []

        if response.status_code == 401:
            logger.error(
                "Finnhub: invalid API key (401). "
                "Check FINNHUB_API_KEY in ~/.clawquant/.env"
            )
            return []

        if response.status_code == 429:
            logger.warning(
                "Finnhub: rate limit hit (429) for %s. "
                "Free tier allows 60 req/min.",
                ticker,
            )
            return []

        if response.status_code != 200:
            logger.warning(
                "Finnhub: HTTP %d for %s (symbol=%s)",
                response.status_code, ticker, finnhub_symbol,
            )
            return []

        data = response.json()
        status = data.get("s", "")

        if status == "no_data":
            logger.debug(
                "Finnhub: no data for %s (symbol=%s) in requested range",
                ticker, finnhub_symbol,
            )
            return []

        if status != "ok":
            logger.warning(
                "Finnhub: unexpected status '%s' for %s (symbol=%s)",
                status, ticker, finnhub_symbol,
            )
            return []

        return self._parse_candle_response(ticker, data)

    def _parse_candle_response(self, ticker: str, data: dict) -> list[MarketData]:
        """Parse a Finnhub candle API response into MarketData objects."""
        timestamps: list[int] = data.get("t", [])
        opens: list[float] = data.get("o", [])
        highs: list[float] = data.get("h", [])
        lows: list[float] = data.get("l", [])
        closes: list[float] = data.get("c", [])
        volumes: list[float] = data.get("v", [])

        records: list[MarketData] = []
        for i, ts in enumerate(timestamps):
            close = closes[i] if i < len(closes) else None
            if close is None:
                continue

            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            records.append(
                MarketData(
                    ticker=ticker,
                    timestamp=dt,
                    available_at=dt,
                    open=opens[i] if i < len(opens) else None,
                    high=highs[i] if i < len(highs) else None,
                    low=lows[i] if i < len(lows) else None,
                    close=close,
                    volume=(
                        float(volumes[i])
                        if i < len(volumes) and volumes[i] is not None
                        else None
                    ),
                    source="finnhub",
                    data_type="price",
                )
            )

        return records

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
