from datetime import date
import sys
import types

import pandas as pd
import pytest

from rxdashboard.app import paginate_records
from rxdashboard.services.allergy_service import allergy_indicator
from rxdashboard.services.medication_service import medication_status
from rxdashboard.services.refill_review import (
    GroqReviewError,
    PatientContext,
    RefillAIResponse,
    evaluate_refill_rules,
    request_ai_review,
    validate_ai_response,
)
from rxdashboard.services.validation_service import validate_workbook
from scripts.generate_sample_data import build_sample_sheets


def test_status_logic_is_deterministic():
    row = pd.Series({"Prescription Status": "Active", "End Date": date(2027, 1, 1), "Next Expected Fill Date": date(2026, 10, 10)})
    assert medication_status(row, date(2026, 10, 7)) == "Refill Soon"
    row["Prescription Status"] = "Discontinued"
    assert medication_status(row, date(2026, 10, 7)) == "Discontinued"


def test_allergy_mapping_does_not_guess_unknowns():
    assert allergy_indicator("Amoxicillin", ["Penicillin"]) == "Potential Conflict"
    assert allergy_indicator("Metformin", ["Penicillin"]) == "Not Evaluated"


def test_dashboard_pagination_returns_ten_records():
    records = pd.DataFrame({"id": range(25)})
    assert paginate_records(records, 0).shape[0] == 10
    assert paginate_records(records, 1).iloc[0]["id"] == 10
    assert paginate_records(records, 2).shape[0] == 5


def test_sample_refill_activity_varies_by_month():
    history = build_sample_sheets()["Medication History"]
    refill_counts = (
        history[history["Event Type"] == "Medication refilled"]
        .assign(Month=lambda frame: pd.to_datetime(frame["Event Date"]).dt.month)
        .groupby("Month")
        .size()
    )
    assert refill_counts.nunique() > 1


def test_validation_detects_broken_relationships():
    sheets = {
        "Patients": pd.DataFrame({"Patient ID": ["P1"], "Patient Name": ["A"], "DOB": [date(1990, 1, 1)], "Gender": ["F"], "Diagnosis": ["Asthma"], "Allergies": ["None"]}),
        "Medications": pd.DataFrame({"Medication ID": ["M1"], "Patient ID": ["P9"], "Medication Name": ["X"], "Strength": ["1"], "Dose": ["1"], "Frequency": ["daily"], "Start Date": [date(2026, 1, 1)], "End Date": [date(2027, 1, 1)], "Quantity Dispensed": [30], "Days Supply": [30], "Last Fill Date": [date(2026, 9, 1)], "Next Expected Fill Date": [date(2026, 10, 1)], "Refills Remaining": [1], "Prescription Status": ["Active"]}),
        "Medication History": pd.DataFrame(columns=["History ID", "Patient ID", "Medication ID", "Event Date", "Event Type", "Medication Name", "Dose", "Quantity", "Days Supply", "Notes"]),
        "Allergies": pd.DataFrame(columns=["Patient ID", "Allergen", "Allergen Type", "Reaction", "Severity", "Recorded Date"]),
    }
    assert any("unknown Patient ID" in error for error in validate_workbook(sheets))


def review_context(**overrides):
    medication = {
        "Medication Name": "Lisinopril", "Strength": "10 mg", "Dose": "10 mg",
        "Frequency": "Once daily", "Start Date": date(2026, 1, 1), "End Date": date(2027, 1, 1),
        "Last Fill Date": date(2026, 9, 1), "Next Expected Fill Date": date(2026, 10, 10),
        "Refills Remaining": 2, "Prescription Status": "Active",
    }
    medication.update(overrides)
    return PatientContext(patient_ref="SYNTHETIC-P1", diagnosis="Hypertension", documented_allergies=[], medication=medication, six_month_history=[])


def test_refill_rules_flag_expired_prescription_and_zero_refills():
    context = review_context(**{"End Date": date(2026, 10, 1), "Refills Remaining": 0})
    result = evaluate_refill_rules(context, date(2026, 10, 7))
    assert result.prescription_status == "Fail"
    assert result.refills_remaining == "Zero"
    assert result.administrative_status == "Review required"
    assert {"expired_prescription", "zero_refills_remaining"}.issubset(result.flags)


def test_refill_rules_flag_discontinued_and_missing_data():
    context = review_context(**{"Prescription Status": "Discontinued", "Next Expected Fill Date": None})
    context.medication["Dose"] = None
    result = evaluate_refill_rules(context, date(2026, 10, 7))
    assert "discontinued_medication" in result.flags
    assert "missing_required_information" in result.flags
    assert result.refill_timing == "Missing"


def test_unsupported_allergy_check_is_explicit():
    context = review_context(**{"Medication Name": "Unknown medication"})
    result = evaluate_refill_rules(context, date(2026, 10, 7))
    assert result.allergy_check == "Not Evaluated"
    assert "unsupported_allergy_check" in result.flags


def test_clean_rules_are_administratively_complete_only():
    context = review_context(**{"Next Expected Fill Date": date(2026, 11, 10)})
    result = evaluate_refill_rules(context, date(2026, 10, 7))
    assert result.administrative_status == "Administrative information complete"


def test_malformed_llm_output_is_rejected():
    with pytest.raises(GroqReviewError):
        validate_ai_response({"summary": "missing other required fields"})


def test_api_failure_is_safe(monkeypatch):
    class BrokenChatGroq:
        def __init__(self, **kwargs):
            raise TimeoutError("simulated timeout")

    monkeypatch.setitem(sys.modules, "langchain_groq", types.SimpleNamespace(ChatGroq=BrokenChatGroq))
    with pytest.raises(GroqReviewError, match="unavailable"):
        request_ai_review(review_context(), evaluate_refill_rules(review_context(), date(2026, 10, 7)), api_key="test-key")


def test_valid_structured_response_is_preserved():
    response = validate_ai_response({
        "summary": "Review the supplied administrative facts with an authorized clinician.",
        "supporting_evidence": ["Refill date is approaching."],
        "missing_information": [],
        "review_questions": ["Confirm the current prescription."],
        "administrative_review_status": "Review required",
    })
    assert isinstance(response, RefillAIResponse)


def test_unsafe_terms_in_any_llm_field_are_rejected():
    with pytest.raises(GroqReviewError):
        validate_ai_response({
            "summary": "The clinician should review this.",
            "supporting_evidence": [],
            "missing_information": [],
            "review_questions": ["Should the clinician approve this request?"],
            "administrative_review_status": "Clinician review required",
        })
