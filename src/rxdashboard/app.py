from __future__ import annotations

import sys
from datetime import date
from html import escape
from math import ceil
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from rxdashboard.services.excel_service import read_workbook, workbook_bytes
from rxdashboard.services.medication_service import STATUSES, enrich_medications
from rxdashboard.services.refill_review import (
    GroqReviewError,
    RefillAIResponse,
    evaluate_refill_rules,
    prepare_patient_context,
    request_ai_review,
)
from rxdashboard.services.summary_service import patient_summary

ROOT = Path(__file__).parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.generate_sample_data import build_sample_sheets


@st.cache_data
def load_default() -> dict[str, pd.DataFrame]:
    return build_sample_sheets()


def styled_header() -> None:
    st.markdown("""<style>
    .stApp { background: #f5f8fb; }
    .main { background: #f5f8fb; }
    [data-testid="stSidebar"] { background: #eaf1f7; border-right: 1px solid #d5e1eb; }
    [data-baseweb="tab-list"] { gap: 8px; border-bottom: 1px solid #cbd9e5; }
    [data-baseweb="tab"] { color: #506477; }
    [aria-selected="true"] { color: #25628a !important; border-bottom-color: #5b9bd5 !important; }
    [data-testid="stExpander"] { border: 1px solid #d7e2ec; background: #fbfdff; }
    [data-testid="stAlert"] { border-radius: 10px; }
    [data-testid="stMetric"] {
        background: #ffffff;
        border: 1px solid #cbddea;
        padding: 14px;
        border-radius: 12px;
        color: #234b63 !important;
    }
    [data-testid="stMetricLabel"],
    [data-testid="stMetricLabel"] p,
    [data-testid="stMetricValue"],
    [data-testid="stMetricValue"] div,
    [data-testid="stMetricDelta"] {
        color: #234b63 !important;
        -webkit-text-fill-color: #234b63 !important;
    }
    .empty-state-table {
        width: 100%;
        overflow-x: auto;
        border: 1px solid #cbd9e5;
        border-radius: 6px;
    }
    .empty-state-table table {
        width: 100%;
        border-collapse: collapse;
        color: #334e68;
        font-size: 14px;
    }
    .empty-state-table th {
        padding: 10px 8px;
        text-align: left;
        white-space: nowrap;
        background: #b8d4e8;
        border-right: 1px solid #cbd9e5;
        border-bottom: 1px solid #cbd9e5;
    }
    .empty-state-table td {
        height: 46px;
        text-align: center;
        color: #617487;
        background: #ffffff;
    }
    .history-feed-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
    }
    .history-event {
        padding: 12px 14px;
        border: 1px solid #cbd9e5;
        border-left: 4px solid #6aaed6;
        border-radius: 8px;
        background: #ffffff;
    }
    .history-event-date { display: inline-block; width: 42%; color: #34759e; font-weight: 600; }
    .history-event-type { display: inline-block; width: 58%; color: #263f52; font-weight: 600; }
    .history-event-details { color: #40596d; }
    .history-event-notes { color: #718394; font-size: 0.9em; margin-top: 4px; }
    @media (max-width: 900px) {
        .history-feed-grid { grid-template-columns: 1fr; }
    }
    [data-testid="stHeading"] h1,
    [data-testid="stHeading"] h2,
    [data-testid="stHeading"] h3,
    [data-testid="stHeading"] h4,
    [data-testid="stMarkdownContainer"] h1,
    [data-testid="stMarkdownContainer"] h2,
    [data-testid="stMarkdownContainer"] h3,
    [data-testid="stMarkdownContainer"] h4 {
        color: #234b63;
        background: #b8d4e8;
        border-left: 4px solid #4f81bd;
        border-radius: 6px;
        padding: 0.3rem 0.65rem;
    }
    .review-rule-table {
        width: 100%;
        border-collapse: collapse;
        border: 1px solid #b3c9da;
        border-radius: 8px;
        overflow: hidden;
        background: #ffffff;
        color: #334e68;
        margin: 0.25rem 0 0.75rem 0;
    }
    .review-rule-table th {
        background: #b8d4e8;
        color: #1f4e79;
        font-weight: 700;
        text-align: left;
        padding: 0.55rem 0.7rem;
        border-bottom: 1px solid #8fb1ca;
    }
    .review-rule-table td {
        padding: 0.5rem 0.7rem;
        border-bottom: 1px solid #dce7ef;
    }
    .review-rule-table tr:last-child td { border-bottom: 0; }
    [data-testid="stDataFrame"] {
        border: 1px solid #cbd9e5;
        border-radius: 8px;
        overflow: hidden;
    }
    </style>""", unsafe_allow_html=True)


def filtered_records(sheets: dict[str, pd.DataFrame], as_of: date, filters: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    patients = sheets["Patients"].copy()
    meds = enrich_medications(sheets["Medications"], as_of)
    merged = meds.merge(patients, on="Patient ID", how="left")
    merged["Age"] = ((pd.Timestamp(as_of) - pd.to_datetime(merged["DOB"])).dt.days // 365).astype(int)
    allergy_ids = set(sheets["Allergies"]["Patient ID"].astype(str))
    merged["Allergy Status"] = merged["Patient ID"].astype(str).map(lambda x: "Documented" if x in allergy_ids else "None documented")
    if filters["search"]:
        needle = filters["search"].lower()
        merged = merged[merged["Patient ID"].str.lower().str.contains(needle) | merged["Patient Name"].str.lower().str.contains(needle)]
    for column, value in (("Diagnosis", filters["diagnosis"]), ("Medication Name", filters["medication"]), ("Medication Status", filters["status"]), ("Allergy Status", filters["allergy"])):
        if value != "All":
            merged = merged[merged[column] == value]
    return patients[patients["Patient ID"].isin(merged["Patient ID"])], merged


def paginate_records(records: pd.DataFrame, page: int, page_size: int = 10) -> pd.DataFrame:
    """Return one bounded page of records for the dashboard table."""
    if page_size <= 0:
        raise ValueError("page_size must be positive")
    start = max(page, 0) * page_size
    return records.iloc[start:start + page_size]


def shift_months(value: date, months: int) -> date:
    """Shift a date by calendar months while preserving month-end behavior."""
    return (pd.Timestamp(value) + pd.DateOffset(months=months)).date()


def render_history_feed(history: pd.DataFrame) -> None:
    """Render history details directly so users do not need chart hover text."""
    st.markdown("#### Event activity")
    if history.empty:
        st.info("No medication history found for the selected date range.")
        return
    cards = []
    for _, event in history.sort_values("Event Date", ascending=False).iterrows():
        event_date = event["Event Date"].strftime("%b %d, %Y")
        medication = f"{event['Medication Name']} · {event['Dose']}"
        details = f"Quantity: {event['Quantity']} · Days supply: {event['Days Supply']}"
        notes = escape(str(event["Notes"])) if pd.notna(event["Notes"]) else ""
        cards.append(
            f"""<div class="history-event">
            <div class="history-event-date">{escape(event_date)}</div>
            <div class="history-event-type">{escape(str(event['Event Type']))}</div>
            <div class="history-event-details"><strong>{escape(medication)}</strong><br>{escape(details)}
            <div class="history-event-notes">{notes}</div></div>
            </div>"""
        )
    st.markdown(f"<div class=\"history-feed-grid\">{''.join(cards)}</div>", unsafe_allow_html=True)


def dashboard_tab(default: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], date]:
    st.subheader("Patient Dashboard")
    with st.expander("Data source", expanded=True):
        source_columns = st.columns([2, 1, 1])
        with source_columns[0]:
            uploaded = st.file_uploader("Upload .xlsx workbook", type=["xlsx"])
        with source_columns[1]:
            as_of = st.date_input("Analysis date", date(2026, 10, 7), format="MM/DD/YYYY")
        with source_columns[2]:
            st.write("")
            st.download_button(
                "Download sample workbook",
                workbook_bytes(default),
                "sample_patients.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
    sheets = default
    if uploaded is not None:
        sheets, errors = read_workbook(uploaded)
        if errors:
            for error in errors:
                st.error(error)
            sheets = default
        else:
            st.success("Uploaded workbook validated successfully.")

    base = enrich_medications(sheets["Medications"], as_of)
    with st.expander("Dashboard filters", expanded=True):
        filter_columns = st.columns(5)
        with filter_columns[0]:
            search = st.text_input("Patient name or ID")
        with filter_columns[1]:
            diagnosis = st.selectbox("Diagnosis", ["All"] + sorted(sheets["Patients"]["Diagnosis"].dropna().unique().tolist()))
        with filter_columns[2]:
            medication = st.selectbox("Medication", ["All"] + sorted(base["Medication Name"].dropna().unique().tolist()))
        with filter_columns[3]:
            status = st.selectbox("Medication status", ["All"] + list(STATUSES))
        with filter_columns[4]:
            allergy = st.selectbox("Allergy status", ["All", "Documented", "None documented"])
    filters = {"search": search, "diagnosis": diagnosis, "medication": medication, "status": status, "allergy": allergy}
    _, meds = filtered_records(sheets, as_of, filters)
    allergies = sheets["Allergies"]
    filtered_allergies = allergies[allergies["Patient ID"].isin(meds["Patient ID"].unique())]
    due = int((meds["Medication Status"] == "Refill Due").sum())
    soon = int((meds["Medication Status"] == "Refill Soon").sum())
    review = int((meds["Medication Status"] == "Review Required").sum() + (meds["Allergy Status"] == "Documented").sum())
    cols = st.columns(6)
    for col, label, value in zip(cols, ["Total Patients", "Active Medications", "Refills Due", "Refills Due Soon", "Patients With Documented Allergies", "Medications Requiring Review"], [meds["Patient ID"].nunique(), int((meds["Medication Status"] == "Active").sum()), due, soon, filtered_allergies["Patient ID"].nunique(), review]):
        col.metric(label, value)
    display = meds[["Patient ID", "Patient Name", "Age", "Gender", "Diagnosis", "Medication Name", "Strength", "Dose", "Frequency", "Last Fill Date", "Next Expected Fill Date", "Refills Remaining", "Medication Status", "Allergy Status"]]
    for column in ("Last Fill Date", "Next Expected Fill Date"):
        display[column] = pd.to_datetime(display[column], errors="coerce").dt.strftime("%m/%d/%Y")
    page_size = 10
    total_pages = max(1, ceil(len(display) / page_size))
    page_key = "dashboard_table_page"
    current_page = min(st.session_state.get(page_key, 0), total_pages - 1)
    st.session_state[page_key] = current_page
    previous, page_status, next_page = st.columns([1, 1, 4], gap=None)
    with previous:
        if st.button("← Previous", disabled=current_page == 0, key="dashboard_previous"):
            st.session_state[page_key] = current_page - 1
            st.rerun()
    with next_page:
        first_row = current_page * page_size + 1 if len(display) else 0
        last_row = min((current_page + 1) * page_size, len(display))
        st.caption(f"Showing {first_row}–{last_row} of {len(display)} records · Page {current_page + 1} of {total_pages}")
    with page_status:
        if st.button("Next →", disabled=current_page >= total_pages - 1, key="dashboard_next"):
            st.session_state[page_key] = current_page + 1
            st.rerun()
    if display.empty:
        headers = "".join(f"<th>{escape(str(column))}</th>" for column in display.columns)
        st.markdown(
            f"""<div class="empty-state-table"><table><thead><tr>{headers}</tr></thead>
            <tbody><tr><td colspan="{len(display.columns)}">No record found</td></tr></tbody>
            </table></div>""",
            unsafe_allow_html=True,
        )
    else:
        st.dataframe(paginate_records(display, current_page, page_size), use_container_width=True, hide_index=True)
    st.download_button("Download filtered CSV", display.to_csv(index=False).encode(), "filtered_medications.csv", "text/csv")
    if not display.empty:
        selected = st.selectbox("Patient detail", sorted(display["Patient Name"].unique()))
        patient = sheets["Patients"].loc[sheets["Patients"]["Patient Name"] == selected].iloc[0]
        summary = patient_summary(patient, enrich_medications(sheets["Medications"], as_of), sheets["Allergies"], sheets["Medication History"])
        with st.expander("Patient summary", expanded=True):
            st.text(summary)
            st.download_button("Download patient summary", summary, f"{patient['Patient ID']}_summary.txt", "text/plain")
    return sheets, as_of


def analytics_tab(sheets: dict[str, pd.DataFrame], as_of: date) -> None:
    st.subheader("Medication Analytics")
    meds = enrich_medications(sheets["Medications"], as_of).merge(sheets["Patients"], on="Patient ID")
    a, b = st.columns(2)
    with a:
        counts = meds.groupby("Medication Name")["Patient ID"].nunique().reset_index(name="Patients")
        st.plotly_chart(px.bar(counts, x="Patients", y="Medication Name", orientation="h", title="Patients by Medication"), use_container_width=True)
        statuses = meds["Medication Status"].value_counts().reindex(STATUSES, fill_value=0).reset_index()
        statuses.columns = ["Status", "Count"]
        st.plotly_chart(px.pie(statuses, names="Status", values="Count", hole=.5, title="Medication Status Distribution"), use_container_width=True)
        allergens = sheets["Allergies"]["Allergen"].value_counts().reset_index(name="Patients")
        allergens.columns = ["Allergen", "Patients"]
        st.plotly_chart(px.bar(allergens, x="Allergen", y="Patients", title="Documented Allergies"), use_container_width=True)
    with b:
        diagnosis = meds.groupby(["Diagnosis", "Medication Name"])["Patient ID"].nunique().reset_index(name="Patients")
        st.plotly_chart(px.bar(diagnosis, x="Diagnosis", y="Patients", color="Medication Name", barmode="stack", title="Diagnosis vs Medication"), use_container_width=True)
        history = sheets["Medication History"].copy()
        history["Month"] = pd.to_datetime(history["Event Date"]).dt.to_period("M").astype(str)
        monthly = history[history["Event Type"].str.contains("refill", case=False, na=False)].groupby("Month").size().reset_index(name="Refills")
        st.plotly_chart(px.line(monthly, x="Month", y="Refills", markers=True, title="Refill Activity by Month"), use_container_width=True)
        trends = history.groupby(["Month", "Event Type"]).size().reset_index(name="Events")
        st.plotly_chart(px.area(trends, x="Month", y="Events", color="Event Type", title="Medication Trends"), use_container_width=True)


def history_tab(sheets: dict[str, pd.DataFrame]) -> None:
    st.subheader("Medication History")
    patients = sheets["Patients"]
    control_columns = st.columns([2, 1, 1])
    with control_columns[0]:
        selected = st.selectbox("Patient", patients["Patient Name"].tolist(), key="history_patient")
    patient_id = patients.loc[patients["Patient Name"] == selected, "Patient ID"].iloc[0]
    history = sheets["Medication History"][sheets["Medication History"]["Patient ID"] == patient_id].copy()
    history["Event Date"] = pd.to_datetime(history["Event Date"], errors="coerce")
    history = history.dropna(subset=["Event Date"]).sort_values("Event Date")
    if history.empty:
        st.info("No medication history found for this patient.")
        return
    min_date, max_date = history["Event Date"].min().date(), history["Event Date"].max().date()
    default_from = max(min_date, shift_months(max_date, -4))
    if "history_from_date" not in st.session_state:
        st.session_state["history_from_date"] = default_from
    bounded_from = max(min_date, min(max_date, st.session_state["history_from_date"]))
    st.session_state["history_from_date"] = bounded_from
    with control_columns[1]:
        from_date = st.date_input("From date", min_value=min_date, max_value=max_date, format="MM/DD/YYYY", key="history_from_date")
    to_min = from_date
    to_max = min(max_date, shift_months(from_date, 6))
    if "history_to_date" not in st.session_state:
        st.session_state["history_to_date"] = max_date
    bounded_to = max(to_min, min(to_max, st.session_state["history_to_date"]))
    st.session_state["history_to_date"] = bounded_to
    with control_columns[2]:
        to_date = st.date_input("To date", min_value=to_min, max_value=to_max, format="MM/DD/YYYY", key="history_to_date")
    history = history[(history["Event Date"].dt.date >= from_date) & (history["Event Date"].dt.date <= to_date)]
    history = history.sort_values("Event Date")
    if history.empty:
        st.info("No medication history found in the selected date range.")
        return
    monthly = history.assign(Month=history["Event Date"].dt.to_period("M").astype(str)).groupby(["Month", "Event Type"]).size().reset_index(name="Events")
    st.plotly_chart(px.bar(monthly, x="Month", y="Events", color="Event Type", title="Medication Events by Month"), use_container_width=True)
    with st.expander("Interactive timeline chart", expanded=True):
        timeline = px.scatter(history, x="Event Date", y="Medication Name", color="Event Type", hover_data=["Dose", "Quantity", "Days Supply", "Notes"], title="Patient History Timeline")
        timeline.update_xaxes(tickformat="%m/%d/%Y")
        st.plotly_chart(timeline, use_container_width=True)
    render_history_feed(history)
    st.markdown("#### History table")
    history_display = history.copy()
    history_display["Event Date"] = history_display["Event Date"].dt.strftime("%m/%d/%Y")
    page_size = 10
    total_pages = max(1, ceil(len(history) / page_size))
    page_key = "history_table_page"
    current_page = min(st.session_state.get(page_key, 0), total_pages - 1)
    st.session_state[page_key] = current_page
    previous, page_status, next_page = st.columns([1, 1, 4], gap=None)
    with previous:
        if st.button("← Previous", disabled=current_page == 0, key="history_previous"):
            st.session_state[page_key] = current_page - 1
            st.rerun()
    with next_page:
        first_row = current_page * page_size + 1 if len(history) else 0
        last_row = min((current_page + 1) * page_size, len(history))
        st.caption(f"Showing {first_row}–{last_row} of {len(history)} records · Page {current_page + 1} of {total_pages}")
    with page_status:
        if st.button("Next →", disabled=current_page >= total_pages - 1, key="history_next"):
            st.session_state[page_key] = current_page + 1
            st.rerun()
    st.dataframe(paginate_records(history_display, current_page, page_size), use_container_width=True, hide_index=True)
    st.download_button("Download history CSV", history.to_csv(index=False).encode(), f"{patient_id}_history.csv", "text/csv")


def refill_review_tab(sheets: dict[str, pd.DataFrame], as_of: date) -> None:
    """Render the advisory, deterministic-first refill review workflow."""
    st.subheader("AI Refill Eligibility Review")
    st.info("Informational administrative review only. AI cannot approve, reject, prescribe, or change medication. An authorized clinician makes every refill decision.")
    patients = sheets["Patients"]
    medications = sheets["Medications"]
    patient_name = st.selectbox("Select patient", patients["Patient Name"].tolist(), key="refill_review_patient")
    patient = patients.loc[patients["Patient Name"] == patient_name].iloc[0]
    patient_meds = medications[medications["Patient ID"].astype(str) == str(patient["Patient ID"])].copy()
    if patient_meds.empty:
        st.warning("No medications are available for this patient.")
        return
    patient_meds["Review label"] = patient_meds.apply(lambda row: f"{row['Medication Name']} {row['Strength']} · {row['Medication ID']}", axis=1)
    medication_label = st.selectbox("Select current medication", patient_meds["Review label"].tolist(), key="refill_review_medication")
    medication = patient_meds.loc[patient_meds["Review label"] == medication_label].iloc[0]
    context = prepare_patient_context(patient, medication, sheets["Allergies"], sheets["Medication History"], as_of)
    rules = evaluate_refill_rules(context, as_of)
    review_context_key = f"{context.patient_ref}|{medication_label}"
    if st.session_state.get("refill_review_context_key") != review_context_key:
        st.session_state.pop("refill_ai_response", None)
        st.session_state["refill_review_context_key"] = review_context_key

    st.markdown("#### Deterministic rule results")
    rule_rows = {
        "Administrative recommendation": rules.administrative_status,
        "Prescription status": rules.prescription_status,
        "Refill timing": rules.refill_timing,
        "Refills remaining": rules.refills_remaining,
        "Required information": rules.required_information,
        "Allergy check": rules.allergy_check,
        "Review flags": ", ".join(rules.flags) or "None",
        "Clinician review": "Required",
    }
    rule_rows_html = "".join(
        f"<tr><td>{escape(str(label))}</td><td>{escape(str(value))}</td></tr>"
        for label, value in rule_rows.items()
    )
    st.markdown(
        "<table class='review-rule-table'>"
        "<thead><tr><th>Rule</th><th>Result</th></tr></thead>"
        f"<tbody>{rule_rows_html}</tbody></table>",
        unsafe_allow_html=True,
    )
    st.caption("This recommendation is administrative only. It does not determine clinical eligibility or authorize a refill.")
    if rules.flags:
        st.warning("Rule flags are authoritative and cannot be overridden by the AI: " + ", ".join(rules.flags))
    with st.expander("Synthetic context sent to Groq", expanded=False):
        st.json(context.model_dump())

    ai_response = None
    if st.button("Run AI administrative review", type="primary", key="run_refill_review"):
        with st.spinner("Preparing synthetic context and requesting structured review…"):
            try:
                try:
                    secrets_key = st.secrets.get("GROQ_API_KEY")
                except Exception:
                    secrets_key = None
                ai_response = request_ai_review(context, rules, api_key=secrets_key)
                st.session_state["refill_ai_response"] = ai_response.model_dump()
                st.success("Structured administrative review received.")
            except GroqReviewError as exc:
                st.error(str(exc))
                st.caption("The deterministic rule results remain available for clinician review.")
    stored_response = st.session_state.get("refill_ai_response")
    if ai_response is None and stored_response:
        ai_response = RefillAIResponse.model_validate(stored_response)
    if ai_response:
        st.markdown("#### AI administrative summary")
        st.warning(ai_response.administrative_review_status)
        st.write(ai_response.summary)
        with st.expander("Supporting evidence", expanded=True):
            for item in ai_response.supporting_evidence:
                st.markdown(f"- {item}")
        with st.expander("Missing information and review questions"):
            st.markdown("**Missing information**")
            for item in ai_response.missing_information or ["None reported"]:
                st.markdown(f"- {item}")
            st.markdown("**Questions for the authorized clinician**")
            for item in ai_response.review_questions or ["Confirm the refill decision using the complete clinical record."]:
                st.markdown(f"- {item}")


def main() -> None:
    _original_caption = st.caption
    st.caption = lambda *args, **kwargs: None
    st.set_page_config(page_title="RxInsight — Medication Analytics & History", page_icon="💊", layout="wide")
    styled_header()
    st.title("RxInsight — Medication Analytics & History")
    st.caption("Synthetic medication analytics for demonstration only — not clinical decision support.")
    st.caption = _original_caption
    default = load_default()
    tabs = st.tabs(["Patient Dashboard", "Medication Analytics", "Medication History", "AI Refill Eligibility Review"])
    with tabs[0]: sheets, as_of = dashboard_tab(default)
    with tabs[1]: analytics_tab(sheets, as_of)
    with tabs[2]: history_tab(sheets)
    with tabs[3]: refill_review_tab(sheets, as_of)


if __name__ == "__main__":
    main()
