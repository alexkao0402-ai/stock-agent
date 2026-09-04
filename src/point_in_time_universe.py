"""Point-in-time large-cap universe model for survivorship-safe research.

The model deliberately separates index membership from market-cap observations.
Every market-cap row carries an ``available_date`` so a backtest cannot use a
value before it would have been known. Companies are joined through a permanent
identifier rather than a reusable ticker symbol.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


MEMBERSHIP_COLUMNS = {
    "permanent_id", "ticker", "member_from", "member_to", "index_name"
}
MARKET_CAP_COLUMNS = {
    "permanent_id", "as_of_date", "available_date", "market_cap_usd"
}


class PointInTimeDataError(ValueError):
    """Raised when historical universe data is incomplete or could leak future data."""


@dataclass(frozen=True)
class PointInTimeUniverse:
    memberships: pd.DataFrame
    market_caps: pd.DataFrame

    @classmethod
    def from_csv(cls, membership_path: str | Path, market_cap_path: str | Path):
        return cls(pd.read_csv(membership_path), pd.read_csv(market_cap_path)).validated()

    def validated(self) -> "PointInTimeUniverse":
        memberships = self.memberships.copy()
        market_caps = self.market_caps.copy()
        missing_membership = MEMBERSHIP_COLUMNS.difference(memberships.columns)
        missing_caps = MARKET_CAP_COLUMNS.difference(market_caps.columns)
        if missing_membership:
            raise PointInTimeDataError(f"Missing membership columns: {sorted(missing_membership)}")
        if missing_caps:
            raise PointInTimeDataError(f"Missing market-cap columns: {sorted(missing_caps)}")

        for column in ("member_from", "member_to"):
            memberships[column] = pd.to_datetime(memberships[column], errors="coerce")
        for column in ("as_of_date", "available_date"):
            market_caps[column] = pd.to_datetime(market_caps[column], errors="coerce")
        market_caps["market_cap_usd"] = pd.to_numeric(market_caps["market_cap_usd"], errors="coerce")

        if memberships[["permanent_id", "ticker", "member_from", "index_name"]].isna().any().any():
            raise PointInTimeDataError("Membership rows contain missing required values")
        if market_caps[list(MARKET_CAP_COLUMNS)].isna().any().any():
            raise PointInTimeDataError("Market-cap rows contain missing or invalid values")
        if (memberships["member_to"].notna() & (memberships["member_to"] <= memberships["member_from"])).any():
            raise PointInTimeDataError("member_to must be later than member_from")
        if (market_caps["available_date"] < market_caps["as_of_date"]).any():
            raise PointInTimeDataError("available_date cannot precede as_of_date")
        if (market_caps["market_cap_usd"] <= 0).any():
            raise PointInTimeDataError("market_cap_usd must be positive")
        if market_caps.duplicated(["permanent_id", "as_of_date", "available_date"]).any():
            raise PointInTimeDataError("Duplicate market-cap observations")

        memberships = memberships.sort_values(["permanent_id", "member_from"]).reset_index(drop=True)
        for _, group in memberships.groupby("permanent_id"):
            previous_end = None
            for row in group.itertuples():
                if previous_end is None:
                    pass
                elif pd.isna(previous_end) or row.member_from < previous_end:
                    raise PointInTimeDataError("Overlapping membership intervals for one permanent_id")
                previous_end = row.member_to

        return PointInTimeUniverse(
            memberships=memberships,
            market_caps=market_caps.sort_values(["available_date", "as_of_date"]).reset_index(drop=True),
        )

    def top_n(self, signal_date, n: int = 10, index_name: str = "S&P 500") -> pd.DataFrame:
        """Return the top-N members using only information available by signal_date."""
        if n <= 0:
            raise ValueError("n must be positive")
        signal_date = pd.Timestamp(signal_date).normalize()
        memberships = self.memberships
        active = memberships[
            (memberships["index_name"] == index_name)
            & (memberships["member_from"] <= signal_date)
            & (memberships["member_to"].isna() | (signal_date < memberships["member_to"]))
        ].copy()
        known_caps = self.market_caps[
            (self.market_caps["available_date"] <= signal_date)
            & (self.market_caps["as_of_date"] <= signal_date)
        ].copy()
        known_caps = known_caps.sort_values(["available_date", "as_of_date"]).drop_duplicates(
            "permanent_id", keep="last"
        )
        ranked = active.merge(known_caps, on="permanent_id", how="inner", validate="one_to_one")
        if len(ranked) < n:
            raise PointInTimeDataError(
                f"Only {len(ranked)} eligible {index_name} members have known market cap on {signal_date.date()}; need {n}"
            )
        ranked = ranked.nlargest(n, "market_cap_usd").reset_index(drop=True)
        ranked.insert(0, "rank", range(1, len(ranked) + 1))
        ranked["signal_date"] = signal_date
        return ranked[[
            "signal_date", "rank", "permanent_id", "ticker", "market_cap_usd",
            "as_of_date", "available_date", "member_from", "member_to", "index_name",
        ]]
