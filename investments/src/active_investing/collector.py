from __future__ import annotations

import json
import logging
import math
import re
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
import truststore
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .io_utils import read_csv, write_csv_atomic

LOGGER = logging.getLogger(__name__)
SOURCE_URL = "https://companiesmarketcap.com/tech/largest-tech-companies-by-market-cap/"
YAHOO_QUOTE_URL = "https://finance.yahoo.com/quote/{ticker}/?guccounter=2"
YAHOO_CHART_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1y&interval=1d&events=history"
)
USER_AGENT = "Mozilla/5.0 (compatible; active-investing/0.1; personal research tool)"
TICKER_PATTERN = re.compile(r"^[A-Z0-9^][A-Z0-9.^=-]{0,23}$")
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
HTTP_CHUNK_SIZE = 64 * 1024

CSV_FIELDS = [
    "Source Rank",
    "Ticker",
    "Company Name",
    "Market Cap",
    "P/E Ratio",
    "P/B Ratio",
    "Revenue Growth",
    "Profit Margin",
    "Products and services",
    "Products and services score",
    "Undervalued score",
    "Volatility score",
    "Current Price",
    "52-Week High",
    "52-Week Low",
    "Annualized Volatility",
]
MANUAL_FIELDS = ("Products and services", "Products and services score")


@dataclass(frozen=True)
class CompanySeed:
    source_rank: int
    ticker: str
    name: str
    market_cap: int


@dataclass(frozen=True)
class HttpPayload:
    content: bytes
    encoding: str
    url: str

    @property
    def text(self) -> str:
        return self.content.decode(self.encoding, errors="replace")

    def json(self) -> Any:
        return json.loads(self.content)


def parse_top_companies(html: str, limit: int = 100) -> list[CompanySeed]:
    """Parse the CompaniesMarketCap technology table and validate each row."""
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")

    soup = BeautifulSoup(html, "html.parser")
    companies: list[CompanySeed] = []
    seen_tickers: set[str] = set()
    for row in soup.select("tbody tr"):
        rank_element = row.select_one(".rank-td")
        name_element = row.select_one(".company-name")
        ticker_element = row.select_one(".company-code")
        cells = row.find_all("td", recursive=False)
        if rank_element is None or name_element is None or ticker_element is None or len(cells) < 4:
            continue

        rank_text = rank_element.get("data-sort") or rank_element.get_text(strip=True)
        ticker = ticker_element.get_text(" ", strip=True).split()[-1].upper()
        name = name_element.get_text(" ", strip=True)
        market_cap_text = cells[3].get("data-sort")
        try:
            source_rank = int(str(rank_text))
            market_cap = int(str(market_cap_text))
        except (TypeError, ValueError):
            continue
        if source_rank < 1 or not name or not TICKER_PATTERN.fullmatch(ticker):
            continue
        if ticker in seen_tickers:
            continue

        companies.append(CompanySeed(source_rank, ticker, name, market_cap))
        seen_tickers.add(ticker)
        if len(companies) == limit:
            break

    if len(companies) != limit:
        raise ValueError(
            f"Expected {limit} valid companies in source table, found {len(companies)}"
        )
    return companies


def fetch_top_companies(limit: int = 100) -> list[CompanySeed]:
    """Download and parse the current top technology companies."""
    with _build_session() as session:
        response = _get(session, SOURCE_URL, accept="text/html")
    return parse_top_companies(response.text, limit)


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def calculate_price_scores(closes: Any) -> dict[str, float | None]:
    """Calculate transparent 0-100 undervaluation and volatility heuristics."""
    clean_closes = [number for value in closes if (number := _finite_number(value)) is not None]
    if len(clean_closes) < 30:
        return {
            "current_price": None,
            "year_high": None,
            "year_low": None,
            "annualized_volatility": None,
            "undervalued_score": None,
            "volatility_score": None,
        }

    current = clean_closes[-1]
    year_high = max(clean_closes)
    year_low = min(clean_closes)
    if current <= 0 or year_high <= 0 or year_low <= 0:
        raise ValueError("Price history contains non-positive prices")

    drawdown = max(0.0, (year_high - current) / year_high)
    price_range = year_high - year_low
    range_position = (year_high - current) / price_range if price_range > 0 else 0.0
    undervalued_score = 100 * (
        0.6 * min(drawdown / 0.30, 1.0) + 0.4 * min(max(range_position, 0.0), 1.0)
    )

    daily_returns = [
        (current_close / previous_close) - 1
        for previous_close, current_close in zip(clean_closes, clean_closes[1:], strict=False)
        if previous_close > 0
    ]
    annualized_volatility = statistics.stdev(daily_returns) * math.sqrt(252)
    volatility_score = 100 * min(max((annualized_volatility - 0.15) / 0.45, 0.0), 1.0)
    return {
        "current_price": current,
        "year_high": year_high,
        "year_low": year_low,
        "annualized_volatility": annualized_volatility,
        "undervalued_score": undervalued_score,
        "volatility_score": volatility_score,
    }


def _build_session() -> requests.Session:
    truststore.inject_into_ssl()
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def _get(session: requests.Session, url: str, accept: str) -> HttpPayload:
    with session.get(
        url,
        headers={"Accept": accept},
        timeout=(10, 30),
        stream=True,
    ) as response:
        response.raise_for_status()
        content_length = _finite_number(response.headers.get("Content-Length"))
        if content_length is not None and content_length > MAX_RESPONSE_BYTES:
            raise ValueError(f"Response exceeds the 5 MB safety limit: {url}")

        content = bytearray()
        for chunk in response.iter_content(chunk_size=HTTP_CHUNK_SIZE):
            content.extend(chunk)
            if len(content) > MAX_RESPONSE_BYTES:
                raise ValueError(f"Response exceeds the 5 MB safety limit: {url}")
        encoding = response.encoding or "utf-8"
        if encoding.lower() == "iso-8859-1":
            encoding = "utf-8"
        return HttpPayload(bytes(content), encoding, response.url)


def parse_quote_summary(html: str) -> dict[str, Any]:
    """Extract Yahoo's quote-summary object from its public quote page."""
    soup = BeautifulSoup(html, "html.parser")
    scripts = soup.find_all("script", attrs={"data-sveltekit-fetched": True})
    for script in scripts:
        if "quoteSummary" not in str(script.get("data-url", "")) or not script.string:
            continue
        try:
            envelope = json.loads(script.string)
            body = envelope.get("body")
            payload = json.loads(body) if isinstance(body, str) else body
            result = payload["quoteSummary"]["result"]
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
        if isinstance(result, list) and result and isinstance(result[0], dict):
            return result[0]
    raise ValueError("Yahoo quote page did not contain a valid quote-summary payload")


def _raw_metric(summary: dict[str, Any], module: str, name: str) -> Any:
    value = summary.get(module, {}).get(name)
    return value.get("raw") if isinstance(value, dict) else value


def _fetch_summary(session: requests.Session, ticker: str) -> dict[str, Any]:
    encoded_ticker = quote(ticker, safe="")
    response = _get(
        session,
        YAHOO_QUOTE_URL.format(ticker=encoded_ticker),
        accept="text/html",
    )
    return parse_quote_summary(response.text)


def _fetch_closes(session: requests.Session, ticker: str) -> list[float]:
    encoded_ticker = quote(ticker, safe="")
    response = _get(
        session,
        YAHOO_CHART_URL.format(ticker=encoded_ticker),
        accept="application/json",
    )
    try:
        result = response.json()["chart"]["result"][0]
        indicators = result["indicators"]
        adjusted = indicators.get("adjclose") or []
        values = adjusted[0]["adjclose"] if adjusted else indicators["quote"][0]["close"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
        raise ValueError(f"Yahoo returned invalid chart data for {ticker}") from error
    if not isinstance(values, list):
        raise ValueError(f"Yahoo returned invalid close prices for {ticker}")
    return values


def _fetch_financial_data(seed: CompanySeed) -> dict[str, object]:
    summary: dict[str, Any] = {}
    price_scores: dict[str, float | None] = {}
    with _build_session() as session:
        try:
            summary = _fetch_summary(session, seed.ticker)
        except (OSError, ValueError, requests.RequestException) as error:
            LOGGER.warning("Could not fetch fundamentals for %s: %s", seed.ticker, error)
        try:
            price_scores = calculate_price_scores(_fetch_closes(session, seed.ticker))
        except (OSError, ValueError, requests.RequestException) as error:
            LOGGER.warning("Could not fetch price history for %s: %s", seed.ticker, error)

    description = str(_raw_metric(summary, "summaryProfile", "longBusinessSummary") or "")
    description = " ".join(description.split())[:4_000]
    return {
        "Source Rank": seed.source_rank,
        "Ticker": seed.ticker,
        "Company Name": seed.name,
        "Market Cap": seed.market_cap,
        "P/E Ratio": _finite_number(_raw_metric(summary, "summaryDetail", "trailingPE")),
        "P/B Ratio": _finite_number(_raw_metric(summary, "defaultKeyStatistics", "priceToBook")),
        "Revenue Growth": _finite_number(_raw_metric(summary, "financialData", "revenueGrowth")),
        "Profit Margin": _finite_number(_raw_metric(summary, "financialData", "profitMargins")),
        "Products and services": description,
        "Undervalued score": price_scores.get("undervalued_score"),
        "Volatility score": price_scores.get("volatility_score"),
        "Current Price": price_scores.get("current_price"),
        "52-Week High": price_scores.get("year_high"),
        "52-Week Low": price_scores.get("year_low"),
        "Annualized Volatility": price_scores.get("annualized_volatility"),
    }


def load_manual_values(path: Path) -> dict[str, dict[str, str]]:
    """Load user-maintained fields from a previous collection, keyed by ticker."""
    if not path.exists():
        return {}
    rows = read_csv(path, {"Ticker", *MANUAL_FIELDS})
    values: dict[str, dict[str, str]] = {}
    for row in rows:
        ticker = row["Ticker"].strip().upper()
        if TICKER_PATTERN.fullmatch(ticker):
            score_text = row["Products and services score"].strip()
            score = _finite_number(score_text) if score_text else None
            if score_text and (score is None or not 0 <= score <= 100):
                raise ValueError(
                    f"Products and services score for {ticker} must be between 0 and 100"
                )
            values[ticker] = {
                "Products and services": row["Products and services"].strip(),
                "Products and services score": format(score, "g") if score is not None else "",
            }
    return values


def collect_records(
    seeds: list[CompanySeed],
    manual_values: dict[str, dict[str, str]],
    default_products_score: float = 50.0,
    workers: int = 4,
) -> list[dict[str, object]]:
    """Collect records concurrently while retaining stable source order and manual edits."""
    if not 0 <= default_products_score <= 100:
        raise ValueError("default products score must be between 0 and 100")
    if not 1 <= workers <= 16:
        raise ValueError("workers must be between 1 and 16")

    by_ticker: dict[str, dict[str, object]] = {}
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="finance") as executor:
        futures = {executor.submit(_fetch_financial_data, seed): seed for seed in seeds}
        for future in as_completed(futures):
            seed = futures[future]
            try:
                record = future.result()
            except Exception as error:
                LOGGER.warning("Could not collect %s: %s", seed.ticker, error)
                record = {
                    "Source Rank": seed.source_rank,
                    "Ticker": seed.ticker,
                    "Company Name": seed.name,
                    "Market Cap": seed.market_cap,
                }

            previous = manual_values.get(seed.ticker, {})
            if seed.ticker in manual_values:
                record["Products and services"] = previous.get("Products and services", "")
            previous_score = previous.get("Products and services score", "")
            record["Products and services score"] = previous_score or default_products_score
            by_ticker[seed.ticker] = record

    return [by_ticker[seed.ticker] for seed in seeds]


def collect_to_csv(
    output_path: Path,
    limit: int = 100,
    default_products_score: float = 50.0,
    workers: int = 4,
) -> list[dict[str, object]]:
    """Refresh the company data CSV, preserving its manual fields."""
    seeds = fetch_top_companies(limit)
    manual_values = load_manual_values(output_path)
    records = collect_records(seeds, manual_values, default_products_score, workers)
    required_metrics = ("P/E Ratio", "P/B Ratio", "Revenue Growth", "Profit Margin")
    usable_records = sum(
        all(record.get(metric) is not None for metric in required_metrics)
        and record.get("Undervalued score") is not None
        for record in records
    )
    if usable_records < math.ceil(len(records) / 2):
        raise ValueError(
            "Fewer than half of the companies have usable provider data; "
            "the existing CSV was not replaced"
        )
    write_csv_atomic(output_path, CSV_FIELDS, records)
    return records
