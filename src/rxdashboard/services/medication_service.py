from __future__ import annotations

from datetime import date

import pandas as pd

from rxdashboard.config import REFILL_SOON_DAYS

STATUSES = ("Active", "Refill Due", "Refill Soon", "Expired", "Discontinued", "Review Required")


def medication_status(row: pd.Series, as_of: date | None = None, soon_days: int = REFILL_SOON_DAYS) -> str:
    today = as_of or date.today()
    prescription_status = str(row.get("Prescription Status", "")).strip().lower()
    if prescription_status == "discontinued":
        return "Discontinued"
    end_date = row.get("End Date")
    if pd.notna(end_date) and end_date < today:
        return "Expired"
    next_fill = row.get("Next Expected Fill Date")
    if pd.isna(next_fill):
        return "Review Required"
    days = (next_fill - today).days
    if days <= 0:
        return "Refill Due"
    if days <= soon_days:
        return "Refill Soon"
    return "Active"


def enrich_medications(medications: pd.DataFrame, as_of: date | None = None) -> pd.DataFrame:
    result = medications.copy()
    result["Medication Status"] = result.apply(medication_status, axis=1, as_of=as_of)
    return result
