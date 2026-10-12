from __future__ import annotations

from io import BytesIO

import pandas as pd

from rxdashboard.services.validation_service import normalize_sheets, validate_workbook


def read_workbook(source: str | bytes | BytesIO) -> tuple[dict[str, pd.DataFrame], list[str]]:
    try:
        sheets = pd.read_excel(source, sheet_name=None, engine="openpyxl")
    except Exception as exc:
        return {}, [f"Unable to read workbook: {exc}"]
    errors = validate_workbook(sheets)
    return normalize_sheets(sheets), errors


def workbook_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, index=False, sheet_name=name)
    return buffer.getvalue()
