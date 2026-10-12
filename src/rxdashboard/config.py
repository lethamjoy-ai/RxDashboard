from __future__ import annotations

REFILL_SOON_DAYS = 7
WORKSHEETS = ("Patients", "Medications", "Medication History", "Allergies")
REQUIRED_COLUMNS = {
    "Patients": {"Patient ID", "Patient Name", "DOB", "Gender", "Diagnosis", "Allergies"},
    "Medications": {
        "Medication ID", "Patient ID", "Medication Name", "Strength", "Dose", "Frequency",
        "Start Date", "End Date", "Quantity Dispensed", "Days Supply", "Last Fill Date",
        "Next Expected Fill Date", "Refills Remaining", "Prescription Status",
    },
    "Medication History": {
        "History ID", "Patient ID", "Medication ID", "Event Date", "Event Type",
        "Medication Name", "Dose", "Quantity", "Days Supply", "Notes",
    },
    "Allergies": {"Patient ID", "Allergen", "Allergen Type", "Reaction", "Severity", "Recorded Date"},
}
