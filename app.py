from __future__ import annotations

import io
import re
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd
import streamlit as st

from claim_engine import (
    CLAIM_ENGINE_VERSION,
    EVIDENCE_COLUMNS,
    JOB_COLUMNS,
    LEAD_COLUMNS,
    SCAN_LOG_COLUMNS,
    apply_crm_exclusions,
    build_evidence_from_jobs,
    clean_text,
    crm_keys_from_frame,
    deep_research_candidates,
    deep_research_lead,
    merge_jobs,
    migrate_evidence,
    migrate_jobs,
    migrate_leads,
    normalize,
    normalize_company,
    prepare_jobs,
    rebuild_leads,
    safe_int,
)
from scanner import scan_jobs

try:
    import gspread
    from google.oauth2.service_account import Credentials
except Exception:
    gspread = None
    Credentials = None


st.set_page_config(
    page_title="XING Lead Claim Engine",
    page_icon="🔎",
    layout="wide",
    initial_sidebar_state="expanded",
)


BROAD_TERMS = [
    "Physiotherapeut", "Ergotherapeut", "Logopäde", "Sprachtherapeut",
    "Pflegefachkraft", "Altenpfleger", "Gesundheits und Krankenpfleger",
    "Medizinische Fachangestellte", "Zahnmedizinische Fachangestellte",
    "Heilerziehungspfleger", "Erzieher", "Pädagogische Fachkraft", "Sozialpädagoge", "Sozialarbeiter",
    "Elektroniker", "Elektriker", "Anlagenmechaniker SHK", "Mechatroniker", "Kfz Mechatroniker",
    "Servicetechniker", "Kältetechniker", "Dachdecker", "Tischler", "Schreiner", "Metallbauer",
    "Schweißer", "Maler und Lackierer", "Maurer", "Straßenbauer", "Tiefbaufacharbeiter", "Zimmerer",
    "Industriemechaniker", "Zerspanungsmechaniker", "CNC Fräser", "CNC Dreher",
    "Maschinen und Anlagenführer", "Produktionsmitarbeiter", "Werkzeugmechaniker", "Instandhalter",
    "Qualitätsprüfer", "Qualitätsmanager", "Bauleiter", "Polier", "Kalkulator", "Projektleiter Bau",
    "Projektingenieur", "TGA Planer", "BIM Manager", "Bauzeichner", "Architekt", "Konstrukteur",
    "Elektroingenieur", "Maschinenbauingenieur", "Versorgungsingenieur",
    "Steuerfachangestellte", "Steuerfachwirt", "Bilanzbuchhalter", "Lohnbuchhalter",
    "Finanzbuchhalter", "Accountant", "Controller", "Steuerberater",
    "Rechtsanwaltsfachangestellte", "Notarfachangestellte", "Rechtsanwalt", "Legal Counsel",
    "Softwareentwickler", "Frontend Entwickler", "Backend Entwickler", "Full Stack Entwickler",
    "Systemadministrator", "IT Administrator", "IT Support", "Fachinformatiker", "DevOps Engineer",
    "Cloud Engineer", "Data Engineer", "Cyber Security Specialist", "SAP Berater", "ERP Berater",
    "Vertriebsmitarbeiter", "Vertriebsinnendienst", "Außendienstmitarbeiter", "Sales Manager",
    "Account Manager", "Key Account Manager", "Business Development Manager", "Customer Success Manager",
    "Technischer Vertrieb", "Einkäufer", "Berufskraftfahrer", "LKW Fahrer", "Disponent",
    "Speditionskaufmann", "Fachkraft für Lagerlogistik", "Fachlagerist", "Lagermitarbeiter", "Staplerfahrer",
    "Supply Chain Manager", "Laborant", "Chemielaborant", "Pharmakant", "Apotheker", "PTA",
    "Regulatory Affairs Manager", "Clinical Research Associate", "Medizintechniker", "Recruiter",
    "Personalreferent", "HR Business Partner", "Lohn und Gehaltsbuchhalter", "Sachbearbeiter",
    "Assistenz der Geschäftsführung", "Kaufmann für Büromanagement", "Industriekaufmann",
    "Immobilienkaufmann", "Immobilienverwalter", "Koch", "Küchenchef", "Servicekraft",
    "Restaurantfachmann", "Hotelfachmann", "Rezeptionist", "Verkäufer", "Filialleiter",
]

FOCUS_TERMS = [
    "Elektroniker", "Anlagenmechaniker SHK", "Mechatroniker", "Servicetechniker", "Kältetechniker",
    "Industriemechaniker", "Zerspanungsmechaniker", "CNC Fräser", "Bauleiter", "Projektingenieur",
    "TGA Planer", "Bauzeichner", "Steuerfachangestellte", "Steuerfachwirt", "Bilanzbuchhalter",
    "Lohnbuchhalter", "Softwareentwickler", "Systemadministrator", "Fachinformatiker", "DevOps Engineer",
    "Berufskraftfahrer", "Disponent", "Fachkraft für Lagerlogistik", "Physiotherapeut", "Ergotherapeut",
    "Logopäde", "Pflegefachkraft", "Medizinische Fachangestellte",
]

THERAPY_TERMS = ["Physiotherapeut", "Ergotherapeut", "Logopäde", "Sprachtherapeut", "Praxisleitung Therapie"]

DEFAULT_REGIONS = [
    ("Hamburg", 140), ("Bremen", 130), ("Hannover", 140), ("Münster", 130),
    ("Dortmund", 120), ("Düsseldorf", 120), ("Köln", 120), ("Frankfurt am Main", 140),
    ("Mannheim", 120), ("Stuttgart", 140), ("Nürnberg", 140), ("München", 160),
    ("Leipzig", 140), ("Dresden", 130), ("Berlin", 160), ("Rostock", 140),
]

CAMPAIGNS = {
    "Bedarfsradar Deutschland": BROAD_TERMS,
    "Fachkräfte Fokus": FOCUS_TERMS,
    "Therapie": THERAPY_TERMS,
    "Eigene Suchbegriffe": [],
}


def secret_text(name: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(name, default) or default).strip()
    except Exception:
        return default


def google_call(func, *args, **kwargs):
    last = None
    for wait in (0, 2, 5, 15):
        if wait:
            import time
            time.sleep(wait)
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            last = exc
            message = str(exc).lower()
            if not any(token in message for token in ("429", "quota", "rate limit", "500", "502", "503", "504")):
                raise
    raise last


class Storage:
    def __init__(self):
        self.mode = "local"
        self.error = ""
        self.book = None
        self.book_title = ""
        self.book_url = ""
        self.sheets: dict[str, Any] = {}
        try:
            service_account = dict(st.secrets.get("gcp_service_account", {}))
        except Exception:
            service_account = {}
        spreadsheet_id = secret_text("spreadsheet_id")
        spreadsheet_name = secret_text("spreadsheet_name")
        if not (gspread and Credentials and service_account and (spreadsheet_id or spreadsheet_name)):
            return
        try:
            credentials = Credentials.from_service_account_info(
                service_account,
                scopes=[
                    "https://www.googleapis.com/auth/spreadsheets",
                    "https://www.googleapis.com/auth/drive",
                ],
            )
            client = gspread.authorize(credentials)
            self.book = google_call(client.open_by_key, spreadsheet_id) if spreadsheet_id else google_call(client.open, spreadsheet_name)
            self.book_title = self.book.title
            self.book_url = f"https://docs.google.com/spreadsheets/d/{self.book.id}/edit"
            self.sheets = {ws.title: ws for ws in google_call(self.book.worksheets)}
            self.mode = "google"
        except Exception as exc:
            self.mode = "google_error"
            self.error = str(exc)

    def _sheet(self, title: str, rows: int, cols: int):
        if title in self.sheets:
            ws = self.sheets[title]
            try:
                target_rows = max(int(getattr(ws, "row_count", 0) or 0), rows)
                target_cols = max(int(getattr(ws, "col_count", 0) or 0), cols)
                if target_rows != getattr(ws, "row_count", 0) or target_cols != getattr(ws, "col_count", 0):
                    google_call(ws.resize, rows=target_rows, cols=target_cols)
            except Exception:
                pass
            return ws
        ws = google_call(self.book.add_worksheet, title=title, rows=rows, cols=cols)
        self.sheets[title] = ws
        return ws

    @staticmethod
    def _records(values: list[list[str]]) -> list[dict[str, str]]:
        if not values:
            return []
        header = values[0]
        records = []
        for row in values[1:]:
            padded = row + [""] * max(0, len(header) - len(row))
            records.append(dict(zip(header, padded[:len(header)])))
        return records

    def load_frame(self, title: str, columns: list[str], local_path: str) -> pd.DataFrame:
        if self.mode == "google_error":
            raise RuntimeError(self.error)
        if self.mode == "local":
            try:
                return pd.read_csv(local_path, dtype=str).fillna("")
            except FileNotFoundError:
                return pd.DataFrame(columns=columns)
        ws = self._sheet(title, 15000 if title != "Stellen" else 60000, max(len(columns) + 5, 20))
        values = google_call(ws.get_all_values)
        if not values:
            google_call(ws.update, [columns])
            return pd.DataFrame(columns=columns)
        return pd.DataFrame(self._records(values)).fillna("")

    def save_frame(self, title: str, frame: pd.DataFrame, columns: list[str], local_path: str) -> None:
        frame = frame.reindex(columns=columns).fillna("").astype(str)
        if self.mode == "google_error":
            raise RuntimeError(self.error)
        if self.mode == "local":
            frame.to_csv(local_path, index=False)
            return
        ws = self._sheet(title, max(15000, len(frame) + 100), max(len(columns) + 5, 20))
        values = [columns] + frame.values.tolist()
        google_call(ws.clear)
        for start in range(0, len(values), 1000):
            chunk = values[start:start + 1000]
            row_start = start + 1
            google_call(ws.update, chunk, f"A{row_start}")

    def load_exclusions(self) -> set[str]:
        frame = self.load_frame("CRM_Ausschluss", ["firma"], "crm_ausschluss_local.csv")
        keys: set[str] = set()
        for value in frame.get("firma", pd.Series(dtype=str)).astype(str):
            value = clean_text(value)
            if not value:
                continue
            if value.startswith(("@name:", "@domain:", "@phone:")):
                keys.add(value.lower())
            else:
                keys.add("@name:" + normalize_company(value))
        return keys

    def save_exclusions(self, keys: set[str]) -> None:
        frame = pd.DataFrame({"firma": sorted({k for k in keys if k})})
        self.save_frame("CRM_Ausschluss", frame, ["firma"], "crm_ausschluss_local.csv")


@st.cache_resource
def get_storage() -> Storage:
    return Storage()


storage = get_storage()
if storage.mode == "google_error":
    st.error(f"Google Sheets konnte nicht verbunden werden: {storage.error}")
    st.stop()


def load_all():
    leads = migrate_leads(storage.load_frame("Leads", LEAD_COLUMNS, "leads_local.csv"))
    jobs = migrate_jobs(storage.load_frame("Stellen", JOB_COLUMNS, "stellen_local.csv"))
    evidence = migrate_evidence(storage.load_frame("Evidence", EVIDENCE_COLUMNS, "evidence_local.csv"))
    logs = storage.load_frame("Scan_Log", SCAN_LOG_COLUMNS, "scan_log_local.csv")
    exclusions = storage.load_exclusions()
    leads = apply_crm_exclusions(leads, exclusions)
    return leads, jobs, evidence, logs, exclusions


def save_leads(frame: pd.DataFrame) -> None:
    storage.save_frame("Leads", migrate_leads(frame), LEAD_COLUMNS, "leads_local.csv")


def save_jobs(frame: pd.DataFrame) -> None:
    storage.save_frame("Stellen", migrate_jobs(frame), JOB_COLUMNS, "stellen_local.csv")


def save_evidence(frame: pd.DataFrame) -> None:
    storage.save_frame("Evidence", migrate_evidence(frame), EVIDENCE_COLUMNS, "evidence_local.csv")


def append_log(logs: pd.DataFrame, **kwargs) -> pd.DataFrame:
    record = {column: "" for column in SCAN_LOG_COLUMNS}
    record.update(kwargs)
    record["timestamp"] = record.get("timestamp") or datetime.now(timezone.utc).isoformat(timespec="seconds")
    logs = logs.reindex(columns=SCAN_LOG_COLUMNS).copy()
    logs.loc[len(logs)] = [record.get(column, "") for column in SCAN_LOG_COLUMNS]
    storage.save_frame("Scan_Log", logs, SCAN_LOG_COLUMNS, "scan_log_local.csv")
    return logs


def parse_regions(text: str) -> list[tuple[str, int]]:
    regions = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if "," not in line:
            raise ValueError(f"Region ohne Radius: {line}")
        city, radius = line.rsplit(",", 1)
        regions.append((city.strip(), int(radius.strip())))
    if not regions:
        raise ValueError("Mindestens eine Region eintragen.")
    return regions


def load_uploaded_table(uploaded) -> pd.DataFrame:
    name = uploaded.name.lower()
    if name.endswith(".xlsx"):
        return pd.read_excel(uploaded, dtype=str).fillna("")
    raw = uploaded.getvalue()
    for encoding in ("utf-8-sig", "utf-8", "latin1"):
        try:
            return pd.read_csv(io.BytesIO(raw), dtype=str, sep=None, engine="python", encoding=encoding).fillna("")
        except Exception:
            continue
    raise ValueError("Datei konnte nicht gelesen werden.")


def find_column(frame: pd.DataFrame, aliases: tuple[str, ...]) -> str | None:
    normalized = {normalize(column): column for column in frame.columns}
    for key, original in normalized.items():
        if any(alias in key for alias in aliases):
            return original
    return None


def portal_import_jobs(frame: pd.DataFrame, source_name: str) -> list[dict[str, Any]]:
    company_col = find_column(frame, ("company", "firma", "unternehmen", "arbeitgeber", "employer"))
    title_col = find_column(frame, ("title", "position", "jobtitel", "stellenbezeichnung", "job title"))
    city_col = find_column(frame, ("city", "ort", "location", "standort"))
    date_col = find_column(frame, ("published", "datum", "date", "veroffentlicht", "veroeffentlicht"))
    url_col = find_column(frame, ("url", "link", "stellenlink", "job url", "joblink"))
    id_col = find_column(frame, ("reference", "referenz", "job id", "jobid", "id"))
    description_col = find_column(frame, ("description", "beschreibung", "text", "snippet"))
    if not company_col or not title_col:
        raise ValueError("Für Portalimporte brauche ich mindestens Firmen- und Positionsspalte.")
    imported_jobs = []
    for _, row in frame.iterrows():
        company = clean_text(row.get(company_col, ""))
        title = clean_text(row.get(title_col, ""))
        if not company or not title:
            continue
        imported_jobs.append({
            "company": company,
            "title": title,
            "city": clean_text(row.get(city_col, "")) if city_col else "",
            "published": clean_text(row.get(date_col, "")) if date_col else "",
            "job_link": clean_text(row.get(url_col, "")) if url_col else "",
            "reference": clean_text(row.get(id_col, "")) if id_col else "",
            "description": clean_text(row.get(description_col, "")) if description_col else "",
            "source": source_name,
            "term": title,
            "lead_score": 45,
            "small_business_score": 50,
            "size_fit": "Mittel",
            "lead_segment": "Direktkunde",
        })
    return imported_jobs


def _nonempty(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().ne("")


def _pipe_unique(*values: Any) -> str:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        for part in str(value or "").split("|"):
            item = clean_text(part)
            key = item.lower()
            if item and key not in seen:
                seen.add(key)
                result.append(item)
    return " | ".join(result)


def _lead_professions(row: pd.Series | dict[str, Any]) -> str:
    return _pipe_unique(
        row.get("verified_job_titles", ""),
        row.get("job_titles", ""),
        row.get("offene_stellen", ""),
    )


def _lead_view(frame: pd.DataFrame) -> pd.DataFrame:
    frame = migrate_leads(frame)
    if frame.empty:
        return pd.DataFrame(columns=[
            "Firma", "Gesuchte Berufe", "Ort", "Ansprechpartner", "Rolle",
            "E-Mail", "Telefon", "Website", "Karriere", "Quellen", "Stellen",
            "Verifiziert", "Claim", "Claim Score", "Bedarf", "Research", "CRM",
        ])
    view = pd.DataFrame(index=frame.index)
    view["Firma"] = frame["firma"]
    view["Gesuchte Berufe"] = frame.apply(_lead_professions, axis=1)
    view["Ort"] = frame["orte"]
    view["Ansprechpartner"] = frame["ansprechpartner"]
    view["Rolle"] = frame["rolle"]
    view["E-Mail"] = frame["email"]
    view["Telefon"] = frame["telefon"]
    view["Website"] = frame["website"]
    view["Karriere"] = frame["karriereseite"]
    view["Quellen"] = frame["source_list"]
    view["Stellen"] = pd.to_numeric(frame["anzahl_stellen"], errors="coerce").fillna(0).astype(int)
    view["Verifiziert"] = pd.to_numeric(frame["verified_open_jobs"], errors="coerce").fillna(0).astype(int)
    view["Claim"] = frame["claim_status"]
    view["Claim Score"] = pd.to_numeric(frame["claim_score"], errors="coerce").fillna(0).astype(int)
    view["Bedarf"] = pd.to_numeric(frame["need_score"], errors="coerce").fillna(0).astype(int)
    view["Research"] = frame["research_depth"]
    view["CRM"] = frame["crm_status"]
    return view


def show_leads(frame: pd.DataFrame, *, max_rows: int = 1000) -> None:
    view = _lead_view(frame).head(max_rows)
    st.dataframe(
        view,
        hide_index=True,
        width="stretch",
        column_config={
            "Website": st.column_config.LinkColumn("Website"),
            "Karriere": st.column_config.LinkColumn("Karriere"),
            "Claim Score": st.column_config.NumberColumn("Claim Score", format="%d"),
            "Bedarf": st.column_config.NumberColumn("Bedarf", format="%d"),
            "Stellen": st.column_config.NumberColumn("Stellen", format="%d"),
            "Verifiziert": st.column_config.NumberColumn("Verifiziert", format="%d"),
        },
    )


def filter_leads_ui(frame: pd.DataFrame, key_prefix: str, *, default_claimable: bool = False) -> pd.DataFrame:
    frame = migrate_leads(frame).copy()
    c1, c2, c3, c4 = st.columns(4)
    search = c1.text_input("Firma / Beruf / Kontakt", key=f"{key_prefix}_search")
    only_person = c2.checkbox("Nur mit Ansprechpartner", key=f"{key_prefix}_person")
    only_email = c3.checkbox("Nur mit E-Mail", key=f"{key_prefix}_email")
    only_phone = c4.checkbox("Nur mit Telefon", key=f"{key_prefix}_phone")

    c5, c6, c7 = st.columns(3)
    claim_options = ["Alle", "CLAIMABLE", "RESEARCH", "REVIEW", "EXCLUDE"]
    default_claim_index = 1 if default_claimable else 0
    claim_filter = c5.selectbox("Claim Status", claim_options, index=default_claim_index, key=f"{key_prefix}_claim")
    profession = c6.text_input("Beruf enthält", key=f"{key_prefix}_profession")
    only_verified = c7.checkbox("Nur mit verifizierter Stelle", key=f"{key_prefix}_verified")

    if search:
        needle = search.strip()
        searchable = (
            frame["firma"].astype(str) + " " + frame["job_titles"].astype(str) + " "
            + frame["verified_job_titles"].astype(str) + " " + frame["offene_stellen"].astype(str) + " "
            + frame["ansprechpartner"].astype(str) + " " + frame["rolle"].astype(str) + " "
            + frame["email"].astype(str) + " " + frame["telefon"].astype(str)
        )
        frame = frame[searchable.str.contains(needle, case=False, na=False, regex=False)]
    if profession:
        profession_text = (
            frame["job_titles"].astype(str) + " "
            + frame["verified_job_titles"].astype(str) + " "
            + frame["offene_stellen"].astype(str)
        )
        frame = frame[profession_text.str.contains(profession.strip(), case=False, na=False, regex=False)]
    if only_person:
        frame = frame[_nonempty(frame["ansprechpartner"])]
    if only_email:
        frame = frame[_nonempty(frame["email"])]
    if only_phone:
        frame = frame[_nonempty(frame["telefon"])]
    if only_verified:
        frame = frame[pd.to_numeric(frame["verified_open_jobs"], errors="coerce").fillna(0) > 0]
    if claim_filter != "Alle":
        frame = frame[frame["claim_status"] == claim_filter]

    frame["_claim"] = pd.to_numeric(frame["claim_score"], errors="coerce").fillna(0)
    frame["_need"] = pd.to_numeric(frame["need_score"], errors="coerce").fillna(0)
    frame["_contact"] = (
        _nonempty(frame["ansprechpartner"]).astype(int)
        + _nonempty(frame["email"]).astype(int)
        + _nonempty(frame["telefon"]).astype(int)
    )
    return frame.sort_values(["_contact", "_claim", "_need"], ascending=[False, False, False])


if "data_loaded" not in st.session_state:
    leads, jobs, evidence, logs, exclusions = load_all()
    st.session_state.update({
        "leads": leads,
        "jobs": jobs,
        "evidence": evidence,
        "logs": logs,
        "exclusions": exclusions,
        "data_loaded": True,
    })

leads = migrate_leads(st.session_state["leads"])
jobs = migrate_jobs(st.session_state["jobs"])
evidence = migrate_evidence(st.session_state["evidence"])
logs = st.session_state["logs"].copy()
exclusions = set(st.session_state["exclusions"])

openai_key = secret_text("openai_api_key")
serpapi_key = secret_text("serpapi_key")
adzuna_app_id = secret_text("adzuna_app_id")
adzuna_api_key = secret_text("adzuna_api_key")

st.sidebar.title("Lead Claim Engine")
st.sidebar.caption(f"V{CLAIM_ENGINE_VERSION} · Kontakt-UI")
page = st.sidebar.radio(
    "Bereich",
    ["Dashboard", "Discovery", "Deep Research", "Alle Leads", "Claim Queue", "Stellen", "Salesforce", "System"],
)
st.sidebar.write(f"Speicher: {'Google Sheets' if storage.mode == 'google' else 'lokal'}")
if storage.book_title:
    st.sidebar.caption(storage.book_title)
    st.sidebar.link_button("Google Sheet öffnen", storage.book_url)
st.sidebar.write(f"SerpApi: {'bereit' if serpapi_key else 'fehlt'}")
st.sidebar.write(f"Adzuna: {'bereit' if adzuna_app_id and adzuna_api_key else 'fehlt'}")
st.sidebar.caption("Kontakte + gesuchte Berufe stehen wieder im Mittelpunkt.")

if st.sidebar.button("Daten neu laden"):
    st.cache_resource.clear()
    for key in ["data_loaded", "leads", "jobs", "evidence", "logs", "exclusions"]:
        st.session_state.pop(key, None)
    st.rerun()


if page == "Dashboard":
    st.title("Lead Cockpit")
    st.caption("Firmen, gesuchte Berufe und Kontaktdaten zuerst. Claim- und Research-Scores dienen nur zur Priorisierung.")

    claimable = leads[leads["claim_status"] == "CLAIMABLE"]
    verified = leads[pd.to_numeric(leads["verified_open_jobs"], errors="coerce").fillna(0) > 0]
    with_person = int(_nonempty(leads["ansprechpartner"]).sum())
    with_email = int(_nonempty(leads["email"]).sum())
    with_phone = int(_nonempty(leads["telefon"]).sum())

    cols = st.columns(7)
    cols[0].metric("Firmen", len(leads))
    cols[1].metric("Stellen", len(jobs))
    cols[2].metric("Ansprechpartner", with_person)
    cols[3].metric("E-Mail", with_email)
    cols[4].metric("Telefon", with_phone)
    cols[5].metric("Verifizierte Jobs", len(verified))
    cols[6].metric("CLAIMABLE", len(claimable))

    st.subheader("Beste Leads")
    dashboard = leads.copy()
    dashboard["_claim"] = pd.to_numeric(dashboard["claim_score"], errors="coerce").fillna(0)
    dashboard["_need"] = pd.to_numeric(dashboard["need_score"], errors="coerce").fillna(0)
    dashboard["_contact"] = (
        _nonempty(dashboard["ansprechpartner"]).astype(int)
        + _nonempty(dashboard["email"]).astype(int)
        + _nonempty(dashboard["telefon"]).astype(int)
    )
    dashboard = dashboard.sort_values(["_contact", "_claim", "_need"], ascending=[False, False, False])
    show_leads(dashboard, max_rows=300)


elif page == "Discovery":
    st.title("Discovery")
    st.caption("Mehrere Portale dürfen denselben Arbeitgeber finden. Gesuchte Berufe und Quellen werden pro Firma zusammengeführt.")
    campaign = st.selectbox("Kampagne", list(CAMPAIGNS))
    default_terms = CAMPAIGNS[campaign]
    terms_text = st.text_area("Suchbegriffe", "\n".join(default_terms), height=260)
    regions_text = st.text_area("Regionen: Ort,Radius", "\n".join(f"{city},{radius}" for city, radius in DEFAULT_REGIONS), height=220)
    c1, c2, c3, c4, c5 = st.columns(5)
    use_ba = c1.checkbox("Bundesagentur", value=True)
    use_adzuna = c2.checkbox("Adzuna", value=bool(adzuna_app_id and adzuna_api_key))
    use_google = c3.checkbox("Google Jobs", value=bool(serpapi_key))
    use_radar = c4.checkbox("Google Firmenradar", value=False)
    use_careers = c5.checkbox("Karriereseiten", value=False)
    career_urls = st.text_area("Optionale Karriere-/ATS-URLs", height=100)
    days = st.slider("Stellenalter in Tagen", 3, 45, 30)
    pages = st.slider("Seiten pro Suche", 1, 3, 2)
    terms_per_run = st.slider("Suchbegriffe pro Klick", 1, 30, 8)
    if "term_cursor" not in st.session_state:
        st.session_state["term_cursor"] = 0

    if st.button("Discovery starten", type="primary"):
        terms = [line.strip() for line in terms_text.splitlines() if line.strip()]
        try:
            regions = parse_regions(regions_text)
        except Exception as exc:
            st.error(str(exc))
            st.stop()
        if not terms:
            st.error("Keine Suchbegriffe.")
            st.stop()
        cursor = st.session_state["term_cursor"] % len(terms)
        selected_terms = [terms[(cursor + i) % len(terms)] for i in range(min(terms_per_run, len(terms)))]
        st.session_state["term_cursor"] = (cursor + len(selected_terms)) % len(terms)
        sources = []
        if use_ba:
            sources.append("Bundesagentur")
        if use_adzuna:
            sources.append("Adzuna")
        if use_google:
            sources.append("Google Jobs")
        if use_radar:
            sources.append("Google Firmenradar")
        if use_careers:
            sources.append("Karriereseiten")
        if not sources:
            st.error("Mindestens eine Quelle aktivieren.")
            st.stop()
        scan_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        with st.spinner("Portale werden durchsucht …"):
            raw_jobs, diagnostics = scan_jobs(
                terms=selected_terms,
                regions=regions,
                days=int(days),
                max_pages=int(pages),
                sources=sources,
                career_urls=[x.strip() for x in career_urls.splitlines() if x.strip()],
                serpapi_key=serpapi_key,
                adzuna_app_id=adzuna_app_id,
                adzuna_api_key=adzuna_api_key,
                ba_fetch_details=False,
                focus="Bedarfsradar Deutschland | alle Berufsgruppen",
            )
            fresh = prepare_jobs(raw_jobs, scan_id, campaign)
            jobs, inserted, updated = merge_jobs(jobs, fresh)
            leads = rebuild_leads(jobs, leads, campaign)
            leads = apply_crm_exclusions(leads, exclusions)
            evidence = build_evidence_from_jobs(jobs)
            save_jobs(jobs)
            save_leads(leads)
            save_evidence(evidence)
            logs = append_log(
                logs,
                scan_id=scan_id,
                stage="Discovery",
                status="completed",
                processed_terms=" | ".join(selected_terms),
                processed_items=str(len(selected_terms)),
                found_jobs=str(len(fresh)),
                new_leads=str(inserted),
                updated_leads=str(updated),
                message=f"{len(fresh)} Treffer aus {', '.join(sources)}",
            )
            st.session_state.update({"jobs": jobs, "leads": leads, "evidence": evidence, "logs": logs})
        st.success(f"{len(fresh)} Treffer verarbeitet · {inserted} neue Stellen · {updated} aktualisiert.")
        if not fresh.empty:
            st.subheader("Neu verarbeitete Stellen")
            st.dataframe(
                fresh[["firma", "position", "ort", "quelle", "ansprechpartner", "email", "telefon", "stellenlink"]].head(500),
                hide_index=True,
                width="stretch",
                column_config={"stellenlink": st.column_config.LinkColumn("Stellenlink")},
            )
        with st.expander("Diagnose"):
            st.write("\n".join(diagnostics))

    st.divider()
    st.subheader("Beliebiges Jobportal importieren")
    st.caption("CSV/XLSX mit Firma und Position genügt. Die Quelle bleibt als Evidence erhalten.")
    portal_name = st.text_input("Portalname", "Externes Jobportal")
    portal_file = st.file_uploader("CSV oder XLSX mit Firmen und Stellen", type=["csv", "xlsx"], key="portal_import")
    if portal_file is not None and st.button("Portaldatei übernehmen"):
        imported = load_uploaded_table(portal_file)
        raw_jobs = portal_import_jobs(imported, portal_name)
        scan_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        fresh = prepare_jobs(raw_jobs, scan_id, portal_name)
        jobs, inserted, updated = merge_jobs(jobs, fresh)
        leads = rebuild_leads(jobs, leads, portal_name)
        leads = apply_crm_exclusions(leads, exclusions)
        evidence = build_evidence_from_jobs(jobs)
        save_jobs(jobs)
        save_leads(leads)
        save_evidence(evidence)
        st.session_state.update({"jobs": jobs, "leads": leads, "evidence": evidence})
        st.success(f"{len(fresh)} Portalzeilen importiert · {inserted} neu · {updated} aktualisiert.")


elif page == "Deep Research":
    st.title("Deep Research")
    st.caption("Website, Karriere, ATS, Stellen und Kontaktdaten werden gemeinsam recherchiert. Ansprechpartner, E-Mail und Telefon bleiben zentrale Ergebnisse.")
    limit = st.slider("Firmen pro Lauf", 1, 50, 15)
    candidate_indices = deep_research_candidates(leads, limit)
    st.write(f"Aktuell priorisiert: **{len(candidate_indices)}** Firmen")
    if candidate_indices:
        preview = leads.loc[candidate_indices].copy()
        show_leads(preview, max_rows=50)

    if st.button("Deep Research starten", type="primary", disabled=not candidate_indices):
        progress = st.progress(0.0)
        details = []
        researched_indices: list[int] = []
        for pos, index in enumerate(candidate_indices, start=1):
            progress.progress((pos - 1) / max(1, len(candidate_indices)), text=f"{pos}/{len(candidate_indices)} {leads.at[index, 'firma']}")
            try:
                updated, diagnostics = deep_research_lead(leads.loc[index].to_dict(), serpapi_key=serpapi_key)
                for column in LEAD_COLUMNS:
                    leads.at[index, column] = updated.get(column, leads.at[index, column])
                researched_indices.append(index)
                details.extend(diagnostics)
            except Exception as exc:
                leads.at[index, "research_attempts"] = str(safe_int(leads.at[index, "research_attempts"], 0) + 1)
                leads.at[index, "last_error"] = f"Deep Research: {exc}"
                details.append(f"{leads.at[index, 'firma']}: Fehler {exc}")
        leads = apply_crm_exclusions(leads, exclusions)
        save_leads(leads)
        st.session_state["leads"] = leads
        progress.empty()
        st.success("Deep Research gespeichert.")
        if researched_indices:
            st.subheader("Recherche-Ergebnis")
            show_leads(leads.loc[researched_indices], max_rows=50)
        with st.expander("Recherche-Details", expanded=False):
            st.write("\n".join(details))


elif page == "Alle Leads":
    st.title("Alle Leads")
    st.caption("Arbeitsansicht für Firmen, gesuchte Berufe und Kontaktdaten.")
    filtered = filter_leads_ui(leads, "all_leads")
    st.write(f"**{len(filtered)}** Leads im Filter")
    show_leads(filtered, max_rows=3000)
    export = filtered.drop(columns=["_claim", "_need", "_contact"], errors="ignore")
    st.download_button(
        "Gefilterte Leads als CSV",
        export.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"xing_leads_{date.today().isoformat()}.csv",
        mime="text/csv",
    )


elif page == "Claim Queue":
    st.title("Claim Queue")
    st.caption("Kontaktdaten und gesuchte Berufe stehen vorne. Scores helfen nur bei der Reihenfolge.")
    filtered = filter_leads_ui(leads, "claim_queue", default_claimable=True)

    min_claim, min_need = st.columns(2)
    min_claim_score = min_claim.slider("Mindestens Claim Score", 0, 100, 50)
    min_need_score = min_need.slider("Mindestens Need Score", 0, 100, 40)
    filtered = filtered[
        (pd.to_numeric(filtered["claim_score"], errors="coerce").fillna(0) >= min_claim_score)
        & (pd.to_numeric(filtered["need_score"], errors="coerce").fillna(0) >= min_need_score)
    ]
    st.metric("Leads im Filter", len(filtered))
    show_leads(filtered, max_rows=2000)
    export = filtered.drop(columns=["_claim", "_need", "_contact"], errors="ignore")
    st.download_button(
        "Claim Queue als CSV",
        export.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"claimable_leads_{date.today().isoformat()}.csv",
        mime="text/csv",
    )


elif page == "Stellen":
    st.title("Stellen & Evidence")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Stellenzeilen", len(jobs))
    c2.metric("Quellenbelege", len(evidence))
    c3.metric("Arbeitgeber", jobs["firma"].nunique() if not jobs.empty else 0)
    c4.metric("Stellen mit Kontakt", int((_nonempty(jobs["email"]) | _nonempty(jobs["telefon"]) | _nonempty(jobs["ansprechpartner"])).sum()) if not jobs.empty else 0)

    job_search = st.text_input("Firma / Beruf / Kontakt durchsuchen", key="job_search")
    filtered_jobs = jobs.copy()
    if job_search:
        searchable = (
            filtered_jobs["firma"].astype(str) + " " + filtered_jobs["position"].astype(str) + " "
            + filtered_jobs["ort"].astype(str) + " " + filtered_jobs["ansprechpartner"].astype(str) + " "
            + filtered_jobs["email"].astype(str) + " " + filtered_jobs["telefon"].astype(str)
        )
        filtered_jobs = filtered_jobs[searchable.str.contains(job_search.strip(), case=False, na=False, regex=False)]

    st.dataframe(
        filtered_jobs[[
            "firma", "position", "ort", "ansprechpartner", "email", "telefon",
            "veroeffentlicht_am", "source_portal", "quelle", "stellenlink", "times_seen", "kampagne",
        ]].head(5000),
        hide_index=True,
        width="stretch",
        column_config={"stellenlink": st.column_config.LinkColumn("Stellenlink")},
    )
    with st.expander("Evidence anzeigen"):
        st.dataframe(evidence.head(5000), hide_index=True, width="stretch")


elif page == "Salesforce":
    st.title("Salesforce Ausschluss")
    st.caption("Ein Account wird über Firmenname, Domain und – wenn vorhanden – Telefon ausgeschlossen.")
    st.metric("Gespeicherte Ausschluss-Keys", len(exclusions))
    crm_file = st.file_uploader("Salesforce Account Export (CSV/XLSX)", type=["csv", "xlsx"], key="crm_upload")
    if crm_file is not None:
        crm_frame = load_uploaded_table(crm_file)
        keys = crm_keys_from_frame(crm_frame)
        st.write(f"Erkannt: **{len(crm_frame)} Zeilen** · **{len(keys)} Identitäts-Keys**")
        if st.button("Salesforce Export übernehmen", type="primary"):
            exclusions |= keys
            storage.save_exclusions(exclusions)
            leads = apply_crm_exclusions(leads, exclusions)
            save_leads(leads)
            st.session_state.update({"exclusions": exclusions, "leads": leads})
            st.success("Salesforce-Ausschluss aktualisiert.")
    manual = st.text_area("Firmen manuell ausschließen, eine pro Zeile")
    if st.button("Manuelle Firmen speichern"):
        for value in manual.splitlines():
            if value.strip():
                exclusions.add("@name:" + normalize_company(value))
        storage.save_exclusions(exclusions)
        leads = apply_crm_exclusions(leads, exclusions)
        save_leads(leads)
        st.session_state.update({"exclusions": exclusions, "leads": leads})
        st.success("Gespeichert.")


elif page == "System":
    st.title("System")
    st.write(f"Claim Engine: **{CLAIM_ENGINE_VERSION}**")
    st.write(f"Speicher: **{storage.mode}**")
    st.write(f"SerpApi: **{'bereit' if serpapi_key else 'fehlt'}**")
    st.write(f"Adzuna: **{'bereit' if adzuna_app_id and adzuna_api_key else 'fehlt'}**")
    st.write(f"OpenAI: **{'vorhanden, aber für Claiming nicht erforderlich' if openai_key else 'nicht erforderlich'}**")
    st.subheader("Datenqualität")
    metrics = {
        "Leads ohne Firma": int((leads["firma"].astype(str).str.strip() == "").sum()),
        "Jobs ohne Firma": int((jobs["firma"].astype(str).str.strip() == "").sum()),
        "Mit Ansprechpartner": int(_nonempty(leads["ansprechpartner"]).sum()),
        "Mit E-Mail": int(_nonempty(leads["email"]).sum()),
        "Mit Telefon": int(_nonempty(leads["telefon"]).sum()),
        "Deep Research": int((leads["research_depth"] == "deep").sum()),
        "Claimable": int((leads["claim_status"] == "CLAIMABLE").sum()),
    }
    st.json(metrics)
    st.subheader("Letzte Scan Logs")
    st.dataframe(logs.tail(200).iloc[::-1], hide_index=True, width="stretch")
