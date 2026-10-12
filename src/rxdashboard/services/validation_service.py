from __future__ import annotations

import pandas as pd

from rxdashboard.config import REQUIRED_COLUMNS, WORKSHEETS


def validate_workbook(sheets: dict[str, pd.DataFrame]) -> list[str]:
    errors: list[str] = []
    missing_sheets = [name for name in WORKSHEETS if name not in sheets]
    errors.extend(f"Missing worksheet: {name}" for name in missing_sheets)
    for name, required in REQUIRED_COLUMNS.items():
        if name not in sheets:
            continue
        missing = sorted(required - set(sheets[name].columns))
        if missing:
            errors.append(f"{name}: missing columns: {', '.join(missing)}")
    if errors:
        return errors

    patients = sheets["Patients"]
    meds = sheets["Medications"]
    history = sheets["Medication History"]
    allergies = sheets["Allergies"]
    for frame, column, label in ((patients, "Patient ID", "patient"), (meds, "Medication ID", "medication"),
                                 (history, "History ID", "history")):
        if frame[column].duplicated().any():
            errors.append(f"Duplicate {label} identifiers found")
    patient_ids = set(patients["Patient ID"].astype(str))
    med_ids = set(meds["Medication ID"].astype(str))
    if not set(meds["Patient ID"].astype(str)).issubset(patient_ids):
        errors.append("Medications contains an unknown Patient ID")
    if not set(history["Patient ID"].astype(str)).issubset(patient_ids):
        errors.append("Medication History contains an unknown Patient ID")
    if not set(history["Medication ID"].astype(str)).issubset(med_ids):
        errors.append("Medication History contains an unknown Medication ID")
    if not set(allergies["Patient ID"].astype(str)).issubset(patient_ids):
        errors.append("Allergies contains an unknown Patient ID")
    for name, columns in (("Patients", ["DOB"]), ("Medications", ["Start Date", "End Date", "Last Fill Date", "Next Expected Fill Date"]),
                          ("Medication History", ["Event Date"]), ("Allergies", ["Recorded Date"])):
        frame = sheets[name]
        for column in columns:
            if frame[column].notna().any() and pd.to_datetime(frame[column], errors="coerce").isna().any():
                errors.append(f"{name}.{column} contains invalid dates")
    for name, columns in (("Medications", ["Quantity Dispensed", "Days Supply", "Refills Remaining"]),
                          ("Medication History", ["Quantity", "Days Supply"])):
        frame = sheets[name]
        for column in columns:
            values = pd.to_numeric(frame[column], errors="coerce")
            if values.isna().any() or (values < 0).any():
                errors.append(f"{name}.{column} contains invalid or negative values")
    return errors


def normalize_sheets(sheets: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    normalized = {name: frame.copy() for name, frame in sheets.items()}
    date_columns = {
        "Patients": ["DOB"],
        "Medications": ["Start Date", "End Date", "Last Fill Date", "Next Expected Fill Date"],
        "Medication History": ["Event Date"],
        "Allergies": ["Recorded Date"],
    }
    for name, columns in date_columns.items():
        if name in normalized:
            for column in columns:
                normalized[name][column] = pd.to_datetime(normalized[name][column], errors="coerce").dt.date
    return normalized
