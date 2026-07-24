from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd
import streamlit as st

import pipeline as pipeline_module
from pipeline import (
    ASSET_KEYS,
    COLUMNS,
    JOB_COLUMNS,
    STATUSES,
    ai_candidate_indices,
    apply_crm_status,
    backfill_jobs_from_leads,
    build_discovery_leads,
    build_job_rows,
    clean_text,
    crm_match,
    enrich_lead,
    evaluate_lead_quality,
    generate_lead_assets,
    migrate_frame,
    migrate_jobs_frame,
    normalize_company,
    research_candidate_indices,
    refresh_quality,
    upsert_jobs,
    upsert_leads,
)
from sales_ai import openai_available
from scanner import scan_jobs

try:
    import gspread
    from google.oauth2.service_account import Credentials
except Exception:
    gspread = None
    Credentials = None


st.set_page_config(
    page_title="XING Daily Leads",
    page_icon="📞",
    layout="wide",
    initial_sidebar_state="expanded",
)


CAMPAIGN_PRESETS = {
    "Breite Massenkampagne": [
        # Bewusst gemischt sortiert, damit schon das erste Paket mehrere Branchen liefert.
        "Physiotherapeut", "Steuerfachangestellte", "Elektroniker", "Softwareentwickler",
        "Pflegefachkraft", "Vertriebsmitarbeiter", "Bauleiter", "Medizinische Fachangestellte",
        "Mechatroniker", "Bilanzbuchhalter", "Systemadministrator", "Berufskraftfahrer",
        "Ergotherapeut", "Rechtsanwaltsfachangestellte", "Servicetechniker", "Sales Manager",
        "Logopäde", "Lohnbuchhalter", "Industriemechaniker", "Disponent",
        "Zahnmedizinische Fachangestellte", "Konstrukteur", "Projektleiter", "Account Manager",
        "Pflegedienstleitung", "Finanzbuchhalter", "Anlagenmechaniker SHK", "IT Support",
        "Schweißer", "Personalreferent", "Recruiter", "Sachbearbeiter",
        "Controller", "Einkäufer", "Assistenz der Geschäftsführung", "Bürokaufmann",
        "Kaufmann für Büromanagement", "Industriekaufmann", "Speditionskaufmann", "Lagerist",
        "Fachkraft für Lagerlogistik", "Logistikmitarbeiter", "Produktionsmitarbeiter", "Maschinenbediener",
        "CNC Fräser", "CNC Dreher", "Werkzeugmechaniker", "Zerspanungsmechaniker",
        "Metallbauer", "Tischler", "Kältetechniker", "Elektroniker Betriebstechnik",
        "Elektroniker Automatisierungstechnik", "Elektroingenieur", "Projektingenieur", "TGA Planer",
        "Versorgungsingenieur", "Architekt", "Kalkulator Hochbau", "Polier",
        "Vorarbeiter", "Monteur", "Instandhalter", "Qualitätsmanager",
        "Qualitätssicherung", "Laborant", "Chemielaborant", "Pharmakant",
        "Regulatory Affairs Manager", "Clinical Research Associate", "Apotheker", "PTA",
        "Steuerfachwirt", "Steuerberater", "Wirtschaftsprüfer", "Rechtsanwalt",
        "Rechtsanwaltsanwärter", "Notarfachangestellte", "Patentanwaltsfachangestellte", "Compliance Manager",
        "Data Analyst", "DevOps Engineer", "IT Administrator", "IT Projektleiter",
        "SAP Berater", "ERP Consultant", "Webentwickler", "Fachinformatiker",
        "Marketing Manager", "Online Marketing Manager", "Customer Service", "Kundenberater",
        "Außendienstmitarbeiter", "Key Account Manager", "Business Development Manager", "Niederlassungsleiter",
        "Praxismanager", "Praxisleitung", "Therapeutische Leitung", "Heilerziehungspfleger",
        "Sozialpädagoge", "Erzieher", "Pädagogische Fachkraft", "Psychologe",
        "Koch", "Restaurantfachkraft", "Hotelfachkraft", "Hausmeister",
        "Gebäudereiniger", "Gärtner", "Immobilienkaufmann", "Property Manager",
    ],
    "Therapiepraxen": [
        "Physiotherapeut", "Ergotherapeut", "Logopäde", "Sprachtherapeut",
        "Praxisleitung Therapie", "Therapeutische Leitung",
    ],
    "Steuerkanzleien": [
        "Steuerfachangestellte", "Steuerfachwirt", "Bilanzbuchhalter",
        "Lohnbuchhalter", "Finanzbuchhalter", "Steuerberater",
    ],
    "Recht und Kanzleien": [
        "Rechtsanwaltsfachangestellte", "Rechtsanwalt", "Rechtsanwaltsanwärter",
        "Notarfachangestellte", "Patentanwaltsfachangestellte", "Legal Counsel",
    ],
    "Ambulante Pflege": [
        "Pflegefachkraft ambulant", "Pflegedienstleitung ambulant",
        "Pflegefachassistent", "Altenpfleger ambulant", "Tourenpflege",
    ],
    "Arztpraxen": [
        "Medizinische Fachangestellte", "MFA", "Zahnmedizinische Fachangestellte",
        "Praxismanager", "Praxisleitung",
    ],
    "Handwerk und Technik": [
        "Elektroniker", "Mechatroniker", "Anlagenmechaniker SHK",
        "Servicetechniker", "Industriemechaniker", "Schweißer",
        "Tischler", "Metallbauer", "Kältetechniker",
    ],
    "Industrie und Produktion": [
        "Produktionsmitarbeiter", "Maschinenbediener", "CNC Fräser", "CNC Dreher",
        "Zerspanungsmechaniker", "Werkzeugmechaniker", "Instandhalter", "Qualitätssicherung",
    ],
    "Kleine Ingenieurbüros": [
        "Bauleiter", "Projektingenieur", "Konstrukteur", "TGA Planer",
        "Elektroingenieur", "Versorgungsingenieur", "Projektleiter Bau",
    ],
    "Kleine IT Unternehmen": [
        "Softwareentwickler", "Systemadministrator", "DevOps Engineer",
        "IT Support", "IT Administrator", "Fachinformatiker", "SAP Berater",
    ],
    "Logistik und Einkauf": [
        "Berufskraftfahrer", "Disponent", "Speditionskaufmann", "Lagerist",
        "Fachkraft für Lagerlogistik", "Logistikmitarbeiter", "Fuhrparkleiter",
    ],
    "Vertrieb und Marketing": [
        "Vertriebsmitarbeiter", "Sales Manager", "Account Manager", "Key Account Manager",
        "Außendienstmitarbeiter", "Business Development Manager", "Sachbearbeiter", "Einkäufer",
    ],
    "Pharma und Forschung": [
        "Laborant", "Chemielaborant", "Pharmakant", "Regulatory Affairs Manager",
        "Clinical Research Associate", "Apotheker", "PTA",
    ],
    "Personal und Verwaltung": [
        "Personalreferent", "Recruiter", "HR Business Partner", "Sachbearbeiter",
        "Assistenz der Geschäftsführung", "Kaufmann für Büromanagement", "Industriekaufmann",
    ],
}


DEFAULT_REGIONS = [
    ("Hamburg", 180),
    ("Bremen", 160),
    ("Hannover", 180),
    ("Münster", 180),
    ("Dortmund", 150),
    ("Köln", 150),
    ("Frankfurt am Main", 180),
    ("Stuttgart", 180),
    ("Nürnberg", 180),
    ("München", 200),
    ("Leipzig", 180),
    ("Berlin", 200),
]


def _secret_text(name: str, default: str = "") -> str:
    """Liest einen Streamlit Secret Wert robust als getrimmten Text."""
    try:
        return str(st.secrets.get(name, default) or default).strip()
    except Exception:
        return str(default).strip()


def _google_config_signature() -> str:
    """Sorgt dafür, dass Streamlit die gecachte Google Verbindung neu aufbaut,
    sobald Ziel Sheet oder Service Account geändert werden.
    """
    try:
        account = st.secrets.get("gcp_service_account", {})
        client_email = str(account.get("client_email", "")).strip() if account else ""
    except Exception:
        client_email = ""
    return "|".join([
        _secret_text("spreadsheet_id"),
        _secret_text("spreadsheet_name"),
        client_email,
    ])

KMU_SCHEMA_VERSION = "6.0.0"


def exclusive_invitation_subject(company: Any) -> str:
    company_text = clean_text(company)
    return f"Exklusive Einladung | {company_text}" if company_text else "Exklusive Einladung"


def ensure_exclusive_subjects(frame: pd.DataFrame | None) -> tuple[pd.DataFrame, bool]:
    result = frame.copy() if frame is not None else pd.DataFrame()
    if result.empty or "firma" not in result.columns:
        return result, False
    if "erstmail_betreff" not in result.columns:
        result["erstmail_betreff"] = ""
    changed = False
    for index, company in result["firma"].items():
        target = exclusive_invitation_subject(company)
        if target and clean_text(result.at[index, "erstmail_betreff"]) != target:
            result.at[index, "erstmail_betreff"] = target
            changed = True
    return result, changed
KMU_REQUIRED_COLUMNS = {
    "lead_segment": "Direktkunde",
    "size_fit": "Mittel",
    "small_business_score": "50",
    "size_reason": "Bestandslead automatisch migriert",
}


def _safe_pipe_count(value: Any) -> int:
    parts = [part.strip() for part in str(value or "").split("|") if part.strip()]
    return max(1, len(parts))


def _fallback_kmu_segment(row: pd.Series) -> str:
    text = " ".join([
        str(row.get("firma", "")),
        str(row.get("job_titles", "")),
        str(row.get("offene_stellen", "")),
    ]).lower()
    groups = [
        ("Therapiepraxis", ("physio", "ergotherap", "logop", "sprachtherap", "therapie")),
        ("Steuerkanzlei", ("steuerfach", "steuerberater", "steuerkanz", "bilanzbuch", "lohnbuch", "datev")),
        ("Ambulante Pflege", ("ambulante pflege", "pflegedienst", "sozialstation", "tourenpflege")),
        ("Arztpraxis", ("medizinische fachang", " mfa", "arztpraxis", "zahnarztpraxis", "zahnmedizin")),
        ("Handwerk und Technik", ("elektroniker", "mechatron", "anlagenmechaniker", "shk", "servicetechn", "schwei", "metallbau", "tischler")),
        ("Ingenieurbüro", ("ingenieur", "planungsbüro", "planungsbuero", "bauleiter", "konstrukteur", "tga")),
        ("Kleines IT Unternehmen", ("softwareentwickler", "developer", "devops", "systemadministrator", "softwarehaus")),
    ]
    for segment, terms in groups:
        if any(term in text for term in terms):
            return segment
    return "Direktkunde"


def _fallback_size_fit(row: pd.Series, segment: str) -> tuple[str, int, str]:
    company = str(row.get("firma", "")).lower()
    try:
        jobs = max(1, int(float(row.get("anzahl_stellen", 1) or 1)))
    except (TypeError, ValueError):
        jobs = 1
    locations = _safe_pipe_count(row.get("orte", ""))
    large_tokens = (
        "holding", "gruppe", "group", "konzern", "kliniken", "universitätsklinikum",
        "deutsche bahn", "amazon", "siemens", "bosch", "lidl", "aldi", "rewe",
        "telekom", "dhl", "bundeswehr", "stadt ", "landkreis",
    )
    score = 65
    reasons = []
    if jobs <= 3:
        score += 20
        reasons.append("1 bis 3 Stellen")
    elif jobs <= 5:
        score += 10
        reasons.append("4 bis 5 Stellen")
    elif jobs > 8:
        score -= 55
        reasons.append("mehr als 8 Stellen")
    if locations == 1:
        score += 10
        reasons.append("ein Standort")
    elif locations > 3:
        score -= 35
        reasons.append("mehr als 3 Standorte")
    if segment in {"Therapiepraxis", "Steuerkanzlei", "Ambulante Pflege", "Arztpraxis", "Ingenieurbüro"}:
        score += 10
        reasons.append(segment)
    if any(token in company for token in large_tokens):
        score -= 60
        reasons.append("Großstruktur erkannt")
    score = max(0, min(100, score))
    if jobs > 8 or locations > 3 or any(token in company for token in large_tokens) or score < 35:
        fit = "Groß oder unpassend"
    elif score >= 70:
        fit = "Klein"
    else:
        fit = "Mittel"
    return fit, score, "; ".join(reasons[:5])


def ensure_kmu_schema(frame: pd.DataFrame | None) -> tuple[pd.DataFrame, bool]:
    """Migriert alte Google-Sheets-Daten robust auf das KMU-Schema.

    Der zweite Rückgabewert zeigt, ob Spalten oder Werte ergänzt wurden und das
    Sheet einmalig zurückgeschrieben werden sollte.
    """
    result = frame.copy() if frame is not None else pd.DataFrame()
    changed = False

    for column in COLUMNS:
        if column not in result.columns:
            result[column] = ""
            changed = True
    for column, default in KMU_REQUIRED_COLUMNS.items():
        if column not in result.columns:
            result[column] = ""
            changed = True

    result = result.fillna("")
    if result.empty:
        ordered = list(dict.fromkeys(list(COLUMNS) + list(KMU_REQUIRED_COLUMNS)))
        return result.reindex(columns=ordered), changed

    for index, row in result.iterrows():
        segment = str(row.get("lead_segment", "")).strip() or _fallback_kmu_segment(row)
        if not str(row.get("lead_segment", "")).strip():
            result.at[index, "lead_segment"] = segment
            changed = True

        fit_text = str(row.get("size_fit", "")).strip()
        score_text = str(row.get("small_business_score", "")).strip()
        reason_text = str(row.get("size_reason", "")).strip()
        if not fit_text or not score_text or not reason_text:
            fit, score, reason = _fallback_size_fit(row, segment)
            if not fit_text:
                result.at[index, "size_fit"] = fit
                changed = True
            if not score_text:
                result.at[index, "small_business_score"] = str(score)
                changed = True
            if not reason_text:
                result.at[index, "size_reason"] = reason
                changed = True

    ordered = list(dict.fromkeys(list(COLUMNS) + list(KMU_REQUIRED_COLUMNS)))
    return result.reindex(columns=ordered).fillna("").astype(str), changed


LOG_COLUMNS = [
    "timestamp",
    "scan_id",
    "stage",
    "status",
    "processed_terms",
    "processed_items",
    "found_jobs",
    "new_leads",
    "updated_leads",
    "message",
]


def _google_error_meta(exc: Exception) -> tuple[int | None, int | None, str]:
    """Liest Statuscode und Retry-After robust aus gspread/requests Fehlern."""
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    retry_after = None
    try:
        header_value = response.headers.get("Retry-After") if response is not None else None
        retry_after = int(header_value) if header_value else None
    except Exception:
        retry_after = None
    return status, retry_after, str(exc)


def _google_call(func, *args, **kwargs):
    """Google-Aufruf mit belastbarem Backoff für Quota- und Serverfehler.

    429-Fehler werden bis zu rund einer Minute lang erneut versucht. Dauerhafte
    Fehler wie fehlende Rechte oder ein falsches Sheet werden sofort weitergegeben.
    """
    waits = (2, 5, 15, 40)
    last_error = None
    for attempt in range(len(waits) + 1):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            last_error = exc
            status, retry_after, message = _google_error_meta(exc)
            low = message.lower()
            temporary = (
                status in {429, 500, 502, 503, 504}
                or "429" in low
                or "quota exceeded" in low
                or "resource_exhausted" in low
                or "rate limit" in low
                or "503" in low
            )
            if not temporary or attempt >= len(waits):
                raise
            wait_seconds = max(waits[attempt], retry_after or 0)
            time.sleep(wait_seconds)
    raise last_error


def _column_letter(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


class Storage:
    def __init__(self):
        self.mode = "local"
        self.error = ""
        self.ws = None
        self.jobs_ws = None
        self.exclusion_ws = None
        self.log_ws = None
        self.book_title = ""
        self.book_id = ""
        self.book_url = ""
        self.row_map: dict[str, int] = {}
        self.next_row = 2
        self.job_row_map: dict[str, int] = {}
        self.job_next_row = 2
        self._exclusions_cache: set[str] | None = None
        self.local_path = "leads_local.csv"
        self.local_jobs_path = "stellen_local.csv"
        self.local_exclusion_path = "crm_ausschluss_local.csv"
        self.local_log_path = "scan_log_local.csv"

        spreadsheet_id = _secret_text("spreadsheet_id")
        spreadsheet_name = _secret_text("spreadsheet_name")
        try:
            service_account = dict(st.secrets.get("gcp_service_account", {}))
        except Exception:
            service_account = {}

        configured = bool(
            gspread
            and Credentials
            and service_account
            and (spreadsheet_id or spreadsheet_name)
        )
        if not configured:
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
            if spreadsheet_id:
                book = _google_call(client.open_by_key, spreadsheet_id)
            else:
                # Fallback für alte Konfigurationen. Ein Name ist bei mehreren gleichnamigen
                # Dateien nicht eindeutig, deshalb sollte spreadsheet_id verwendet werden.
                book = _google_call(client.open, spreadsheet_name)

            self.book_title = book.title
            self.book_id = book.id
            self.book_url = f"https://docs.google.com/spreadsheets/d/{book.id}/edit"
            worksheets = {sheet.title: sheet for sheet in _google_call(book.worksheets)}
            self.ws = self._lead_sheet(book, worksheets, 12000, max(70, len(COLUMNS) + 5))
            self.jobs_ws = self._sheet(book, worksheets, "Stellen", 50000, max(30, len(JOB_COLUMNS) + 3))
            self.exclusion_ws = self._sheet(book, worksheets, "CRM_Ausschluss", 12000, 5)
            self.log_ws = self._sheet(book, worksheets, "Scan_Log", 12000, len(LOG_COLUMNS) + 2)
            self.mode = "google"
        except Exception as exc:
            self.mode = "google_error"
            self.error = str(exc)

    @staticmethod
    def _lead_sheet(book, worksheets: dict[str, Any], rows: int, cols: int):
        """Verwendet genau ein sichtbares Hauptblatt für alle Leads.

        Existiert bereits ein Blatt "Leads", wird es genutzt. Ist nur das leere
        Standardblatt "Tabelle1" vorhanden, wird dieses in "Leads" umbenannt,
        statt ein weiteres leeres Blatt anzulegen.
        """
        if "Leads" in worksheets:
            return worksheets["Leads"]

        default_sheet = worksheets.get("Tabelle1") or worksheets.get("Sheet1")
        if default_sheet is not None:
            try:
                values = _google_call(default_sheet.get_all_values)
                if not values or not any(any(str(cell).strip() for cell in row) for row in values):
                    old_title = default_sheet.title
                    _google_call(default_sheet.update_title, "Leads")
                    worksheets.pop(old_title, None)
                    worksheets["Leads"] = default_sheet
                    return default_sheet
            except Exception:
                pass

        return Storage._sheet(book, worksheets, "Leads", rows, cols)

    @staticmethod
    def _sheet(book, worksheets: dict[str, Any], title: str, rows: int, cols: int):
        if title in worksheets:
            sheet = worksheets[title]
            try:
                target_rows = max(int(getattr(sheet, "row_count", 0) or 0), rows)
                target_cols = max(int(getattr(sheet, "col_count", 0) or 0), cols)
                if target_rows != getattr(sheet, "row_count", 0) or target_cols != getattr(sheet, "col_count", 0):
                    _google_call(sheet.resize, rows=target_rows, cols=target_cols)
            except Exception:
                pass
            return sheet
        sheet = _google_call(book.add_worksheet, title=title, rows=rows, cols=cols)
        try:
            _google_call(sheet.freeze, rows=1)
        except Exception:
            pass
        worksheets[title] = sheet
        return sheet

    @staticmethod
    def _records(values: list[list[str]]) -> list[dict[str, str]]:
        if not values:
            return []
        header = values[0]
        records: list[dict[str, str]] = []
        for row in values[1:]:
            padded = row + [""] * max(0, len(header) - len(row))
            records.append(dict(zip(header, padded[: len(header)])))
        return records

    def load(self) -> pd.DataFrame:
        if self.mode == "google_error":
            raise RuntimeError(self.error or "Google Sheets ist nicht verbunden.")
        if self.mode == "local":
            try:
                return migrate_frame(pd.read_csv(self.local_path, dtype=str).fillna(""))
            except FileNotFoundError:
                return migrate_frame(pd.DataFrame())

        values = _google_call(self.ws.get_all_values)
        if not values:
            _google_call(self.ws.update, [COLUMNS])
            self.row_map = {}
            self.next_row = 2
            return migrate_frame(pd.DataFrame())

        header = values[0]
        frame = migrate_frame(pd.DataFrame(self._records(values)))
        if header != COLUMNS:
            self.save(frame)
            return frame

        self.row_map = {}
        for index, record in enumerate(self._records(values), start=2):
            lead = clean_text(record.get("lead_id", ""))
            if lead:
                self.row_map[lead] = index
        self.next_row = max([1] + list(self.row_map.values())) + 1
        return frame

    def save(self, frame: pd.DataFrame) -> None:
        frame = migrate_frame(frame)
        if self.mode == "google_error":
            raise RuntimeError(self.error or "Google Sheets ist nicht verbunden.")
        if self.mode == "local":
            frame.to_csv(self.local_path, index=False)
            return

        _google_call(self.ws.clear)
        _google_call(self.ws.update, [COLUMNS] + frame.astype(str).values.tolist())
        self.row_map = {
            row["lead_id"]: index
            for index, (_, row) in enumerate(frame.iterrows(), start=2)
            if row["lead_id"]
        }
        self.next_row = len(frame) + 2

    def upsert_rows(self, rows: pd.DataFrame, full_frame: pd.DataFrame) -> None:
        rows = migrate_frame(rows)
        full_frame = migrate_frame(full_frame)
        if rows.empty:
            return
        if self.mode != "google":
            self.save(full_frame)
            return

        end_column = _column_letter(len(COLUMNS))
        updates: list[dict[str, Any]] = []
        append_values: list[list[str]] = []
        append_ids: list[str] = []
        for _, row in rows.iterrows():
            values = [str(row[column] or "") for column in COLUMNS]
            lead = row["lead_id"]
            if lead in self.row_map:
                sheet_row = self.row_map[lead]
                updates.append({
                    "range": f"A{sheet_row}:{end_column}{sheet_row}",
                    "values": [values],
                })
            else:
                append_values.append(values)
                append_ids.append(lead)

        try:
            for start in range(0, len(updates), 100):
                _google_call(self.ws.batch_update, updates[start : start + 100])
            if append_values:
                _google_call(self.ws.append_rows, append_values, value_input_option="RAW")
                for lead in append_ids:
                    self.row_map[lead] = self.next_row
                    self.next_row += 1
        except Exception:
            # Ein kompletter Fallback ist langsamer, aber verhindert Datenverlust,
            # falls sich die gspread Signatur ändert oder ein Batch fehlschlägt.
            self.save(full_frame)

    def load_jobs(self) -> pd.DataFrame:
        if self.mode == "google_error":
            raise RuntimeError(self.error or "Google Sheets ist nicht verbunden.")
        if self.mode == "local":
            try:
                return migrate_jobs_frame(pd.read_csv(self.local_jobs_path, dtype=str).fillna(""))
            except FileNotFoundError:
                return migrate_jobs_frame(pd.DataFrame())

        values = _google_call(self.jobs_ws.get_all_values)
        if not values:
            _google_call(self.jobs_ws.update, [JOB_COLUMNS])
            self.job_row_map = {}
            self.job_next_row = 2
            return migrate_jobs_frame(pd.DataFrame())

        header = values[0]
        frame = migrate_jobs_frame(pd.DataFrame(self._records(values)))
        if header != JOB_COLUMNS:
            self.save_jobs(frame)
            return frame

        self.job_row_map = {}
        for index, record in enumerate(self._records(values), start=2):
            job = clean_text(record.get("job_id", ""))
            if job:
                self.job_row_map[job] = index
        self.job_next_row = max([1] + list(self.job_row_map.values())) + 1
        return frame

    def save_jobs(self, frame: pd.DataFrame) -> None:
        frame = migrate_jobs_frame(frame)
        if self.mode == "google_error":
            raise RuntimeError(self.error or "Google Sheets ist nicht verbunden.")
        if self.mode == "local":
            frame.to_csv(self.local_jobs_path, index=False)
            return

        _google_call(self.jobs_ws.clear)
        _google_call(self.jobs_ws.update, [JOB_COLUMNS] + frame.astype(str).values.tolist())
        self.job_row_map = {
            row["job_id"]: index
            for index, (_, row) in enumerate(frame.iterrows(), start=2)
            if row["job_id"]
        }
        self.job_next_row = len(frame) + 2

    def upsert_job_rows(self, rows: pd.DataFrame, full_frame: pd.DataFrame) -> None:
        rows = migrate_jobs_frame(rows)
        full_frame = migrate_jobs_frame(full_frame)
        if rows.empty:
            return
        if self.mode != "google":
            self.save_jobs(full_frame)
            return

        end_column = _column_letter(len(JOB_COLUMNS))
        updates: list[dict[str, Any]] = []
        append_values: list[list[str]] = []
        append_ids: list[str] = []
        for _, row in rows.iterrows():
            values = [str(row[column] or "") for column in JOB_COLUMNS]
            jid = row["job_id"]
            if jid in self.job_row_map:
                sheet_row = self.job_row_map[jid]
                updates.append({
                    "range": f"A{sheet_row}:{end_column}{sheet_row}",
                    "values": [values],
                })
            else:
                append_values.append(values)
                append_ids.append(jid)

        try:
            for start in range(0, len(updates), 100):
                _google_call(self.jobs_ws.batch_update, updates[start : start + 100])
            if append_values:
                for start in range(0, len(append_values), 500):
                    batch = append_values[start : start + 500]
                    _google_call(self.jobs_ws.append_rows, batch, value_input_option="RAW")
                for jid in append_ids:
                    self.job_row_map[jid] = self.job_next_row
                    self.job_next_row += 1
        except Exception:
            self.save_jobs(full_frame)

    def load_exclusions(self) -> set[str]:
        if self.mode == "google_error":
            raise RuntimeError(self.error or "Google Sheets ist nicht verbunden.")
        if self.mode == "local":
            try:
                frame = pd.read_csv(self.local_exclusion_path, dtype=str).fillna("")
                result = {normalize_company(value) for value in frame.get("firma", []) if value}
            except FileNotFoundError:
                result = set()
            self._exclusions_cache = set(result)
            return result

        values = _google_call(self.exclusion_ws.get_all_values)
        if not values:
            _google_call(self.exclusion_ws.update_acell, "A1", "firma")
            result: set[str] = set()
        else:
            first_cell = clean_text(values[0][0] if values[0] else "").lower()
            start_index = 1 if first_cell == "firma" else 0
            if first_cell != "firma":
                _google_call(self.exclusion_ws.insert_row, ["firma"], 1)
                start_index = 0
            result = {
                normalize_company(row[0])
                for row in values[start_index:]
                if row and normalize_company(row[0])
            }
        self._exclusions_cache = set(result)
        return result

    def save_exclusions(self, companies: set[str]) -> set[str]:
        """Speichert Ausschlüsse additiv statt das ganze Blatt neu zu schreiben.

        Die Ausschlussliste ist absichtlich monoton: Neue Firmen werden in einem
        einzigen Batch angehängt. Dadurch entstehen weder Clear-Requests noch ein
        vollständiges Rewrite bei jedem einzelnen Klick.
        """
        target = {
            normalize_company(company)
            for company in companies
            if normalize_company(company)
        }
        if self.mode == "google_error":
            raise RuntimeError(self.error or "Google Sheets ist nicht verbunden.")
        if self.mode == "local":
            existing = self._exclusions_cache if self._exclusions_cache is not None else self.load_exclusions()
            combined = set(existing) | target
            pd.DataFrame({"firma": sorted(combined)}).to_csv(self.local_exclusion_path, index=False)
            self._exclusions_cache = combined
            return combined

        existing = self._exclusions_cache if self._exclusions_cache is not None else self.load_exclusions()
        additions = sorted(target - existing)
        if not additions:
            return set(existing)

        rows = [[company] for company in additions]
        for start in range(0, len(rows), 500):
            _google_call(
                self.exclusion_ws.append_rows,
                rows[start : start + 500],
                value_input_option="RAW",
                insert_data_option="INSERT_ROWS",
            )

        combined = set(existing) | set(additions)
        self._exclusions_cache = combined
        return combined

    def load_logs(self) -> pd.DataFrame:
        if self.mode == "google_error":
            raise RuntimeError(self.error or "Google Sheets ist nicht verbunden.")
        if self.mode == "local":
            try:
                frame = pd.read_csv(self.local_log_path, dtype=str).fillna("")
            except FileNotFoundError:
                frame = pd.DataFrame(columns=LOG_COLUMNS)
            return frame.reindex(columns=LOG_COLUMNS).fillna("")

        values = _google_call(self.log_ws.get_all_values)
        if not values:
            _google_call(self.log_ws.update, [LOG_COLUMNS])
            return pd.DataFrame(columns=LOG_COLUMNS)
        frame = pd.DataFrame(self._records(values))
        for column in LOG_COLUMNS:
            if column not in frame.columns:
                frame[column] = ""
        return frame.reindex(columns=LOG_COLUMNS).fillna("")

    def append_log(self, record: dict[str, Any]) -> None:
        row = [clean_text(record.get(column, "")) for column in LOG_COLUMNS]
        if self.mode == "google_error":
            raise RuntimeError(self.error or "Google Sheets ist nicht verbunden.")
        if self.mode == "local":
            current = self.load_logs()
            current.loc[len(current)] = row
            current.to_csv(self.local_log_path, index=False)
            return
        _google_call(self.log_ws.append_row, row, value_input_option="RAW")


@st.cache_resource(show_spinner=False)
def get_storage(config_signature: str) -> Storage:
    # Der Parameter dient ausschließlich zur Cache Invalidierung.
    _ = config_signature
    return Storage()


storage = get_storage(_google_config_signature())


def persist_full(frame: pd.DataFrame) -> None:
    frame = migrate_frame(frame)
    storage.save(frame)
    st.session_state["xing_frame_cache"] = frame.copy()


def persist_rows(rows: pd.DataFrame, frame: pd.DataFrame) -> None:
    rows = migrate_frame(rows)
    frame = migrate_frame(frame)
    storage.upsert_rows(rows, frame)
    st.session_state["xing_frame_cache"] = frame.copy()


def persist_job_rows(rows: pd.DataFrame, jobs_frame: pd.DataFrame) -> None:
    rows = migrate_jobs_frame(rows)
    jobs_frame = migrate_jobs_frame(jobs_frame)
    storage.upsert_job_rows(rows, jobs_frame)
    st.session_state["xing_jobs_cache"] = jobs_frame.copy()


def sync_lead_contacts_to_jobs(lead_row: dict[str, Any], jobs_frame: pd.DataFrame) -> pd.DataFrame:
    """Überträgt recherchierte Kontakte in alle Stellenzeilen derselben Firma."""
    jobs_frame = migrate_jobs_frame(jobs_frame)
    lid = clean_text(lead_row.get("lead_id", ""))
    if not lid or jobs_frame.empty:
        return migrate_jobs_frame(pd.DataFrame())
    mask = jobs_frame["lead_id"] == lid
    if not mask.any():
        return migrate_jobs_frame(pd.DataFrame())
    mapping = {
        "email": clean_text(lead_row.get("email", "")),
        "telefon": clean_text(lead_row.get("telefon", "")),
        "ansprechpartner": clean_text(lead_row.get("ansprechpartner", "")),
    }
    changed = False
    for column, value in mapping.items():
        if value:
            jobs_frame.loc[mask, column] = value
            changed = True
    if not changed:
        return migrate_jobs_frame(pd.DataFrame())
    st.session_state["xing_jobs_cache"] = jobs_frame.copy()
    return jobs_frame.loc[mask].copy()


def persist_exclusions(companies: set[str]) -> set[str]:
    normalized = {normalize_company(company) for company in companies if normalize_company(company)}
    persisted = storage.save_exclusions(normalized)
    st.session_state["xing_exclusions_cache"] = set(persisted)
    return set(persisted)


def _google_action_error(exc: Exception) -> str:
    status, _, message = _google_error_meta(exc)
    if status == 429 or "429" in message or "quota" in message.lower():
        return "Google Sheets ist gerade am Minutenlimit. Die App hat automatisch erneut versucht. Bitte etwa eine Minute warten und den Klick einmal wiederholen."
    if status == 403 or "403" in message:
        return "Google Sheets verweigert den Schreibzugriff. Prüfe, ob die Service Account E Mail im Sheet die Rolle Mitarbeiter hat."
    if status == 404 or "404" in message:
        return "Das verbundene Google Sheet oder das Tabellenblatt CRM_Ausschluss wurde nicht gefunden."
    return f"Google Sheets konnte die Änderung nicht speichern: {message}"


def append_log(**kwargs) -> None:
    record = {column: "" for column in LOG_COLUMNS}
    record.update(kwargs)
    record["timestamp"] = record.get("timestamp") or datetime.now(timezone.utc).isoformat(timespec="seconds")
    storage.append_log(record)
    logs = st.session_state.get("xing_logs_cache", pd.DataFrame(columns=LOG_COLUMNS)).copy()
    logs.loc[len(logs)] = [record.get(column, "") for column in LOG_COLUMNS]
    st.session_state["xing_logs_cache"] = logs


def read_company_file(uploaded_file):
    name = uploaded_file.name.lower()
    if name.endswith(".xlsx"):
        frame = pd.read_excel(uploaded_file, dtype=str).fillna("")
    else:
        raw = uploaded_file.getvalue()
        frame = None
        for encoding in ("utf-8-sig", "utf-8", "latin1"):
            try:
                frame = pd.read_csv(
                    pd.io.common.BytesIO(raw),
                    dtype=str,
                    sep=None,
                    engine="python",
                    encoding=encoding,
                ).fillna("")
                break
            except Exception:
                continue
        if frame is None:
            raise ValueError("CSV konnte nicht gelesen werden.")

    aliases = [
        "account name", "account", "firmenname", "firma", "unternehmen",
        "company", "name des accounts", "kunde", "kundenname",
    ]
    normalized_columns = {normalize_company(column): column for column in frame.columns}
    company_column = next(
        (
            original
            for normalized, original in normalized_columns.items()
            if any(alias in normalized for alias in aliases)
        ),
        None,
    )
    if not company_column:
        raise ValueError("Keine Firmenspalte erkannt. Nutze zum Beispiel Account Name, Firma oder Unternehmen.")
    companies = {
        normalize_company(value)
        for value in frame[company_column].astype(str)
        if normalize_company(value)
    }
    return companies, company_column, len(frame)


def parse_regions(text: str) -> list[tuple[str, int]]:
    regions: list[tuple[str, int]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        city, radius = line.rsplit(",", 1)
        city = city.strip()
        radius_value = int(radius.strip())
        if not city or radius_value <= 0:
            raise ValueError
        regions.append((city, radius_value))
    if not regions:
        raise ValueError
    return regions


def next_term_batch(terms: list[str], batch_size: int, logs: pd.DataFrame) -> list[str]:
    if not terms:
        return []
    start = 0
    if not logs.empty:
        search_logs = logs[
            (logs["stage"] == "Suche")
            & (logs["status"].isin(["checkpoint", "fertig"]))
            & (logs["processed_terms"] != "")
        ]
        if not search_logs.empty:
            last_terms = [term.strip() for term in search_logs.iloc[-1]["processed_terms"].split("|") if term.strip()]
            if last_terms and last_terms[-1] in terms:
                start = (terms.index(last_terms[-1]) + 1) % len(terms)
    rotated = terms[start:] + terms[:start]
    return rotated[: min(batch_size, len(terms))]


def latest_scan_id(frame: pd.DataFrame) -> str:
    if frame.empty:
        return ""
    scan_ids = [
        str(value)
        for value in frame["scan_id"].unique().tolist()
        if re.fullmatch(r"\d{8}T\d{6}Z", str(value or ""))
    ]
    return max(scan_ids) if scan_ids else ""


openai_api_key = str(st.secrets.get("openai_api_key", "")).strip()
openai_model = str(st.secrets.get("openai_model", "gpt-5-mini")).strip() or "gpt-5-mini"
serpapi_key = str(st.secrets.get("serpapi_key", "")).strip()
adzuna_app_id = str(st.secrets.get("adzuna_app_id", "")).strip()
adzuna_api_key = str(st.secrets.get("adzuna_api_key", "")).strip()

st.sidebar.title("XING Daily Leads V6")
page = st.sidebar.radio(
    "Bereich",
    ["Daily Leads", "Stellen", "Kampagnen Feedback", "Follow ups", "Alle Leads", "Salesforce Abgleich", "CRM Ausschluss"],
)

st.sidebar.markdown("### Systemcheck")
if storage.mode == "google":
    storage_label = "Google Sheets"
elif storage.mode == "google_error":
    storage_label = "Google Sheets Fehler"
else:
    storage_label = "lokaler Testmodus"
st.sidebar.write(f"Speicher: {storage_label}")
if storage.mode == "local" and (
    "gcp_service_account" in st.secrets
    or _secret_text("spreadsheet_id")
    or _secret_text("spreadsheet_name")
):
    st.sidebar.warning(
        "Google Sheets ist nur teilweise konfiguriert. Benötigt werden "
        "gcp_service_account und spreadsheet_id oder spreadsheet_name."
    )
if storage.mode == "google":
    st.sidebar.caption(f"Verbunden mit: {storage.book_title}")
    if storage.book_url:
        st.sidebar.link_button("Verbundenes Google Sheet öffnen", storage.book_url)
st.sidebar.write(f"OpenAI Paket: {'bereit' if openai_available() else 'fehlt'}")
st.sidebar.write(f"OpenAI Key: {'hinterlegt' if openai_api_key else 'fehlt'}")
st.sidebar.write(f"SerpApi: {'hinterlegt' if serpapi_key else 'nicht hinterlegt'}")
st.sidebar.write(f"Adzuna: {'bereit' if adzuna_app_id and adzuna_api_key else 'Zugangsdaten fehlen'}")
active_schema_version = globals().get(
    "KMU_SCHEMA_VERSION",
    getattr(pipeline_module, "PIPELINE_SCHEMA_VERSION", "6.0.0"),
)
st.sidebar.caption(
    f"Kampagnen Schema: {active_schema_version} · "
    f"Pipeline: {getattr(pipeline_module, 'PIPELINE_SCHEMA_VERSION', 'älter')}"
)
st.sidebar.caption("Google Sheets Tabs: Leads · Stellen · CRM_Ausschluss · Scan_Log")

if storage.mode == "google_error":
    st.error(
        "Google Sheets ist konfiguriert, konnte aber nicht verbunden werden. "
        f"Fehler: {storage.error}"
    )
    st.stop()

if st.sidebar.button("Daten aus Google Sheets neu laden"):
    st.session_state.pop("xing_frame_cache", None)
    st.session_state.pop("xing_jobs_cache", None)
    st.session_state.pop("xing_exclusions_cache", None)
    st.session_state.pop("xing_logs_cache", None)
    st.rerun()

if "xing_frame_cache" not in st.session_state:
    st.session_state["xing_frame_cache"] = storage.load()
if "xing_jobs_cache" not in st.session_state:
    st.session_state["xing_jobs_cache"] = storage.load_jobs()
if "xing_exclusions_cache" not in st.session_state:
    st.session_state["xing_exclusions_cache"] = storage.load_exclusions()
if "xing_logs_cache" not in st.session_state:
    st.session_state["xing_logs_cache"] = storage.load_logs()

raw_frame = st.session_state["xing_frame_cache"].copy()
frame = migrate_frame(raw_frame)
jobs_frame = migrate_jobs_frame(st.session_state["xing_jobs_cache"].copy())
frame, schema_changed = ensure_kmu_schema(frame)
frame, subject_changed = ensure_exclusive_subjects(frame)
frame, quality_changed = refresh_quality(frame)
exclusions = set(st.session_state["xing_exclusions_cache"])
logs = st.session_state["xing_logs_cache"].copy()

if not frame.empty:
    legacy_mask = frame["first_seen_scan"].astype(str).str.strip().eq("")
    legacy_changed = bool(legacy_mask.any())
    if legacy_changed:
        frame.loc[legacy_mask, "first_seen_scan"] = "legacy"
        frame.loc[legacy_mask & frame["scan_id"].astype(str).str.strip().eq(""), "scan_id"] = "legacy"
    if schema_changed or legacy_changed or subject_changed or quality_changed:
        persist_full(frame)

# Einmalige Migration für bestehende Firmen: So ist der Google Sheets Tab Stellen
# nicht leer, obwohl frühere Versionen nur Firmen gespeichert haben.
if jobs_frame.empty and not frame.empty:
    reconstructed_jobs = backfill_jobs_from_leads(frame)
    if not reconstructed_jobs.empty:
        storage.save_jobs(reconstructed_jobs)
        jobs_frame = reconstructed_jobs.copy()
        st.session_state["xing_jobs_cache"] = jobs_frame.copy()
        st.info(
            f"Einmalig {len(jobs_frame)} Stellenzeilen aus bestehenden Leads rekonstruiert. "
            "Neue Scans ersetzen diese schrittweise durch exakte Quelldaten."
        )


if page == "Daily Leads":
    st.title("Daily Leads")
    st.caption("Breite Massenkampagne über alle relevanten Berufsgruppen. Kleine und mittelständische Direktkunden werden weiterhin priorisiert.")

    research_pending = len(research_candidate_indices(frame, max(1, len(frame)))) if not frame.empty else 0
    ai_pending = len(ai_candidate_indices(frame, max(1, len(frame)))) if not frame.empty else 0
    ready_mask = (
        (frame["quality_status"] == "Versandbereit")
        & (frame["email"] != "")
        & (frame["erstmail"] != "")
    ) if not frame.empty else pd.Series(dtype=bool)

    metric_columns = st.columns(6)
    metric_columns[0].metric("Gespeicherte Firmen", len(frame))
    metric_columns[1].metric("Gespeicherte Stellen", len(jobs_frame))
    small_count = int((frame.get("size_fit", pd.Series(index=frame.index, dtype=str)) == "Klein").sum()) if not frame.empty else 0
    metric_columns[2].metric("Kleine Direktkunden", small_count)
    metric_columns[3].metric("Recherche offen", research_pending)
    metric_columns[4].metric("Texte offen", ai_pending)
    metric_columns[5].metric("Verkaufsbereit", int(ready_mask.sum()) if not frame.empty else 0)

    with st.expander("Schritt 1: Stellen finden und Firmen sofort speichern", expanded=frame.empty):
        st.write(
            "Dieser Schritt sucht nur Stellen und speichert jede fertige Suchrunde sofort. "
            "Website Recherche und OpenAI laufen hier bewusst noch nicht."
        )
        campaign = st.selectbox(
            "Zielkunden Kampagne",
            list(CAMPAIGN_PRESETS.keys()),
            index=0,
            key="campaign_v60",
            help="Der Scanner filtert nicht nur nach Beruf, sondern auch nach kleiner Unternehmensstruktur.",
        )
        terms_text = st.text_area(
            "Suchbegriffe, eine Zeile je Begriff",
            "\n".join(CAMPAIGN_PRESETS[campaign]),
            key=f"terms_v60_{campaign}",
        )
        regions_text = st.text_area(
            "Regionen im Format Ort,Umkreis",
            "\n".join(f"{city},{radius}" for city, radius in DEFAULT_REGIONS),
            key="regions_v4",
        )

        source_columns = st.columns(4)
        use_adzuna = source_columns[0].checkbox("Adzuna", value=bool(adzuna_app_id and adzuna_api_key), key="source_adzuna_v4")
        use_ba = source_columns[1].checkbox("Bundesagentur", value=True, key="source_ba_v4")
        use_google = source_columns[2].checkbox("Google Jobs", value=bool(serpapi_key), key="source_google_v60")
        use_careers = source_columns[3].checkbox("Karriereseiten", value=False, key="source_careers_v4")

        career_urls_text = st.text_area(
            "Optionale echte Karriereseiten oder ATS Boards, eine URL je Zeile",
            placeholder=(
                "https://firma.jobs.personio.de\n"
                "https://boards.greenhouse.io/firma\n"
                "https://jobs.lever.co/firma\n"
                "https://firma.de/karriere"
            ),
            key="career_urls_v4",
        )

        settings_columns = st.columns(3)
        days = settings_columns[0].number_input("Veröffentlicht seit Tagen", 1, 30, 14, key="days_v4")
        max_pages = settings_columns[1].number_input("Seiten je Suche", 1, 3, 1, key="pages_v4")
        term_batch_size = settings_columns[2].number_input("Suchbegriffe pro Klick", 1, 20, 8, key="term_batch_v60")

        all_terms = [line.strip() for line in terms_text.splitlines() if line.strip()]
        upcoming_terms = next_term_batch(all_terms, int(term_batch_size), logs)
        st.info("Nächste Suchrunde: " + (", ".join(upcoming_terms) if upcoming_terms else "keine Begriffe"))
        st.caption(
            "Standardmäßig werden Unternehmen mit mehr als acht Stellen, mehr als drei Standorten, "
            "Kettenstrukturen oder stark gemischten Rollen aussortiert. Kontakte folgen in Schritt 2."
        )

        uploaded = st.file_uploader(
            "Optionaler Salesforce Export, vorhandene Firmen werden ausgeschlossen",
            type=["csv", "xlsx"],
            key="quick_crm_upload_v4",
        )
        if uploaded is not None:
            try:
                crm_companies, detected_column, row_count = read_company_file(uploaded)
                st.info(f"Firmenspalte erkannt: {detected_column}. Zeilen: {row_count}.")
                if st.button("CRM Firmen übernehmen", key="quick_crm_save_v4"):
                    try:
                        exclusions = persist_exclusions(set(exclusions) | crm_companies)
                        st.success(f"{len(crm_companies)} Firmen übernommen.")
                    except Exception as exc:
                        st.error(_google_action_error(exc))
            except Exception as exc:
                st.error(str(exc))

        if st.button("Schritt 1 starten", type="primary", key="start_discovery_v4"):
            try:
                regions = parse_regions(regions_text)
            except Exception:
                st.error("Mindestens eine Region hat nicht das Format Ort,Umkreis.")
                st.stop()

            sources: list[str] = []
            if use_adzuna:
                sources.append("Adzuna")
            if use_ba:
                sources.append("Bundesagentur")
            if use_google:
                sources.append("Google Jobs")
            if use_careers:
                sources.append("Karriereseiten")
            if not sources:
                st.error("Aktiviere mindestens eine Quelle.")
                st.stop()
            if use_adzuna and (not adzuna_app_id or not adzuna_api_key):
                st.error("Adzuna ist aktiviert, aber die Zugangsdaten fehlen.")
                st.stop()
            if use_google and not serpapi_key:
                st.error("Google Jobs ist aktiviert, aber der SerpApi Key fehlt.")
                st.stop()

            scan_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            terms_to_run = next_term_batch(all_terms, int(term_batch_size), logs)
            career_urls = [line.strip() for line in career_urls_text.splitlines() if line.strip()]
            append_log(
                scan_id=scan_id,
                stage="Suche",
                status="gestartet",
                processed_terms=" | ".join(terms_to_run),
                message=f"Suchrunde {campaign} gestartet. Ergebnisse werden nach jedem Begriff gespeichert.",
            )

            progress = st.progress(0, text="Suchrunde startet.")
            total_jobs = total_inserted = total_updated = 0
            total_job_inserted = total_job_updated = 0
            details: list[str] = []
            completed_terms: list[str] = []

            try:
                for position, term in enumerate(terms_to_run, start=1):
                    progress.progress(
                        (position - 1) / max(1, len(terms_to_run)),
                        text=f"Suche {position} von {len(terms_to_run)}: {term}",
                    )
                    term_sources = list(sources)
                    term_career_urls = career_urls
                    if position > 1 and "Karriereseiten" in term_sources:
                        term_sources.remove("Karriereseiten")
                        term_career_urls = []

                    parsed_jobs, scan_diagnostics = scan_jobs(
                        terms=[term],
                        regions=regions,
                        days=int(days),
                        max_pages=int(max_pages),
                        sources=term_sources,
                        career_urls=term_career_urls,
                        serpapi_key=serpapi_key,
                        adzuna_app_id=adzuna_app_id,
                        adzuna_api_key=adzuna_api_key,
                        ba_fetch_details=False,
                        focus=campaign,
                    )
                    eligible_jobs = [
                        job for job in parsed_jobs
                        if not crm_match(clean_text(job.get("company", "")), exclusions)
                    ]
                    fresh_job_rows = build_job_rows(
                        eligible_jobs,
                        scan_id=scan_id,
                        campaign=campaign,
                    )
                    jobs_frame, job_inserted, job_updated, changed_job_ids = upsert_jobs(
                        jobs_frame,
                        fresh_job_rows,
                        scan_id=scan_id,
                    )
                    changed_job_rows = jobs_frame[jobs_frame["job_id"].isin(changed_job_ids)].copy()
                    persist_job_rows(changed_job_rows, jobs_frame)

                    fresh, discovery_diagnostics = build_discovery_leads(
                        parsed_jobs=eligible_jobs,
                        exclusions=exclusions,
                        existing=frame,
                        scan_id=scan_id,
                        focus=campaign,
                    )
                    frame, inserted, updated, changed_ids = upsert_leads(frame, fresh, scan_id)
                    frame = apply_crm_status(frame, exclusions)
                    changed_rows = frame[frame["lead_id"].isin(changed_ids)].copy()
                    persist_rows(changed_rows, frame)

                    total_jobs += len(eligible_jobs)
                    total_job_inserted += job_inserted
                    total_job_updated += job_updated
                    total_inserted += inserted
                    total_updated += updated
                    completed_terms.append(term)
                    details.append(
                        f"{term}: {len(eligible_jobs)} priorisierte Stellen nach CRM Abgleich, "
                        f"{job_inserted} neue Stellenzeilen, {job_updated} Stellen aktualisiert, "
                        f"{inserted} neue Firmen, {updated} Firmen aktualisiert."
                    )
                    details.extend(f"{term}: {message}" for message in scan_diagnostics + discovery_diagnostics)
                    append_log(
                        scan_id=scan_id,
                        stage="Suche",
                        status="checkpoint",
                        processed_terms=" | ".join(completed_terms),
                        processed_items=str(position),
                        found_jobs=str(total_jobs),
                        new_leads=str(total_inserted),
                        updated_leads=str(total_updated),
                        message=(
                            f"{term} gespeichert: {job_inserted} neue Stellen, "
                            f"{job_updated} aktualisierte Stellen."
                        ),
                    )

                progress.progress(1.0, text="Suchrunde abgeschlossen und gespeichert.")
                append_log(
                    scan_id=scan_id,
                    stage="Suche",
                    status="fertig",
                    processed_terms=" | ".join(completed_terms),
                    processed_items=str(len(completed_terms)),
                    found_jobs=str(total_jobs),
                    new_leads=str(total_inserted),
                    updated_leads=str(total_updated),
                    message="Suchrunde vollständig abgeschlossen.",
                )
                st.session_state["last_pipeline_details"] = details
                st.success(
                    f"Gespeichert: {total_job_inserted} neue Stellenzeilen und {total_job_updated} aktualisierte Stellen "
                    f"im Google Sheet Tab Stellen. Zusätzlich {total_inserted} neue Firmen und "
                    f"{total_updated} aktualisierte Firmen im Tab Leads."
                )
            except Exception as exc:
                append_log(
                    scan_id=scan_id,
                    stage="Suche",
                    status="fehler",
                    processed_terms=" | ".join(completed_terms),
                    processed_items=str(len(completed_terms)),
                    found_jobs=str(total_jobs),
                    new_leads=str(total_inserted),
                    updated_leads=str(total_updated),
                    message=clean_text(exc),
                )
                st.session_state["last_pipeline_details"] = details + [f"Abbruch: {clean_text(exc)}"]
                st.error(
                    "Die Suchrunde wurde abgebrochen. Bereits fertige Begriffe sind trotzdem gespeichert. "
                    f"Fehler: {clean_text(exc)}"
                )
            finally:
                progress.empty()

    research_all = research_candidate_indices(frame, max(1, len(frame))) if not frame.empty else []
    with st.expander(f"Schritt 2: Website, Ansprechpartner, Mail und Telefon recherchieren ({len(research_all)} offen)"):
        st.write("Dieser Schritt bearbeitet nur bereits gespeicherte Firmen in kleinen Paketen.")
        research_limit = st.number_input("Firmen pro Recherchepaket", 1, 100, 20, key="research_limit_v7")
        if st.button("Schritt 2 starten", disabled=not research_all, key="start_research_v4"):
            indices = research_candidate_indices(frame, int(research_limit))
            run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            append_log(
                scan_id=run_id,
                stage="Recherche",
                status="gestartet",
                processed_items=str(len(indices)),
                message="Recherchepaket gestartet. Jede Firma wird einzeln gespeichert.",
            )
            progress = st.progress(0, text="Recherche startet.")
            details: list[str] = []
            websites = contacts = 0
            for position, index in enumerate(indices, start=1):
                company = frame.loc[index, "firma"]
                progress.progress((position - 1) / max(1, len(indices)), text=f"Recherche {position} von {len(indices)}: {company}")
                updated, diagnostics = enrich_lead(frame.loc[index].to_dict(), serpapi_key=serpapi_key)
                for column in COLUMNS:
                    frame.loc[index, column] = updated.get(column, frame.loc[index, column])
                persist_rows(frame.loc[[index]], frame)
                related_job_rows = sync_lead_contacts_to_jobs(frame.loc[index].to_dict(), jobs_frame)
                if not related_job_rows.empty:
                    jobs_frame = migrate_jobs_frame(st.session_state["xing_jobs_cache"].copy())
                    persist_job_rows(related_job_rows, jobs_frame)
                if frame.loc[index, "website"]:
                    websites += 1
                if frame.loc[index, "email"] or frame.loc[index, "telefon"]:
                    contacts += 1
                details.extend(diagnostics)
            progress.empty()
            append_log(
                scan_id=run_id,
                stage="Recherche",
                status="fertig",
                processed_items=str(len(indices)),
                message=f"Websites {websites}, direkte Kontakte {contacts}.",
            )
            st.session_state["last_pipeline_details"] = details
            st.success(f"Recherche abgeschlossen: {len(indices)} Firmen, {websites} Websites, {contacts} direkte Kontakte.")

    ai_all = ai_candidate_indices(frame, max(1, len(frame))) if not frame.empty else []
    with st.expander(f"Schritt 3: Individuelle Sales Texte erzeugen ({len(ai_all)} offen)"):
        st.write("OpenAI wird erst jetzt für die bereits gespeicherten und möglichst recherchierten Firmen genutzt.")
        ai_limit = st.number_input("Firmen pro Textpaket", 1, 30, 10, key="ai_limit_v4")
        if st.button("Schritt 3 starten", disabled=not ai_all, key="start_ai_v4"):
            indices = ai_candidate_indices(frame, int(ai_limit))
            run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            append_log(
                scan_id=run_id,
                stage="Texte",
                status="gestartet",
                processed_items=str(len(indices)),
                message="Textpaket gestartet. Jede Firma wird einzeln gespeichert.",
            )
            progress = st.progress(0, text="Texte werden erzeugt.")
            details: list[str] = []
            ai_created = 0
            for position, index in enumerate(indices, start=1):
                company = frame.loc[index, "firma"]
                progress.progress((position - 1) / max(1, len(indices)), text=f"Text {position} von {len(indices)}: {company}")
                updated, diagnostics = generate_lead_assets(
                    frame.loc[index].to_dict(),
                    api_key=openai_api_key,
                    model=openai_model,
                )
                updated["erstmail_betreff"] = exclusive_invitation_subject(company)
                for column in COLUMNS:
                    frame.loc[index, column] = updated.get(column, frame.loc[index, column])
                persist_rows(frame.loc[[index]], frame)
                if frame.loc[index, "ai_status"].startswith("KI erstellt"):
                    ai_created += 1
                details.extend(diagnostics)
            progress.empty()
            append_log(
                scan_id=run_id,
                stage="Texte",
                status="fertig",
                processed_items=str(len(indices)),
                message=f"KI Texte {ai_created}, Fallbacks {len(indices) - ai_created}.",
            )
            st.session_state["last_pipeline_details"] = details
            st.success(f"Textpaket abgeschlossen: {ai_created} KI Texte, {len(indices) - ai_created} Fallbacks.")

    with st.expander("Technische Details und Scan Verlauf", expanded=False):
        details = st.session_state.get("last_pipeline_details", [])
        if details:
            for message in details[-80:]:
                st.write(f"• {message}")
        else:
            st.caption("In dieser Browser Sitzung gibt es noch keine technischen Details.")
        current_logs = st.session_state.get("xing_logs_cache", pd.DataFrame(columns=LOG_COLUMNS))
        if not current_logs.empty:
            st.dataframe(current_logs.tail(30), width="stretch", hide_index=True)

    if frame.empty:
        st.info("Noch keine Leads vorhanden. Starte Schritt 1.")
    else:
        latest_scan = latest_scan_id(frame)
        latest_frame = frame[frame["scan_id"] == latest_scan].copy() if latest_scan else frame.copy()
        latest_frame = latest_frame[
            ~latest_frame["status"].isin(["In Salesforce übernommen", "Ausschließen"])
            & (latest_frame["crm_status"] != "Bereits in Salesforce")
            & (latest_frame["size_fit"] != "Groß oder unpassend")
        ].copy()
        latest_frame["score_num"] = pd.to_numeric(latest_frame["lead_score"], errors="coerce").fillna(0)
        latest_frame = latest_frame.sort_values("score_num", ascending=False)

        view_mode = st.radio(
            "Ansicht",
            ["Neu gefunden", "Verkaufsbereit", "Alle offenen Leads", "Kleine Direktkunden"],
            horizontal=True,
        )
        if view_mode == "Kleine Direktkunden":
            display_frame = frame[
                (frame["size_fit"] == "Klein")
                & (~frame["status"].isin(["In Salesforce übernommen", "Ausschließen"]))
                & (frame["crm_status"] != "Bereits in Salesforce")
            ].copy()
        elif view_mode == "Verkaufsbereit":
            display_frame = frame[
                (frame["quality_status"] == "Versandbereit")
                & (frame["email"] != "")
                & (frame["erstmail"] != "")
                & (~frame["status"].isin(["In Salesforce übernommen", "Ausschließen"]))
                & (frame["crm_status"] != "Bereits in Salesforce")
            ].copy()
        elif view_mode == "Neu gefunden":
            display_frame = latest_frame.copy()
        else:
            display_frame = frame[
                ~frame["status"].isin(["In Salesforce übernommen", "Ausschließen"])
                & (frame["crm_status"] != "Bereits in Salesforce")
            ].copy()
        display_frame["score_num"] = pd.to_numeric(display_frame["lead_score"], errors="coerce").fillna(0)
        display_frame["small_num"] = pd.to_numeric(display_frame["small_business_score"], errors="coerce").fillna(0)
        display_frame = display_frame.sort_values(
            ["small_num", "score_num"], ascending=[False, False]
        ).head(250)

        if display_frame.empty:
            st.info("In dieser Ansicht gibt es aktuell keine Leads.")

        for index, row in display_frame.iterrows():
            with st.container(border=True):
                header_columns = st.columns([5, 1.5, 1.5, 2])
                header_columns[0].subheader(row["firma"])
                header_columns[1].metric(row["hot_status"] or "COLD", int(float(row["lead_score"] or 0)))
                header_columns[2].metric("Qualität", int(float(row["quality_score"] or 0)))
                header_columns[3].write(row["quality_status"] or "Nicht freigeben")

                st.write(f"**Segment:** {row['lead_segment'] or 'Direktkunde'} · **Größenfit:** {row['size_fit'] or 'offen'}")
                st.write(f"**Stellenschwerpunkte:** {row['offene_stellen']}")
                st.write(f"**Warum interessant:** {row['warum_hot'] or 'noch keine belastbare Begründung'}")
                if row["personalization_evidence"]:
                    st.write(f"**Belegte Personalisierung:** {row['personalization_evidence']}")
                if row["quality_notes"]:
                    st.caption(f"Qualitätsprüfung: {row['quality_notes']}")
                if row["size_reason"]:
                    st.caption(f"Direktkunden Bewertung: {row['size_reason']}")
                if row["benefits"]:
                    st.write(f"**Benefits:** {row['benefits']}")
                st.caption(f"Quellen: {row['source_list'] or 'offen'} · bisher {row['times_seen'] or '1'} Mal gefunden")

                contact_columns = st.columns(4)
                contact_columns[0].write(f"**Ansprechpartner:** {row['ansprechpartner'] or 'nicht sicher gefunden'}")
                contact_columns[1].write(f"**E Mail:** {row['email'] or 'nicht gefunden'}")
                contact_columns[2].write(f"**E Mail Qualität:** {row['email_quality'] or 'Fehlt'}")
                contact_columns[3].write(f"**Telefon:** {row['telefon'] or 'nicht gefunden'}")
                st.caption(f"Recherche: {row['research_status'] or 'offen'} · Texte: {row['ai_status'] or 'offen'} · Variante: {row['mail_variant'] or 'offen'}")
                if row["last_error"]:
                    st.warning(row["last_error"])

                link_columns = st.columns(5)
                if row["website"]:
                    link_columns[0].link_button("Website", row["website"])
                if row["kontaktseite"]:
                    link_columns[1].link_button("Kontakt", row["kontaktseite"])
                if row["impressum"]:
                    link_columns[2].link_button("Impressum", row["impressum"])
                if row["karriereseite"]:
                    link_columns[3].link_button("Karriere", row["karriereseite"])
                if row["stellenlink"]:
                    link_columns[4].link_button("Stelle", row["stellenlink"])

                tabs = st.tabs(["Call", "Erstmail", "Follow ups", "Feedback", "Bearbeiten"])
                with tabs[0]:
                    call_value = st.text_area("Call Opener", row["call_opener"], height=120, key=f"call_{row['lead_id']}")
                    discovery_value = st.text_area("Discovery Fragen", row["discovery_fragen"], height=230, key=f"disc_{row['lead_id']}")
                    challenger_value = st.text_area("Challenger Reframe", row["challenger_reframe"], height=130, key=f"challenger_{row['lead_id']}")
                with tabs[1]:
                    subject_value = st.text_input("Betreff", row["erstmail_betreff"], key=f"subject_{row['lead_id']}")
                    mail_value = st.text_area("Mail", row["erstmail"], height=330, key=f"mail_{row['lead_id']}")
                with tabs[2]:
                    follow1_value = st.text_area("Follow up 1", row["follow_up_1"], height=220, key=f"follow1_{row['lead_id']}")
                    follow2_value = st.text_area("Follow up 2", row["follow_up_2"], height=220, key=f"follow2_{row['lead_id']}")
                with tabs[3]:
                    feedback_columns = st.columns(2)
                    sent_value = feedback_columns[0].text_input(
                        "Versendet am",
                        row["versendet_am"],
                        placeholder="2026 07 24",
                        key=f"sent_{row['lead_id']}",
                    )
                    response_options = ["", "Keine Antwort", "Positive Antwort", "Rückfrage", "Absage", "Termin vereinbart"]
                    current_response = row["antwort_status"] if row["antwort_status"] in response_options else ""
                    response_value = feedback_columns[1].selectbox(
                        "Antwortstatus",
                        response_options,
                        index=response_options.index(current_response),
                        key=f"response_{row['lead_id']}",
                    )
                    response_date_value = feedback_columns[0].text_input(
                        "Antwort am",
                        row["antwort_am"],
                        placeholder="2026 07 25",
                        key=f"response_date_{row['lead_id']}",
                    )
                    appointment_value = feedback_columns[1].text_input(
                        "Termin am",
                        row["termin_am"],
                        placeholder="2026 07 29 10:30",
                        key=f"appointment_{row['lead_id']}",
                    )
                    rejection_value = st.text_input(
                        "Absagegrund",
                        row["absagegrund"],
                        key=f"rejection_{row['lead_id']}",
                    )
                    response_note_value = st.text_area(
                        "Antwortnotiz",
                        row["antwort_notiz"],
                        key=f"response_note_{row['lead_id']}",
                    )
                    quick_columns = st.columns(2)
                    if quick_columns[0].button("Heute als versendet markieren", key=f"mark_sent_{row['lead_id']}"):
                        frame.loc[index, "versendet_am"] = date.today().isoformat()
                        frame.loc[index, "status"] = "Versendet"
                        persist_rows(frame.loc[[index]], frame)
                        st.success("Versand gespeichert.")
                    if quick_columns[1].button("Feedback speichern", key=f"save_feedback_{row['lead_id']}"):
                        frame.loc[index, "versendet_am"] = sent_value
                        frame.loc[index, "antwort_status"] = response_value
                        frame.loc[index, "antwort_am"] = response_date_value
                        frame.loc[index, "termin_am"] = appointment_value
                        frame.loc[index, "absagegrund"] = rejection_value
                        frame.loc[index, "antwort_notiz"] = response_note_value
                        if response_value == "Termin vereinbart":
                            frame.loc[index, "status"] = "Termin vereinbart"
                        elif response_value in {"Positive Antwort", "Rückfrage", "Absage"}:
                            frame.loc[index, "status"] = "Antwort erhalten"
                        elif sent_value and frame.loc[index, "status"] == "Neu":
                            frame.loc[index, "status"] = "Versendet"
                        persist_rows(frame.loc[[index]], frame)
                        st.success("Feedback gespeichert.")
                with tabs[4]:
                    status_value = st.selectbox(
                        "Status",
                        STATUSES,
                        index=STATUSES.index(row["status"]) if row["status"] in STATUSES else 0,
                        key=f"status_{row['lead_id']}",
                    )
                    parsed_due = pd.to_datetime(row["wiedervorlage"], errors="coerce")
                    due_default = parsed_due.date() if not pd.isna(parsed_due) else date.today() + timedelta(days=2)
                    due_value = st.date_input("Wiedervorlage", value=due_default, key=f"due_{row['lead_id']}")
                    note_value = st.text_area("Arbeitsnotiz", row["notiz"], key=f"note_{row['lead_id']}")
                    lock_value = st.checkbox(
                        "Meine Textänderungen bei künftigen Läufen beibehalten",
                        value=row["text_locked"] == "ja",
                        key=f"lock_{row['lead_id']}",
                    )
                    if st.button("Änderungen speichern", key=f"save_{row['lead_id']}"):
                        frame.loc[index, "call_opener"] = call_value
                        frame.loc[index, "discovery_fragen"] = discovery_value
                        frame.loc[index, "challenger_reframe"] = challenger_value
                        frame.loc[index, "erstmail_betreff"] = subject_value
                        frame.loc[index, "erstmail"] = mail_value
                        frame.loc[index, "follow_up_1"] = follow1_value
                        frame.loc[index, "follow_up_2"] = follow2_value
                        frame.loc[index, "status"] = status_value
                        frame.loc[index, "wiedervorlage"] = due_value.isoformat()
                        frame.loc[index, "notiz"] = note_value
                        frame.loc[index, "text_locked"] = "ja" if lock_value else ""
                        quality_score, quality_status, quality_notes = evaluate_lead_quality(frame.loc[index].to_dict())
                        frame.loc[index, "quality_score"] = str(quality_score)
                        frame.loc[index, "quality_status"] = quality_status
                        frame.loc[index, "quality_notes"] = quality_notes
                        try:
                            persist_rows(frame.loc[[index]], frame)
                            if status_value in {"Ausschließen", "In Salesforce übernommen"}:
                                exclusions = persist_exclusions(set(exclusions) | {row["firma"]})
                            st.success("Gespeichert.")
                        except Exception as exc:
                            st.error(_google_action_error(exc))

elif page == "Stellen":
    st.title("Stellen")
    st.caption(
        "Eine Zeile pro gefundener Vakanz. Dieselben Daten stehen dauerhaft im Google Sheets Tab Stellen."
    )
    if jobs_frame.empty:
        st.info("Noch keine Stellen gespeichert. Starte in Daily Leads Schritt 1.")
    else:
        metric_columns = st.columns(4)
        metric_columns[0].metric("Stellen", len(jobs_frame))
        metric_columns[1].metric("Unternehmen", jobs_frame["firma"].nunique())
        metric_columns[2].metric("Kleine Direktkunden", int((jobs_frame["size_fit"] == "Klein").sum()))
        metric_columns[3].metric(
            "Mit Kontakt",
            int(((jobs_frame["email"] != "") | (jobs_frame["telefon"] != "")).sum()),
        )

        search = st.text_input("Stellen durchsuchen", key="jobs_search_v5")
        filter_columns = st.columns(3)
        campaigns = ["Alle"] + sorted([value for value in jobs_frame["kampagne"].unique() if value])
        campaign_filter = filter_columns[0].selectbox("Kampagne", campaigns, key="jobs_campaign_v5")
        size_options = ["Alle"] + sorted([value for value in jobs_frame["size_fit"].unique() if value])
        size_filter = filter_columns[1].selectbox("Unternehmensgröße", size_options, key="jobs_size_v5")
        source_values = sorted({
            part.strip()
            for value in jobs_frame["quelle"].astype(str)
            for part in value.split("|")
            if part.strip()
        })
        source_filter = filter_columns[2].selectbox("Quelle", ["Alle"] + source_values, key="jobs_source_v5")

        filtered_jobs = jobs_frame.copy()
        if search:
            mask = filtered_jobs.astype(str).apply(
                lambda column: column.str.contains(search, case=False, na=False)
            ).any(axis=1)
            filtered_jobs = filtered_jobs[mask]
        if campaign_filter != "Alle":
            filtered_jobs = filtered_jobs[filtered_jobs["kampagne"] == campaign_filter]
        if size_filter != "Alle":
            filtered_jobs = filtered_jobs[filtered_jobs["size_fit"] == size_filter]
        if source_filter != "Alle":
            filtered_jobs = filtered_jobs[
                filtered_jobs["quelle"].str.contains(source_filter, case=False, na=False, regex=False)
            ]

        table_columns = [
            "firma", "position", "ort", "veroeffentlicht_am", "quelle", "suchbegriff",
            "stellenlink", "lead_segment", "size_fit", "small_business_score", "lead_score",
            "ansprechpartner", "email", "telefon", "first_seen", "last_seen", "times_seen",
            "kampagne", "status", "notiz",
        ]
        table = filtered_jobs.reindex(columns=table_columns).copy()
        table["small_business_score"] = pd.to_numeric(
            table["small_business_score"], errors="coerce"
        ).fillna(0).astype(int)
        table["lead_score"] = pd.to_numeric(table["lead_score"], errors="coerce").fillna(0).astype(int)
        st.dataframe(
            table,
            width="stretch",
            hide_index=True,
            column_config={
                "stellenlink": st.column_config.LinkColumn("Stellenanzeige"),
                "small_business_score": st.column_config.NumberColumn("Direktkunden Score", format="%d"),
                "lead_score": st.column_config.NumberColumn("Sales Score", format="%d"),
            },
        )
        st.caption(f"Angezeigt: {len(filtered_jobs)} von {len(jobs_frame)} Stellen.")
        export_csv = filtered_jobs.reindex(columns=JOB_COLUMNS).to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "Stellen als CSV herunterladen",
            export_csv,
            file_name=f"xing_stellen_{date.today().isoformat()}.csv",
            mime="text/csv",
        )

elif page == "Kampagnen Feedback":
    st.title("Kampagnen Feedback")
    st.caption("Die Auswertung basiert ausschließlich auf von dir gespeicherten Versand und Antwortdaten.")
    sent = frame[frame["versendet_am"].astype(str).str.strip() != ""].copy()
    answered = sent[
        sent["antwort_status"].isin(["Positive Antwort", "Rückfrage", "Absage", "Termin vereinbart"])
    ].copy()
    positive = sent[sent["antwort_status"].isin(["Positive Antwort", "Termin vereinbart"])].copy()
    appointments = sent[sent["antwort_status"] == "Termin vereinbart"].copy()

    response_rate = (len(answered) / len(sent) * 100) if len(sent) else 0
    positive_rate = (len(positive) / len(sent) * 100) if len(sent) else 0
    appointment_rate = (len(appointments) / len(sent) * 100) if len(sent) else 0

    metrics = st.columns(6)
    metrics[0].metric("Versendet", len(sent))
    metrics[1].metric("Antworten", len(answered))
    metrics[2].metric("Antwortquote", f"{response_rate:.1f} %")
    metrics[3].metric("Positive Antworten", len(positive))
    metrics[4].metric("Termine", len(appointments))
    metrics[5].metric("Terminquote", f"{appointment_rate:.1f} %")

    if sent.empty:
        st.info("Noch keine Versanddaten gespeichert. Markiere Leads im Feedback Tab als versendet.")
    else:
        st.subheader("Leistung nach Segment")
        segment_rows = []
        for segment, group in sent.groupby(sent["lead_segment"].replace("", "Direktkunde")):
            group_answered = group[group["antwort_status"].isin(["Positive Antwort", "Rückfrage", "Absage", "Termin vereinbart"])]
            group_positive = group[group["antwort_status"].isin(["Positive Antwort", "Termin vereinbart"])]
            group_appointments = group[group["antwort_status"] == "Termin vereinbart"]
            segment_rows.append({
                "Segment": segment,
                "Versendet": len(group),
                "Antworten": len(group_answered),
                "Antwortquote": round(len(group_answered) / len(group) * 100, 1),
                "Positive Antworten": len(group_positive),
                "Termine": len(group_appointments),
                "Terminquote": round(len(group_appointments) / len(group) * 100, 1),
            })
        segment_table = pd.DataFrame(segment_rows).sort_values(
            ["Termine", "Positive Antworten", "Antwortquote"], ascending=[False, False, False]
        )
        st.dataframe(segment_table, width="stretch", hide_index=True)

        st.subheader("Leistung nach Mailvariante")
        variant_rows = []
        for variant, group in sent.groupby(sent["mail_variant"].replace("", "Ohne Kennzeichnung")):
            group_answered = group[group["antwort_status"].isin(["Positive Antwort", "Rückfrage", "Absage", "Termin vereinbart"])]
            group_appointments = group[group["antwort_status"] == "Termin vereinbart"]
            variant_rows.append({
                "Mailvariante": variant,
                "Versendet": len(group),
                "Antworten": len(group_answered),
                "Antwortquote": round(len(group_answered) / len(group) * 100, 1),
                "Termine": len(group_appointments),
                "Terminquote": round(len(group_appointments) / len(group) * 100, 1),
            })
        variant_table = pd.DataFrame(variant_rows).sort_values(
            ["Termine", "Antwortquote"], ascending=[False, False]
        )
        st.dataframe(variant_table, width="stretch", hide_index=True)

        st.subheader("Letzte Rückmeldungen")
        feedback_table = sent[
            [
                "firma", "lead_segment", "mail_variant", "versendet_am", "antwort_status",
                "antwort_am", "termin_am", "absagegrund", "antwort_notiz",
            ]
        ].copy()
        feedback_table = feedback_table.sort_values(["antwort_am", "versendet_am"], ascending=False)
        st.dataframe(feedback_table.head(200), width="stretch", hide_index=True)

elif page == "Follow ups":
    st.title("Follow ups")
    today = date.today().isoformat()
    due_frame = frame[
        (frame["wiedervorlage"] != "")
        & (frame["wiedervorlage"] <= today)
        & (~frame["status"].isin(["In Salesforce übernommen", "Ausschließen"]))
    ].copy()
    if due_frame.empty:
        st.success("Keine Follow ups fällig.")
    else:
        for index, row in due_frame.iterrows():
            with st.container(border=True):
                st.subheader(row["firma"])
                st.write(f"**Fällig:** {row['wiedervorlage']} · **Status:** {row['status']}")
                st.write(f"**Kontakt:** {row['ansprechpartner']} · {row['email']} · {row['telefon']}")
                st.text_area("Follow up", row["follow_up_1"], height=240, key=f"due_mail_{row['lead_id']}")
                action_columns = st.columns(2)
                if action_columns[0].button("In Salesforce übernommen", key=f"sf_{row['lead_id']}"):
                    frame.loc[index, "status"] = "In Salesforce übernommen"
                    persist_rows(frame.loc[[index]], frame)
                    st.rerun()
                if action_columns[1].button("Noch drei Tage", key=f"plus3_{row['lead_id']}"):
                    frame.loc[index, "wiedervorlage"] = (date.today() + timedelta(days=3)).isoformat()
                    persist_rows(frame.loc[[index]], frame)
                    st.rerun()

elif page == "Alle Leads":
    st.title("Alle Leads")
    search = st.text_input("Suche")
    filtered = frame.copy()
    if search:
        mask = filtered.astype(str).apply(
            lambda column: column.str.contains(search, case=False, na=False)
        ).any(axis=1)
        filtered = filtered[mask]
    table = filtered[[
        "hot_status", "lead_score", "quality_score", "quality_status", "small_business_score",
        "firma", "lead_segment", "size_fit", "pipeline_stage", "crm_status", "anzahl_stellen",
        "offene_stellen", "orte", "ansprechpartner", "rolle", "email", "email_quality", "telefon",
        "website", "research_status", "ai_status", "mail_variant", "status", "wiedervorlage",
        "versendet_am", "antwort_status", "antwort_am", "termin_am", "first_seen", "zuletzt_gefunden", "times_seen",
    ]].copy()
    table["lead_score"] = pd.to_numeric(table["lead_score"], errors="coerce").fillna(0).astype(int)
    table["quality_score"] = pd.to_numeric(table["quality_score"], errors="coerce").fillna(0).astype(int)
    table["small_business_score"] = pd.to_numeric(table["small_business_score"], errors="coerce").fillna(0).astype(int)
    st.dataframe(
        table,
        width="stretch",
        hide_index=True,
        column_config={
            "website": st.column_config.LinkColumn("Website"),
            "lead_score": st.column_config.NumberColumn("Sales Score", format="%d"),
            "quality_score": st.column_config.NumberColumn("Qualität", format="%d"),
            "small_business_score": st.column_config.NumberColumn("Direktkunden Score", format="%d"),
        },
    )
    export_csv = filtered.reindex(columns=COLUMNS).to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "Gefilterte Tabelle als CSV herunterladen",
        export_csv,
        file_name=f"xing_sales_leads_{date.today().isoformat()}.csv",
        mime="text/csv",
    )

elif page == "Salesforce Abgleich":
    st.title("Salesforce Abgleich")
    st.write("Lade einen Salesforce Account Export als CSV oder XLSX hoch. Vorhandene Firmen werden dauerhaft ausgeschlossen.")
    crm_file = st.file_uploader("Salesforce Export hochladen", type=["csv", "xlsx"], key="salesforce_export_v4")
    if crm_file is not None:
        try:
            crm_companies, detected_column, row_count = read_company_file(crm_file)
            matches = {
                normalize_company(company)
                for company in frame.get("firma", [])
                if crm_match(company, crm_companies)
            }
            metric_columns = st.columns(3)
            metric_columns[0].metric("Zeilen im Export", row_count)
            metric_columns[1].metric("Eindeutige Firmen", len(crm_companies))
            metric_columns[2].metric("Treffer in Leadliste", len(matches))
            st.info(f"Erkannte Firmenspalte: {detected_column}")
            if st.button("Salesforce Firmen dauerhaft abgleichen"):
                combined = set(exclusions) | crm_companies
                exclusions = persist_exclusions(combined)
                frame = apply_crm_status(frame, exclusions)
                persist_full(frame)
                st.success(f"{len(crm_companies)} Salesforce Firmen gespeichert.")
        except Exception as exc:
            st.error(str(exc))

elif page == "CRM Ausschluss":
    st.title("CRM Ausschluss")
    st.caption("Diese Firmen werden bei neuen Suchläufen nicht mehr als Leads angelegt.")
    manual = st.text_area("Firmen hinzufügen, eine Zeile je Firma")
    if st.button("Firmen speichern"):
        new_items = {normalize_company(value) for value in manual.splitlines() if value.strip()}
        try:
            exclusions = persist_exclusions(set(exclusions) | new_items)
            st.success("Ausschlussliste aktualisiert.")
        except Exception as exc:
            st.error(_google_action_error(exc))
    st.write(f"**Aktuell gespeichert:** {len(exclusions)} Firmen")
    if exclusions:
        st.dataframe(pd.DataFrame({"Firma normalisiert": sorted(exclusions)}), hide_index=True)
