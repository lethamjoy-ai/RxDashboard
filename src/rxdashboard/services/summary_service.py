from __future__ import annotations

import pandas as pd


def patient_summary(patient: pd.Series, medications: pd.DataFrame, allergies: pd.DataFrame, history: pd.DataFrame) -> str:
    patient_id = patient["Patient ID"]
    patient_meds = medications[medications["Patient ID"] == patient_id]
    patient_allergies = allergies[allergies["Patient ID"] == patient_id]
    patient_history = history[history["Patient ID"] == patient_id]
    lines = [f"Patient Medication Summary: {patient['Patient Name']}", f"Patient ID: {patient_id}",
             f"DOB: {patient['DOB']} | Gender: {patient['Gender']}", f"Diagnosis: {patient['Diagnosis']}", "",
             "Documented allergies: " + (", ".join(patient_allergies["Allergen"].astype(str)) or "None recorded"), "",
             "Medications:"]
    for _, row in patient_meds.iterrows():
        lines.append(f"- {row['Medication Name']} {row['Strength']} ({row['Dose']}, {row['Frequency']}) — {row.get('Medication Status', row['Prescription Status'])}; next fill {row['Next Expected Fill Date']}")
    lines += ["", f"Medication history events in dataset: {len(patient_history)}",
              "Safety note: documented allergy indicators are informational and not clinical clearance."]
    return "\n".join(lines)
