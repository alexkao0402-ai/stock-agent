"""Free point-in-time inputs for the frozen V12 forward paper test.

Yahoo Finance supplies a current market-cap screen and price history.  Nasdaq's
symbol directory verifies that a security is currently listed and is not marked
as an ETF or a test issue.  SEC CIK and incorporation data provide a stable
company identifier, allow multiple share classes to be consolidated, and remove
non-US incorporated issuers.

This module intentionally fails closed.  It never falls back to the old fixed
ten-stock universe when a required source is incomplete.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import requests
import yfinance as yf

from src.trading_calendar import is_month_end_session


NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
DEFAULT_SEC_USER_AGENT = "stock-agent/1.0 https://github.com/alexkao0402-ai/stock-agent"
LIVE_INPUT_DIR = Path("live_forward_inputs")

US_JURISDICTIONS = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA",
    "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY",
    "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX",
    "UT", "VT", "VA", "WA", "WV", "WI", "WY", "PR", "VI", "GU", "AS",
    "MP",
}

NON_COMMON_NAME_MARKERS = (
    " warrant", " warrants", " right", " rights", " unit", " units",
    " preferred", " preference", " depositary share", " notes due",
)


class LiveDataError(RuntimeError):
    """Raised when a live input cannot meet the frozen data contract."""


def yahoo_symbol(symbol: str) -> str:
    """Normalize exchange punctuation to Yahoo's class-symbol convention."""
    return str(symbol).strip().upper().replace(".", "-").replace("/", "-")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _response_text(
    url: str,
    *,
    session=requests,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
    retries: int = 2,
) -> str:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = session.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(1.0 * (attempt + 1))
    raise LiveDataError(f"Unable to retrieve {url}: {last_error}")


def _looks_non_common(name: str) -> bool:
    normalized = f" {str(name).lower()} "
    return any(marker in normalized for marker in NON_COMMON_NAME_MARKERS)


def parse_nasdaq_directories(nasdaq_text: str, other_text: str) -> dict[str, dict[str, Any]]:
    """Parse Nasdaq's two current symbol files and keep common-stock candidates."""
    listed: dict[str, dict[str, Any]] = {}

    for row in csv.DictReader(io.StringIO(nasdaq_text), delimiter="|"):
        raw_symbol = str(row.get("Symbol") or "").strip()
        if not raw_symbol or raw_symbol.startswith("File Creation Time"):
            continue
        if row.get("Test Issue") != "N" or row.get("ETF") != "N":
            continue
        if row.get("Financial Status") not in ("", "N", None):
            continue
        name = str(row.get("Security Name") or "").strip()
        if _looks_non_common(name):
            continue
        symbol = yahoo_symbol(raw_symbol)
        listed[symbol] = {
            "symbol": symbol,
            "exchange_symbol": raw_symbol,
            "security_name": name,
            "exchange": "NASDAQ",
            "directory_source": "nasdaqlisted.txt",
        }

    for row in csv.DictReader(io.StringIO(other_text), delimiter="|"):
        raw_symbol = str(row.get("ACT Symbol") or "").strip()
        if not raw_symbol or raw_symbol.startswith("File Creation Time"):
            continue
        if row.get("Test Issue") != "N" or row.get("ETF") != "N":
            continue
        name = str(row.get("Security Name") or "").strip()
        if _looks_non_common(name):
            continue
        symbol = yahoo_symbol(raw_symbol)
        listed[symbol] = {
            "symbol": symbol,
            "exchange_symbol": raw_symbol,
            "security_name": name,
            "exchange": str(row.get("Exchange") or "").strip(),
            "directory_source": "otherlisted.txt",
        }
    return listed


def parse_sec_ticker_exchange(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return a Yahoo-normalized ticker to SEC CIK mapping."""
    fields = payload.get("fields")
    rows = payload.get("data")
    if not isinstance(fields, list) or not isinstance(rows, list):
        raise LiveDataError("SEC ticker mapping has an unexpected schema")
    mapping: dict[str, dict[str, Any]] = {}
    for values in rows:
        item = dict(zip(fields, values))
        ticker = yahoo_symbol(item.get("ticker", ""))
        cik = item.get("cik")
        if not ticker or cik in (None, ""):
            continue
        mapping[ticker] = {
            "cik": int(cik),
            "sec_name": str(item.get("name") or ""),
            "sec_exchange": str(item.get("exchange") or ""),
        }
    return mapping


def fetch_reference_data(*, session=requests) -> tuple[dict, dict, dict[str, str]]:
    """Fetch Nasdaq listings and, when reachable, SEC ticker-to-CIK data."""
    nasdaq_text = _response_text(NASDAQ_LISTED_URL, session=session)
    other_text = _response_text(OTHER_LISTED_URL, session=session)
    hashes = {
        "nasdaq_listed_sha256": _sha256_bytes(nasdaq_text.encode("utf-8")),
        "other_listed_sha256": _sha256_bytes(other_text.encode("utf-8")),
    }
    sec_mapping: dict[str, dict[str, Any]] = {}
    try:
        sec_text = _response_text(
            SEC_TICKERS_URL,
            session=session,
            headers={"User-Agent": DEFAULT_SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"},
        )
        sec_payload = json.loads(sec_text)
        sec_mapping = parse_sec_ticker_exchange(sec_payload)
        hashes["sec_tickers_sha256"] = _sha256_bytes(sec_text.encode("utf-8"))
        hashes["sec_tickers_status"] = "available"
    except (LiveDataError, json.JSONDecodeError):
        hashes["sec_tickers_status"] = "unavailable_fallback_to_yahoo_profile"
    return (
        parse_nasdaq_directories(nasdaq_text, other_text),
        sec_mapping,
        hashes,
    )


def fetch_yahoo_market_cap_candidates(candidate_count: int = 100) -> list[dict[str, Any]]:
    """Return a descending US-region equity screen from Yahoo Finance."""
    if not 20 <= candidate_count <= 250:
        raise ValueError("candidate_count must be between 20 and 250")
    query = yf.EquityQuery(
        "and",
        [
            yf.EquityQuery("eq", ["region", "us"]),
            yf.EquityQuery("gte", ["intradaymarketcap", 1_000_000_000]),
        ],
    )
    try:
        result = yf.screen(
            query,
            size=candidate_count,
            sortField="intradaymarketcap",
            sortAsc=False,
        )
    except Exception as exc:
        raise LiveDataError(f"Yahoo market-cap screen failed: {exc}") from exc

    quotes = result.get("quotes", []) if isinstance(result, dict) else []
    candidates = []
    for quote in quotes:
        symbol = yahoo_symbol(quote.get("symbol", ""))
        market_cap = quote.get("marketCap") or quote.get("intradaymarketcap")
        try:
            market_cap = float(market_cap)
        except (TypeError, ValueError):
            continue
        if not symbol or market_cap <= 0:
            continue
        candidates.append(
            {
                "symbol": symbol,
                "name": str(quote.get("longName") or quote.get("shortName") or symbol),
                "market_cap": market_cap,
                "regular_market_price": quote.get("regularMarketPrice"),
                "regular_market_volume": quote.get("regularMarketVolume"),
                "average_daily_volume_3m": quote.get("averageDailyVolume3Month"),
                "shares_outstanding": quote.get("sharesOutstanding"),
                "market_state": quote.get("marketState"),
                "quote_type": quote.get("quoteType"),
                "yahoo_exchange": quote.get("exchange"),
                "message_board_id": quote.get("messageBoardId"),
                "first_trade_date_ms": quote.get("firstTradeDateMilliseconds"),
            }
        )
    candidates.sort(key=lambda row: row["market_cap"], reverse=True)
    if len(candidates) < 20:
        raise LiveDataError(f"Yahoo returned only {len(candidates)} usable market-cap candidates")
    return candidates


def fetch_sec_incorporation(
    cik: int,
    *,
    session=requests,
    user_agent: str = DEFAULT_SEC_USER_AGENT,
) -> dict[str, str]:
    """Fetch the SEC incorporation code used to exclude foreign issuers."""
    text = _response_text(
        SEC_SUBMISSIONS_URL.format(cik=int(cik)),
        session=session,
        headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
    )
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LiveDataError(f"SEC submissions response for CIK {cik} is not valid JSON") from exc
    return {
        "state_of_incorporation": str(payload.get("stateOfIncorporation") or "").upper(),
        "entity_name": str(payload.get("name") or ""),
    }


def fetch_yahoo_company_profile(symbol: str) -> dict[str, str]:
    """Fetch company identity and domicile when SEC blocks the running host."""
    try:
        payload = yf.Ticker(symbol).get_info()
    except Exception as exc:
        raise LiveDataError(f"Yahoo company profile failed for {symbol}: {exc}") from exc
    if not isinstance(payload, dict):
        raise LiveDataError(f"Yahoo company profile has an unexpected schema for {symbol}")
    return {
        "message_board_id": str(payload.get("messageBoardId") or ""),
        "country": str(payload.get("country") or ""),
        "state": str(payload.get("state") or ""),
        "entity_name": str(payload.get("longName") or payload.get("shortName") or ""),
    }


def _is_us_country(value: str) -> bool:
    return str(value).strip().casefold() in {
        "united states", "united states of america", "usa", "u.s.", "us"
    }


def rank_us_companies(
    candidates: list[dict[str, Any]],
    listed: dict[str, dict[str, Any]],
    sec_mapping: dict[str, dict[str, Any]],
    incorporation_lookup: Callable[[int], dict[str, str]],
    *,
    profile_lookup: Callable[[str], dict[str, str]] | None = None,
    top_n: int = 10,
    eligibility_buffer: int = 5,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Validate candidates and rank unique US companies by issuer-level market cap."""
    if top_n <= 0 or eligibility_buffer < 0:
        raise ValueError("top_n must be positive and eligibility_buffer cannot be negative")
    needed = top_n + eligibility_buffer
    companies: dict[str, dict[str, Any]] = {}
    exclusions: list[dict[str, Any]] = []
    incorporation_cache: dict[int, dict[str, str]] = {}
    processed = 0

    for candidate in sorted(candidates, key=lambda row: row["market_cap"], reverse=True):
        processed += 1
        symbol = yahoo_symbol(candidate.get("symbol", ""))
        reason = None
        if symbol not in listed:
            reason = "not_current_non_etf_nasdaq_directory_security"
        if reason is not None:
            exclusions.append({"symbol": symbol, "reason": reason})
            continue

        sec = sec_mapping.get(symbol)
        cik = int(sec["cik"]) if sec is not None else None
        stable_company_id = ""
        company_name = str(candidate.get("name") or symbol)
        jurisdiction = ""
        identity_source = ""

        if cik is not None:
            try:
                if cik not in incorporation_cache:
                    incorporation_cache[cik] = incorporation_lookup(cik)
                incorporation = incorporation_cache[cik]
            except LiveDataError:
                incorporation = {}
            jurisdiction = str(incorporation.get("state_of_incorporation") or "").upper()
            if jurisdiction:
                if jurisdiction not in US_JURISDICTIONS:
                    exclusions.append(
                        {"symbol": symbol, "reason": "not_us_incorporated", "jurisdiction": jurisdiction}
                    )
                    continue
                stable_company_id = f"SEC-CIK-{cik:010d}"
                company_name = incorporation.get("entity_name") or sec.get("sec_name") or company_name
                identity_source = "SEC_CIK"

        if not stable_company_id and profile_lookup is not None:
            try:
                profile = profile_lookup(symbol)
            except LiveDataError:
                profile = {}
            country = str(profile.get("country") or "")
            if country and not _is_us_country(country):
                exclusions.append(
                    {"symbol": symbol, "reason": "not_us_incorporated", "jurisdiction": country}
                )
                continue
            message_board_id = str(
                profile.get("message_board_id") or candidate.get("message_board_id") or ""
            )
            if country and message_board_id:
                stable_company_id = (
                    f"SEC-CIK-{cik:010d}" if cik is not None else f"YAHOO-MBID-{message_board_id}"
                )
                company_name = profile.get("entity_name") or company_name
                jurisdiction = str(profile.get("state") or country)
                identity_source = (
                    "SEC_CIK_YAHOO_DOMICILE_FALLBACK"
                    if cik is not None
                    else "YAHOO_PROFILE_FALLBACK"
                )

        if not stable_company_id:
            exclusions.append({"symbol": symbol, "reason": "missing_validated_company_identity"})
            continue

        volume = candidate.get("average_daily_volume_3m") or candidate.get("regular_market_volume") or 0
        try:
            volume = float(volume)
        except (TypeError, ValueError):
            volume = 0.0
        try:
            class_market_cap = float(candidate.get("shares_outstanding")) * float(
                candidate.get("regular_market_price")
            )
        except (TypeError, ValueError):
            class_market_cap = 0.0
        current = companies.get(stable_company_id)
        security = {
            "ticker": symbol,
            "stable_security_id": f"{stable_company_id}:{symbol}",
            "market_cap": float(candidate["market_cap"]),
            "average_daily_volume_3m": volume,
            "class_market_cap_estimate": class_market_cap,
            "exchange": listed[symbol]["exchange"],
            "first_trade_date_ms": candidate.get("first_trade_date_ms"),
        }
        if current is None:
            companies[stable_company_id] = {
                "stable_company_id": stable_company_id,
                "cik": cik,
                "company_name": company_name,
                "state_of_incorporation": jurisdiction,
                "company_identity_source": identity_source,
                "company_market_cap": float(candidate["market_cap"]),
                "representative": security,
                "share_classes": [security],
                "market_cap_method": "max_yahoo_issuer_market_cap_by_stable_company_id",
            }
        else:
            current["share_classes"].append(security)
            current["company_market_cap"] = max(current["company_market_cap"], security["market_cap"])
            challenger_key = (
                security["class_market_cap_estimate"], security["average_daily_volume_3m"]
            )
            current_key = (
                current["representative"]["class_market_cap_estimate"],
                current["representative"]["average_daily_volume_3m"],
            )
            if challenger_key > current_key:
                current["representative"] = security

        if len(companies) >= needed:
            break

    if len(companies) < needed:
        raise LiveDataError(
            f"Only {len(companies)} validated US companies were found; need at least {needed}"
        )

    ranked = sorted(companies.values(), key=lambda row: row["company_market_cap"], reverse=True)
    selected = []
    for rank, company in enumerate(ranked[:top_n], start=1):
        representative = company["representative"]
        selected.append(
            {
                "market_cap_rank": rank,
                "stable_company_id": company["stable_company_id"],
                "stable_security_id": representative["stable_security_id"],
                "ticker": representative["ticker"],
                "company_name": company["company_name"],
                "state_of_incorporation": company["state_of_incorporation"],
                "company_market_cap": company["company_market_cap"],
                "share_classes": sorted(item["ticker"] for item in company["share_classes"]),
                "market_cap_method": company["market_cap_method"],
                "company_identity_source": company["company_identity_source"],
                "first_trade_date_ms": representative.get("first_trade_date_ms"),
                "us_common_stock_flag": True,
            }
        )
    coverage = {
        "yahoo_candidates": len(candidates),
        "candidates_processed": processed,
        "validated_us_companies": len(companies),
        "selected_companies": len(selected),
        "excluded_candidates": len(exclusions),
    }
    return selected, exclusions, coverage


def fetch_adjusted_and_raw_prices(symbols: list[str], period: str = "2y") -> pd.DataFrame:
    """Fetch raw opens and adjusted closes needed by V12 signal and execution logic."""
    rows = []
    for symbol in symbols:
        try:
            frame = yf.download(
                symbol,
                period=period,
                auto_adjust=False,
                actions=True,
                progress=False,
                threads=False,
            )
        except Exception as exc:
            raise LiveDataError(f"Yahoo price download failed for {symbol}: {exc}") from exc
        if frame.empty:
            raise LiveDataError(f"Yahoo price history is empty for {symbol}")
        if isinstance(frame.columns, pd.MultiIndex):
            frame.columns = frame.columns.get_level_values(0)
        required = {"Open", "Close", "Adj Close"}
        if not required.issubset(frame.columns):
            raise LiveDataError(f"Yahoo price history for {symbol} is missing {sorted(required - set(frame.columns))}")
        normalized = frame.reset_index().rename(columns={
            "Adj Close": "adjusted_close",
            "Stock Splits": "stock_split",
            "Dividends": "dividend",
        })
        date_column = "Date" if "Date" in normalized.columns else normalized.columns[0]
        for values in normalized.to_dict(orient="records"):
            trade_date = pd.Timestamp(values[date_column]).date().isoformat()
            raw_close = float(values["Close"])
            adjusted_close = float(values["adjusted_close"])
            rows.append(
                {
                    "ticker": symbol,
                    "trade_date": trade_date,
                    "open": float(values["Open"]),
                    "close": raw_close,
                    "adjusted_close": adjusted_close,
                    "total_return_or_corporate_action_adjustment": (
                        adjusted_close / raw_close if raw_close else None
                    ),
                    "dividend": float(values.get("dividend", 0.0) or 0.0),
                    "stock_split": float(values.get("stock_split", 0.0) or 0.0),
                }
            )
    result = pd.DataFrame(rows).sort_values(["ticker", "trade_date"]).reset_index(drop=True)
    return result


def annotate_history_coverage(
    selected: list[dict[str, Any]],
    prices: pd.DataFrame,
    signal_date: str,
    *,
    minimum_rows: int = 253,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Mark genuine new listings ineligible and reject unexplained price gaps."""
    counts = prices.groupby("ticker")["trade_date"].nunique()
    if int(counts.get("SPY", 0)) < minimum_rows:
        raise LiveDataError(
            f"SPY has fewer than {minimum_rows} historical rows; market-regime input is incomplete"
        )
    signal_timestamp = pd.Timestamp(signal_date)
    annotated = []
    insufficient_history = []
    for original in selected:
        row = dict(original)
        history_rows = int(counts.get(row["ticker"], 0))
        row["history_rows"] = history_rows
        if history_rows >= minimum_rows:
            row["history_status"] = "SUFFICIENT_FOR_V12"
        else:
            first_trade_ms = row.get("first_trade_date_ms")
            if first_trade_ms in (None, ""):
                raise LiveDataError(
                    f"{row['ticker']} has only {history_rows} rows and no first-trade date to verify an IPO history gap"
                )
            first_trade_date = pd.to_datetime(
                first_trade_ms, unit="ms", utc=True
            ).tz_localize(None).normalize()
            if first_trade_date < signal_timestamp - pd.Timedelta(days=450):
                raise LiveDataError(
                    f"{row['ticker']} has only {history_rows} rows despite an older listing date; price coverage is incomplete"
                )
            row["history_status"] = "INSUFFICIENT_BY_DESIGN_V12_INELIGIBLE"
            insufficient_history.append(row["ticker"])
        annotated.append(row)
    return annotated, insufficient_history


def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def write_immutable_live_inputs(
    signal_date: str,
    selected: list[dict[str, Any]],
    prices: pd.DataFrame,
    *,
    source_hashes: dict[str, str],
    exclusions: list[dict[str, Any]],
    coverage: dict[str, int],
    directory: str | Path = LIVE_INPUT_DIR,
    captured_at: str | None = None,
) -> tuple[Path, bool]:
    """Write one append-only V12 input bundle and its SHA-256 manifest."""
    captured_at = captured_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    root = Path(directory) / signal_date
    manifest_path = root / "manifest.json"
    if manifest_path.exists():
        return root, False
    root.mkdir(parents=True, exist_ok=True)

    universe_rows = []
    security_ids = {row["ticker"]: row["stable_security_id"] for row in selected}
    for row in selected:
        universe_rows.append(
            {
                "signal_date": signal_date,
                "stable_company_id": row["stable_company_id"],
                "stable_security_id": row["stable_security_id"],
                "ticker": row["ticker"],
                "us_common_stock_flag": True,
                "company_market_cap": row["company_market_cap"],
                "market_cap_rank": row["market_cap_rank"],
                "history_rows": row.get("history_rows"),
                "history_status": row.get("history_status"),
                "source_timestamp": captured_at,
            }
        )
    universe = pd.DataFrame(universe_rows)
    prices = prices.copy()
    unknown_tickers = set(prices["ticker"].dropna().astype(str)) - set(security_ids) - {"SPY", "QQQ"}
    if unknown_tickers:
        raise LiveDataError(
            f"Price rows contain unmapped securities: {', '.join(sorted(unknown_tickers))}"
        )
    prices["stable_security_id"] = prices["ticker"].map(security_ids)
    prices.loc[prices["ticker"].eq("SPY"), "stable_security_id"] = "BENCHMARK:SPY"
    prices.loc[prices["ticker"].eq("QQQ"), "stable_security_id"] = "BENCHMARK:QQQ"
    prices["source_timestamp"] = captured_at
    prices = prices[[
        "stable_security_id", "ticker", "trade_date", "open", "close", "adjusted_close",
        "total_return_or_corporate_action_adjustment", "dividend", "stock_split", "source_timestamp",
    ]]

    universe_path = root / "monthly_universe.csv"
    prices_path = root / "daily_prices.csv"
    details_path = root / "selection_details.json"
    universe.to_csv(universe_path, index=False, encoding="utf-8")
    prices.to_csv(prices_path, index=False, encoding="utf-8")
    details = {
        "schema_version": 1,
        "signal_date": signal_date,
        "captured_at": captured_at,
        "provider_policy": "Yahoo Finance + Nasdaq symbol directory + SEC EDGAR",
        "selection": selected,
        "exclusions": exclusions,
        "coverage": coverage,
        "source_hashes": source_hashes,
    }
    details_path.write_bytes(_canonical_json_bytes(details))

    manifest = {
        "schema_version": 1,
        "signal_date": signal_date,
        "captured_at": captured_at,
        "files": {
            path.name: _sha256_bytes(path.read_bytes())
            for path in (universe_path, prices_path, details_path)
        },
        "immutability": "Files for an existing signal_date are never overwritten",
    }
    manifest_path.write_bytes(_canonical_json_bytes(manifest))
    return root, True


def capture_v12_live_inputs(
    *,
    candidate_count: int = 100,
    top_n: int = 10,
    directory: str | Path = LIVE_INPUT_DIR,
    session=requests,
    sec_user_agent: str = DEFAULT_SEC_USER_AGENT,
) -> tuple[Path, bool, dict[str, Any]]:
    """Capture and archive the free live inputs required by frozen V12."""
    candidates = fetch_yahoo_market_cap_candidates(candidate_count)
    if any(str(row.get("market_state") or "").upper() == "REGULAR" for row in candidates[:20]):
        raise LiveDataError("Capture aborted while the US regular session is open")
    listed, sec_mapping, source_hashes = fetch_reference_data(session=session)
    incorporation_cache: dict[int, dict[str, str]] = {}
    profile_cache: dict[str, dict[str, str]] = {}
    sec_submissions_available = True

    def lookup(cik: int) -> dict[str, str]:
        nonlocal sec_submissions_available
        if not sec_submissions_available:
            raise LiveDataError("SEC submissions unavailable for this capture")
        if cik not in incorporation_cache:
            try:
                incorporation_cache[cik] = fetch_sec_incorporation(
                    cik, session=session, user_agent=sec_user_agent
                )
                source_hashes["sec_submissions_status"] = "available"
            except LiveDataError:
                sec_submissions_available = False
                source_hashes["sec_submissions_status"] = "unavailable_fallback_to_yahoo_profile"
                raise
            time.sleep(0.12)  # Stay below the SEC's published fair-access ceiling.
        return incorporation_cache[cik]

    def profile_lookup(symbol: str) -> dict[str, str]:
        if symbol not in profile_cache:
            profile_cache[symbol] = fetch_yahoo_company_profile(symbol)
            time.sleep(0.10)
        return profile_cache[symbol]

    selected, exclusions, coverage = rank_us_companies(
        candidates,
        listed,
        sec_mapping,
        lookup,
        profile_lookup=profile_lookup,
        top_n=top_n,
    )
    tickers = [row["ticker"] for row in selected]
    prices = fetch_adjusted_and_raw_prices([*tickers, "SPY", "QQQ"])
    latest_dates = prices.groupby("ticker")["trade_date"].max()
    if latest_dates.nunique() != 1:
        raise LiveDataError("Selected securities do not share one latest completed trading date")
    signal_date = str(latest_dates.iloc[0])
    if not is_month_end_session(signal_date):
        raise LiveDataError(
            f"Capture aborted because {signal_date} is not the final business day of the month"
        )
    prices = prices[prices["trade_date"] <= signal_date].copy()
    selected, insufficient_history = annotate_history_coverage(selected, prices, signal_date)
    coverage["insufficient_history_companies"] = len(insufficient_history)
    source_hashes["yahoo_candidates_sha256"] = _sha256_bytes(
        _canonical_json_bytes({"candidates": candidates})
    )
    root, created = write_immutable_live_inputs(
        signal_date,
        selected,
        prices,
        source_hashes=source_hashes,
        exclusions=exclusions,
        coverage=coverage,
        directory=directory,
    )
    return root, created, {
        "signal_date": signal_date,
        "selected": selected,
        "coverage": coverage,
    }
