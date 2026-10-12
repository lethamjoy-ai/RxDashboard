from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from rxdashboard.services.excel_service import workbook_bytes


def build_sample_sheets() -> dict[str, pd.DataFrame]:
    patients = [
        (f"P{i:03}", name, date(1958 + i, (i % 12) + 1, (i % 25) + 1), gender, diagnosis, allergy)
        for i, (name, gender, diagnosis, allergy) in enumerate([
            ("Avery Morgan", "F", "Hypertension", "Penicillin"), ("Jordan Lee", "M", "Type 2 diabetes", "None"),
            ("Taylor Brooks", "F", "Hyperlipidemia", "NSAID"), ("Casey Rivera", "M", "Asthma", "None"),
            ("Riley Patel", "F", "Hypothyroidism", "None"), ("Morgan Chen", "M", "Hypertension", "ACE inhibitor"),
            ("Quinn Davis", "F", "Type 2 diabetes", "None"), ("Drew Wilson", "M", "Asthma", "Penicillin"),
            ("Skyler Adams", "F", "Hyperlipidemia", "None"), ("Parker Kim", "M", "Hypertension", "None"),
        ], start=1)]
    patient_df = pd.DataFrame(patients, columns=["Patient ID", "Patient Name", "DOB", "Gender", "Diagnosis", "Allergies"])
    med_rows = []
    templates = [("Lisinopril", "10 mg", "10 mg", "Once daily"), ("Metformin", "500 mg", "500 mg", "Twice daily"),
                 ("Atorvastatin", "20 mg", "20 mg", "Once nightly"), ("Albuterol", "90 mcg", "2 puffs", "As needed"),
                 ("Levothyroxine", "50 mcg", "50 mcg", "Once daily"), ("Amlodipine", "5 mg", "5 mg", "Once daily")]
    for i, patient in enumerate(patients, 1):
        for j in range(1, 3):
            name, strength, dose, frequency = templates[(i + j) % len(templates)]
            start = date(2026, 5, 1) + timedelta(days=(i + j) * 2)
            end = date(2027, 5, 1) if i % 7 else date(2026, 8, 15)
            next_fill = date(2026, 10, 8 + ((i + j) % 20))
            status = "Discontinued" if i == 9 and j == 2 else "Active"
            med_rows.append((f"M{i:03}{j}", patient[0], name, strength, dose, frequency, start, end, 30, 30, date(2026, 9, 8), next_fill, max(0, 5 - j), status))
    med_df = pd.DataFrame(med_rows, columns=["Medication ID", "Patient ID", "Medication Name", "Strength", "Dose", "Frequency", "Start Date", "End Date", "Quantity Dispensed", "Days Supply", "Last Fill Date", "Next Expected Fill Date", "Refills Remaining", "Prescription Status"])
    events = []
    # Vary refill timing by medication so the analytics chart reflects a more
    # realistic workload instead of producing the same count every month.
    refill_month_patterns = (
        (0, 1),       # May, June
        (0, 2, 4),    # May, July, September
        (1, 3, 5),    # June, August, October
        (0, 1, 2, 4), # May, June, July, September
        (2, 3),       # July, August
        (1, 4, 5),    # June, September, October
    )
    event_id = 1
    for med_index, (_, med) in enumerate(med_df.iterrows()):
        event_schedule = [(0, "Medication started"), (5, "Medication restarted")]
        event_schedule.insert(2, (1, "Dose changed"))
        event_schedule.extend((month, "Medication refilled") for month in refill_month_patterns[med_index % len(refill_month_patterns)])
        for month, event_type in event_schedule:
            event_date = date(2026, 5 + month, min(28, 3 + int(med["Medication ID"][-1]) + month * 3))
            events.append((f"H{event_id:03}", med["Patient ID"], med["Medication ID"], event_date, event_type, med["Medication Name"], med["Dose"], 30, 30, "Synthetic demonstration event"))
            event_id += 1
    history_df = pd.DataFrame(events, columns=["History ID", "Patient ID", "Medication ID", "Event Date", "Event Type", "Medication Name", "Dose", "Quantity", "Days Supply", "Notes"])
    allergy_rows = [(p[0], p[5], "Drug class", "Documented allergy", "Moderate", date(2026, 5, 1)) for p in patients if p[5] != "None"]
    allergy_df = pd.DataFrame(allergy_rows, columns=["Patient ID", "Allergen", "Allergen Type", "Reaction", "Severity", "Recorded Date"])
    return {"Patients": patient_df, "Medications": med_df, "Medication History": history_df, "Allergies": allergy_df}


def main() -> None:
    output = Path(__file__).parents[1] / "data" / "sample_patients.xlsx"
    output.parent.mkdir(exist_ok=True)
    output.write_bytes(workbook_bytes(build_sample_sheets()))
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
