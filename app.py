from __future__ import annotations

import hashlib
import re
import time
import traceback
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd
import streamlit as st

import xing_pipeline as pipeline_module
from xing_pipeline import (
    ASSET_KEYS,
    COLUMNS,
    JOB_COLUMNS,
    STATUSES,
    ai_candidate_indices,
    apply_crm_status,
    company_match_keys,
    expand_crm_exclusions,
    backfill_jobs_from_leads,
    build_discovery_leads,
    build_job_rows,
    clean_text,
    crm_match,
    enrich_lead,
    evaluate_lead_quality,
    diamond_candidate_mask,
    generate_lead_assets,
    migrate_frame,
    migrate_jobs_frame,
    normalize_company,
    research_candidate_indices,
    refresh_quality,
    strict_send_ready_mask,
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
    "Diamanten Radar | kleine Direktkunden": [
        # Firmenradar: Nicht nur offene Stellen suchen, sondern lokale Betriebe direkt finden
        # und deren eigene Websites sowie Karrierebereiche analysieren.
        "Physiotherapeut", "Ergotherapeut", "Logopäde",
        "Elektroniker", "Anlagenmechaniker SHK", "Kältetechniker", "Dachdecker",
        "Tischler", "Metallbauer", "Mechatroniker", "Industriemechaniker",
        "Steuerfachangestellte", "Rechtsanwaltsfachangestellte",
        "Bauleiter", "Projektingenieur", "TGA Planer", "Bauzeichner",
        "Softwareentwickler", "Systemadministrator",
        "Berufskraftfahrer", "Disponent", "Fachkraft für Lagerlogistik",
    ],
    "Montagswelle 500 | Testpilot Fachkräfte": [
        # Engpass plus erreichbare Entscheider: Therapie, Pflege, Handwerk, Technik,
        # Engineering, Steuer und Logistik. Keine beliebige Massenliste.
        "Physiotherapeut", "Ergotherapeut", "Logopäde",
        "Pflegefachkraft ambulant", "Medizinische Fachangestellte", "Zahnmedizinische Fachangestellte",
        "Elektroniker", "Anlagenmechaniker SHK", "Mechatroniker", "Kältetechniker",
        "Dachdecker", "Servicetechniker", "Landmaschinenmechatroniker",
        "Bauleiter", "Projektingenieur", "TGA Planer", "Bauzeichner",
        "Steuerfachangestellte", "Steuerfachwirt", "Bilanzbuchhalter", "Lohnbuchhalter",
        "Fachkraft für Lagerlogistik", "Berufskraftfahrer", "Disponent",
        "Industriemechaniker", "Zerspanungsmechaniker", "CNC Fräser",
    ],
    "Testpilot Therapie 500": [
        "Physiotherapeut", "Physiotherapeutin", "Physiotherapie",
        "Ergotherapeut", "Ergotherapeutin", "Ergotherapie",
        "Logopäde", "Logopädin", "Logopädie",
        "Sprachtherapeut", "Sprachtherapeutin",
        "Atem Sprech Stimmlehrer",
        "Praxisleitung Physiotherapie", "Fachliche Leitung Physiotherapie",
        "Therapeutische Leitung",
    ],
    "Chancenmix Architektur Ingenieurwesen Steuer IT": [
        # Absichtlich gemischt. Schon der erste Klick liefert vier unterschiedliche Zielmärkte.
        "Architekt", "Steuerfachangestellte", "Softwareentwickler", "Bauleiter",
        "Projektingenieur", "Bilanzbuchhalter", "Systemadministrator", "TGA Planer",
        "Elektroingenieur", "Steuerfachwirt", "DevOps Engineer", "BIM Manager",
        "Konstrukteur", "Lohnbuchhalter", "IT Administrator", "Bauzeichner",
        "Versorgungsingenieur", "Finanzbuchhalter", "Fachinformatiker", "Projektleiter Architektur",
        "Landschaftsarchitekt", "Steuerberater", "SAP Berater", "Innenarchitekt",
    ],
    "Architektur und Planung": [
        "Architekt", "Projektleiter Architektur", "Bauzeichner", "BIM Manager",
        "Innenarchitekt", "Landschaftsarchitekt", "Stadtplaner", "Architekt Bauleitung",
    ],
    "Kleine Ingenieurbüros": [
        "Bauleiter", "Projektingenieur", "Konstrukteur", "TGA Planer",
        "Elektroingenieur", "Versorgungsingenieur", "Projektleiter Bau",
    ],
    "Steuerkanzleien": [
        "Steuerfachangestellte", "Steuerfachwirt", "Bilanzbuchhalter",
        "Lohnbuchhalter", "Finanzbuchhalter", "Steuerberater",
    ],
    "Kleine IT Unternehmen": [
        "Softwareentwickler", "Systemadministrator", "DevOps Engineer",
        "IT Support", "IT Administrator", "Fachinformatiker", "SAP Berater",
    ],
    "Breite Massenkampagne": [
        # Die chancenstarken Zielmärkte stehen bewusst vor Therapie und Pflege.
        "Architekt", "Steuerfachangestellte", "Softwareentwickler", "Bauleiter",
        "Projektingenieur", "Bilanzbuchhalter", "Systemadministrator", "TGA Planer",
        "Elektroingenieur", "Steuerfachwirt", "DevOps Engineer", "BIM Manager",
        "Konstrukteur", "Lohnbuchhalter", "IT Administrator", "Bauzeichner",
        "Versorgungsingenieur", "Finanzbuchhalter", "Fachinformatiker", "Projektleiter Architektur",
        "Landschaftsarchitekt", "Steuerberater", "SAP Berater", "Innenarchitekt",
        "Elektroniker", "Mechatroniker", "Anlagenmechaniker SHK", "Servicetechniker",
        "Industriemechaniker", "Schweißer", "Tischler", "Metallbauer", "Kältetechniker",
        "Vertriebsmitarbeiter", "Sales Manager", "Account Manager", "Key Account Manager",
        "Außendienstmitarbeiter", "Business Development Manager", "Einkäufer",
        "Physiotherapeut", "Ergotherapeut", "Logopäde", "Pflegefachkraft",
        "Medizinische Fachangestellte", "Zahnmedizinische Fachangestellte",
        "Berufskraftfahrer", "Disponent", "Fachkraft für Lagerlogistik",
        "Produktionsmitarbeiter", "Maschinenbediener", "Zerspanungsmechaniker",
        "Personalreferent", "Recruiter", "HR Business Partner", "Sachbearbeiter",
    ],
    "Therapiepraxen": [
        "Physiotherapeut", "Ergotherapeut", "Logopäde", "Sprachtherapeut",
        "Praxisleitung Therapie", "Therapeutische Leitung",
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

MONDAY_WAVE_REGIONS = [
    ("Hamburg", 120), ("Kiel", 100), ("Lübeck", 90), ("Bremen", 110),
    ("Hannover", 110), ("Osnabrück", 100), ("Münster", 100), ("Bielefeld", 100),
    ("Dortmund", 90), ("Essen", 85), ("Düsseldorf", 85), ("Köln", 90),
    ("Aachen", 90), ("Koblenz", 100), ("Frankfurt am Main", 100), ("Mannheim", 90),
    ("Saarbrücken", 100), ("Karlsruhe", 90), ("Stuttgart", 100), ("Freiburg im Breisgau", 100),
    ("Nürnberg", 105), ("Würzburg", 100), ("Regensburg", 100), ("München", 115),
    ("Augsburg", 90), ("Erfurt", 105), ("Leipzig", 105), ("Dresden", 105),
    ("Magdeburg", 110), ("Berlin", 120), ("Potsdam", 90), ("Rostock", 120),
]

TESTPILOT_THERAPY_REGIONS = [
    ("Hamburg", 120), ("Bremen", 100), ("Hannover", 110), ("Kiel", 100),
    ("Rostock", 120), ("Berlin", 130), ("Potsdam", 90), ("Magdeburg", 110),
    ("Leipzig", 110), ("Dresden", 110), ("Erfurt", 110), ("Kassel", 110),
    ("Nürnberg", 110), ("München", 130), ("Augsburg", 90), ("Stuttgart", 120),
    ("Freiburg im Breisgau", 100), ("Frankfurt am Main", 120), ("Mannheim", 100),
    ("Saarbrücken", 100), ("Köln", 110), ("Düsseldorf", 100), ("Dortmund", 100),
    ("Münster", 100), ("Bielefeld", 100),
]

CAMPAIGN_REGIONS = {
    "Diamanten Radar | kleine Direktkunden": MONDAY_WAVE_REGIONS,
    "Montagswelle 500 | Testpilot Fachkräfte": MONDAY_WAVE_REGIONS,
    "Testpilot Therapie 500": TESTPILOT_THERAPY_REGIONS,
}

CAMPAIGN_TARGETS = {
    "Diamanten Radar | kleine Direktkunden": 500,
    "Montagswelle 500 | Testpilot Fachkräfte": 500,
    "Testpilot Therapie 500": 500,
}

MONDAY_SEGMENT_QUOTAS = {
    "Therapiepraxis": 110,
    "Handwerk und Technik": 110,
    "Pflege und Medizin": 80,
    "Steuer und Buchhaltung": 70,
    "Bau und Engineering": 55,
    "Industrie und Produktion": 45,
    "Logistik und Einkauf": 30,
}

def balanced_monday_ready(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return migrate_frame(pd.DataFrame())
    work = migrate_frame(frame)
    work = work[strict_send_ready_mask(work)].copy()
    if work.empty:
        return work
    work["quality_num"] = pd.to_numeric(work["quality_score"], errors="coerce").fillna(0)
    work["lead_num"] = pd.to_numeric(work["lead_score"], errors="coerce").fillna(0)
    selected = []
    for segment, quota in MONDAY_SEGMENT_QUOTAS.items():
        chunk = work[work["lead_segment"] == segment].sort_values(
            ["quality_num", "lead_num", "firma"], ascending=[False, False, True]
        ).head(quota)
        if not chunk.empty:
            selected.append(chunk)
    if not selected:
        return work.iloc[0:0].drop(columns=["quality_num", "lead_num"], errors="ignore")
    result = pd.concat(selected, ignore_index=True)
    return result.drop(columns=["quality_num", "lead_num"], errors="ignore")


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

KMU_SCHEMA_VERSION = "11.2.0"


def exclusive_invitation_subject(company: Any) -> str:
    company_text = clean_text(company)
    return f"Exklusive Einladung | {company_text}" if company_text else "Exklusive Einladung"


def expected_subject(row: pd.Series | dict[str, Any]) -> str:
    discovery_kind = clean_text(row.get("discovery_kind", ""))
    titles = clean_text(row.get("job_titles", ""))
    if discovery_kind == "Firmenradar" and not titles:
        return "Frage zur Personalgewinnung"
    return exclusive_invitation_subject(row.get("firma", ""))


def ensure_exclusive_subjects(frame: pd.DataFrame | None) -> tuple[pd.DataFrame, bool]:
    # Historischer Funktionsname bleibt für Kompatibilität erhalten. Inhaltlich
    # wird jetzt der zur Leadart passende Betreff gesetzt.
    result = frame.copy() if frame is not None else pd.DataFrame()
    if result.empty or "firma" not in result.columns:
        return result, False
    if "erstmail_betreff" not in result.columns:
        result["erstmail_betreff"] = ""
    changed = False
    for index, row in result.iterrows():
        target = expected_subject(row)
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


def safe_int(value: Any, default: int = 0) -> int:
    """Wandelt Werte aus Google Sheets robust in ganze Zahlen um."""
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text:
        return default
    text = text.replace(" ", "").replace(".", "").replace(",", ".")
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return default


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
        ("Ingenieurbüro", ("ingenieur", "planungsbüro", "planungsbuero", "bauleiter", "konstrukteur", "tga", "architekt", "bauzeichner", "bim", "stadtplan", "landschaftsarchitekt", "innenarchitekt")),
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
        self.log_next_row = 2
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
                result = expand_crm_exclusions(frame.get("firma", []))
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
            result = expand_crm_exclusions(
                row[0] for row in values[start_index:] if row and row[0]
            )
        self._exclusions_cache = set(result)
        return result

    def save_exclusions(self, companies: set[str]) -> set[str]:
        """Speichert Ausschlüsse additiv statt das ganze Blatt neu zu schreiben.

        Die Ausschlussliste ist absichtlich monoton: Neue Firmen werden in einem
        einzigen Batch angehängt. Dadurch entstehen weder Clear-Requests noch ein
        vollständiges Rewrite bei jedem einzelnen Klick.
        """
        target = expand_crm_exclusions(companies)
        if self.mode == "google_error":
            raise RuntimeError(self.error or "Google Sheets ist nicht verbunden.")
        if self.mode == "local":
            existing = self._exclusions_cache if self._exclusions_cache is not None else self.load_exclusions()
            combined = set(existing) | expand_crm_exclusions(target)
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

    @staticmethod
    def _recover_log_records(values: list[list[str]]) -> list[list[str]]:
        """Rekonstruiert alte, horizontal verrutschte Scan Logs.

        Frühere Versionen nutzten append_row ohne stabile Kopfzeile. Google Sheets
        erkannte deshalb bei jedem Aufruf eine neue Tabelle weiter rechts. Wir suchen
        in jeder Zeile nach einem ISO Zeitstempel und übernehmen die folgenden Felder.
        """
        records: list[list[str]] = []
        timestamp_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
        width = len(LOG_COLUMNS)
        for raw_row in values:
            row = [clean_text(value) for value in raw_row]
            for start, value in enumerate(row):
                if not timestamp_pattern.match(value):
                    continue
                candidate = row[start : start + width]
                candidate += [""] * max(0, width - len(candidate))
                if candidate[1] or candidate[2] or candidate[3]:
                    records.append(candidate[:width])
                break
        return records

    def load_logs(self) -> pd.DataFrame:
        if self.mode == "google_error":
            raise RuntimeError(self.error or "Google Sheets ist nicht verbunden.")
        if self.mode == "local":
            try:
                frame = pd.read_csv(self.local_log_path, dtype=str).fillna("")
            except FileNotFoundError:
                frame = pd.DataFrame(columns=LOG_COLUMNS)
            self.log_next_row = len(frame) + 2
            return frame.reindex(columns=LOG_COLUMNS).fillna("")

        values = _google_call(self.log_ws.get_all_values)
        header_ok = bool(values and [clean_text(value) for value in values[0][: len(LOG_COLUMNS)]] == LOG_COLUMNS)
        if header_ok:
            records = []
            for raw_row in values[1:]:
                row = [clean_text(value) for value in raw_row[: len(LOG_COLUMNS)]]
                row += [""] * max(0, len(LOG_COLUMNS) - len(row))
                if any(row):
                    records.append(row[: len(LOG_COLUMNS)])
        else:
            records = self._recover_log_records(values)
            _google_call(self.log_ws.clear)
            payload = [LOG_COLUMNS] + records
            _google_call(self.log_ws.update, payload, "A1")

        self.log_next_row = len(records) + 2
        return pd.DataFrame(records, columns=LOG_COLUMNS).fillna("")

    def append_log(self, record: dict[str, Any]) -> None:
        row = [clean_text(record.get(column, "")) for column in LOG_COLUMNS]
        if self.mode == "google_error":
            raise RuntimeError(self.error or "Google Sheets ist nicht verbunden.")
        if self.mode == "local":
            current = self.load_logs()
            current.loc[len(current)] = row
            current.to_csv(self.local_log_path, index=False)
            self.log_next_row = len(current) + 2
            return

        end_column = _column_letter(len(LOG_COLUMNS))
        target_row = max(2, int(self.log_next_row or 2))
        _google_call(
            self.log_ws.update,
            [row],
            f"A{target_row}:{end_column}{target_row}",
            value_input_option="RAW",
        )
        self.log_next_row = target_row + 1


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


def _find_column(frame: pd.DataFrame, aliases: list[str]) -> str | None:
    normalized_columns = {normalize_company(column): column for column in frame.columns}
    return next(
        (
            original
            for normalized, original in normalized_columns.items()
            if any(alias in normalized for alias in aliases)
        ),
        None,
    )


def _crm_domain(value: str) -> str:
    text = clean_text(value).lower().strip()
    if not text:
        return ""
    if "@" in text and "://" not in text:
        text = text.rsplit("@", 1)[-1]
    text = re.sub(r"^https?://", "", text)
    text = text.split("/", 1)[0].split(":", 1)[0].strip(". ")
    text = text[4:] if text.startswith("www.") else text
    generic = {
        "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "gmx.de",
        "gmx.net", "web.de", "icloud.com", "yahoo.com", "yahoo.de", "t-online.de",
    }
    if "." not in text or text in generic:
        return ""
    return text


def _crm_phone(value: str) -> str:
    digits = re.sub(r"\D", "", clean_text(value))
    if len(digits) < 8:
        return ""
    return digits[-10:]


def read_company_file(uploaded_file):
    """Liest einen Salesforce Export als Identitätsindex.

    Neben Account Name werden, falls vorhanden, Website, E Mail und Telefon
    berücksichtigt. Das reduziert Treffer, bei denen derselbe Account in einer
    Jobbörse unter einer leicht anderen Schreibweise auftaucht.
    """
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

    company_column = _find_column(frame, [
        "account name", "account", "firmenname", "firma", "unternehmen",
        "company", "name des accounts", "kunde", "kundenname",
    ])
    if not company_column:
        raise ValueError("Keine Firmenspalte erkannt. Nutze zum Beispiel Account Name, Firma oder Unternehmen.")

    website_column = _find_column(frame, ["website", "webseite", "homepage", "domain", "internet"])
    email_column = _find_column(frame, ["e mail", "email", "mail adresse", "email adresse"])
    phone_column = _find_column(frame, ["telefon", "phone", "telefonnummer", "zentrale"])

    identities = expand_crm_exclusions(
        value for value in frame[company_column].astype(str) if normalize_company(value)
    )
    if website_column:
        identities.update(
            f"@domain:{domain}"
            for domain in (_crm_domain(value) for value in frame[website_column].astype(str))
            if domain
        )
    if email_column:
        identities.update(
            f"@domain:{domain}"
            for domain in (_crm_domain(value) for value in frame[email_column].astype(str))
            if domain
        )
    if phone_column:
        identities.update(
            f"@phone:{phone}"
            for phone in (_crm_phone(value) for value in frame[phone_column].astype(str))
            if phone
        )

    detected = [f"Firma: {company_column}"]
    if website_column:
        detected.append(f"Website: {website_column}")
    if email_column:
        detected.append(f"E Mail: {email_column}")
    if phone_column:
        detected.append(f"Telefon: {phone_column}")
    return identities, " | ".join(detected), len(frame)


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


def _region_groups(regions: list[tuple[str, int]], group_size: int) -> list[list[tuple[str, int]]]:
    size = max(1, int(group_size))
    return [regions[index : index + size] for index in range(0, len(regions), size)]


def _scan_task_id(campaign: str, term: str, regions: list[tuple[str, int]]) -> str:
    region_key = "|".join(f"{city}:{radius}" for city, radius in regions)
    raw = f"{campaign}|{term}|{region_key}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14]


def _scan_task_marker(campaign: str, term: str, regions: list[tuple[str, int]]) -> str:
    return f"[SCAN_TASK:{_scan_task_id(campaign, term, regions)}]"


def _task_history(logs: pd.DataFrame) -> tuple[set[str], dict[str, int]]:
    completed: set[str] = set()
    failures: dict[str, int] = {}
    if logs is None or logs.empty or "message" not in logs.columns:
        return completed, failures

    for _, row in logs.iterrows():
        message = clean_text(row.get("message", ""))
        match = re.search(r"\[SCAN_TASK:([0-9a-f]{14})\]", message)
        if not match:
            continue
        task_id = match.group(1)
        status = clean_text(row.get("status", "")).lower()
        if status == "checkpoint":
            completed.add(task_id)
        elif status in {"task_fehler", "task_leer"}:
            # Leere Suchen dürfen erneut laufen. Erst nach drei leeren oder fehlerhaften
            # Versuchen wird die Kombination vorübergehend blockiert.
            failures[task_id] = failures.get(task_id, 0) + 1
    return completed, failures


def next_search_tasks(
    terms: list[str],
    regions: list[tuple[str, int]],
    task_limit: int,
    regions_per_task: int,
    logs: pd.DataFrame,
    campaign: str,
) -> tuple[list[tuple[str, list[tuple[str, int]]]], int, int]:
    """Liefert kleine, kampagnenspezifische Suchaufgaben.

    Jede Kombination aus Suchbegriff und Regionspaket wird separat protokolliert.
    Dadurch setzt die App nach Neustarts exakt an der nächsten offenen Kombination fort.
    """
    groups = _region_groups(regions, regions_per_task)
    completed, failures = _task_history(logs)
    pending: list[tuple[int, int, str, list[tuple[str, int]]]] = []
    blocked = 0

    # Regionspaket zuerst, dann Suchbegriff. So erscheinen im ersten Klick sofort
    # unterschiedliche Branchen statt viele Regionen desselben Berufs.
    for group_index, region_group in enumerate(groups):
        for term_index, term in enumerate(terms):
            task_id = _scan_task_id(campaign, term, region_group)
            if task_id in completed:
                continue
            failure_count = failures.get(task_id, 0)
            if failure_count >= 3:
                blocked += 1
                continue
            pending.append((failure_count, group_index * max(1, len(terms)) + term_index, term, region_group))

    # Neue Aufgaben zuerst, bereits einmal fehlgeschlagene Aufgaben danach.
    pending.sort(key=lambda item: (item[0], item[1]))
    selected = [(term, region_group) for _, _, term, region_group in pending[: max(1, int(task_limit))]]
    total_tasks = len(terms) * len(groups)
    return selected, total_tasks - len(pending) - blocked, blocked

def latest_scan_id(frame: pd.DataFrame) -> str:
    if frame.empty:
        return ""
    scan_ids = [
        str(value)
        for value in frame["scan_id"].unique().tolist()
        if re.fullmatch(r"\d{8}T\d{6}Z", str(value or ""))
    ]
    return max(scan_ids) if scan_ids else ""


def latest_completed_search(logs: pd.DataFrame | None) -> dict[str, str]:
    """Liefert den letzten abgeschlossenen Suchlauf aus dem Scan Log.

    Für die Ansicht ist nicht die zuletzt berührte Lead Zeile entscheidend, sondern
    der letzte Suchlauf mit Status fertig oder fehler. So werden alte, nur erneut
    gefundene Leads nicht fälschlich als neu angezeigt.
    """
    if logs is None or logs.empty:
        return {}
    work = logs.copy().fillna("")
    if not {"stage", "status", "scan_id"}.issubset(work.columns):
        return {}
    work = work[(work["stage"] == "Suche") & (work["status"].isin(["fertig", "fehler"]))].copy()
    if work.empty:
        return {}
    if "timestamp" in work.columns:
        work = work.sort_values("timestamp")
    row = work.iloc[-1]
    return {column: clean_text(row.get(column, "")) for column in LOG_COLUMNS}


def _candidate_indices_for_scope(
    frame: pd.DataFrame,
    selector,
    limit: int,
    latest_search_scan: str,
    only_latest_new: bool,
) -> list[int]:
    """Priorisiert echte neue Leads des letzten Suchlaufs."""
    if frame.empty:
        return []
    limit = max(1, int(limit))
    if only_latest_new and latest_search_scan:
        scoped = frame[frame["first_seen_scan"] == latest_search_scan].copy()
        return selector(scoped, limit)
    return selector(frame, limit)


openai_api_key = str(st.secrets.get("openai_api_key", "")).strip()
openai_model = str(st.secrets.get("openai_model", "gpt-5-mini")).strip() or "gpt-5-mini"
serpapi_key = str(st.secrets.get("serpapi_key", "")).strip()
adzuna_app_id = str(st.secrets.get("adzuna_app_id", "")).strip()
adzuna_api_key = str(st.secrets.get("adzuna_api_key", "")).strip()

st.sidebar.title("XING Daily Leads V11.2")
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
CRM_MINIMUM_FOR_SCAN = 1000
CRM_MINIMUM_FOR_MONDAY = 1000
if "monday_crm_loaded" not in st.session_state:
    st.session_state["monday_crm_loaded"] = False
if "monday_crm_rows" not in st.session_state:
    st.session_state["monday_crm_rows"] = 0
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
    st.caption("Neue Firmen vor Salesforce finden, recherchieren und für eine kontrollierte Vertriebswelle vorbereiten.")

    research_pending = len(research_candidate_indices(frame, max(1, len(frame)))) if not frame.empty else 0
    ai_pending = len(ai_candidate_indices(frame, max(1, len(frame)))) if not frame.empty else 0
    ready_mask = (
        (frame["quality_status"] == "Versandbereit")
        & (frame["email"] != "")
        & (frame["erstmail"] != "")
    ) if not frame.empty else pd.Series(dtype=bool)

    metric_columns = st.columns(7)
    metric_columns[0].metric("Gespeicherte Firmen", len(frame))
    metric_columns[1].metric("Gespeicherte Stellen", len(jobs_frame))
    small_count = int((frame.get("size_fit", pd.Series(index=frame.index, dtype=str)) == "Klein").sum()) if not frame.empty else 0
    diamond_count = int(diamond_candidate_mask(frame).sum()) if not frame.empty else 0
    metric_columns[2].metric("Kleine Direktkunden", small_count)
    metric_columns[3].metric("Diamanten", diamond_count)
    metric_columns[4].metric("Recherche offen", research_pending)
    metric_columns[5].metric("Texte offen", ai_pending)
    metric_columns[6].metric("Verkaufsbereit", int(ready_mask.sum()) if not frame.empty else 0)

    with st.expander("Schritt 1: Firmen und Stellen finden", expanded=frame.empty):
        st.write(
            "Dieser Schritt findet Stellen und auf Wunsch zusätzlich kleine lokale Unternehmen über das Google Firmenradar. "
            "Radar Treffer werden nie automatisch als offene Vakanz behandelt. Website Recherche und Texte folgen getrennt."
        )
        campaign = st.selectbox(
            "Zielkunden Kampagne",
            list(CAMPAIGN_PRESETS.keys()),
            index=0,
            key="campaign_v60",
            help="Der Scanner filtert nicht nur nach Beruf, sondern auch nach kleiner Unternehmensstruktur.",
        )
        campaign_target = CAMPAIGN_TARGETS.get(campaign, 0)
        campaign_mask = (frame.get("kampagne", pd.Series(index=frame.index, dtype=str)) == campaign) if not frame.empty else pd.Series(dtype=bool)
        campaign_count = int(campaign_mask.sum()) if not frame.empty else 0
        if campaign == "Montagswelle 500 | Testpilot Fachkräfte" and not frame.empty:
            monday_balanced = balanced_monday_ready(frame[campaign_mask].copy())
            campaign_ready_count = len(monday_balanced)
        elif campaign == "Diamanten Radar | kleine Direktkunden" and not frame.empty:
            campaign_ready_count = int(diamond_candidate_mask(frame[campaign_mask].copy()).sum())
        else:
            campaign_ready_count = campaign_count
        if campaign_target:
            target_ratio = min(1.0, campaign_ready_count / campaign_target)
            if campaign == "Montagswelle 500 | Testpilot Fachkräfte":
                label = "versandbereiten, Salesforce sauberen Accounts"
            elif campaign == "Diamanten Radar | kleine Direktkunden":
                label = "qualifizierten Radar Kandidaten"
            else:
                label = "neuen Firmen vorbereitet"
            st.progress(target_ratio, text=f"Wellenziel: {campaign_ready_count} von {campaign_target} {label}")
            if campaign == "Montagswelle 500 | Testpilot Fachkräfte":
                st.caption(
                    "Das Ziel zählt nur recherchierte Accounts mit aktueller Vakanz, nutzbarer E Mail, individueller Mail, "
                    "KMU Fit und bestandenem Salesforce Abgleich. Rohfunde zählen ausdrücklich nicht."
                )
                quota_parts = []
                monday_all_ready = frame[strict_send_ready_mask(frame) & campaign_mask].copy() if not frame.empty else frame.copy()
                for segment, quota in MONDAY_SEGMENT_QUOTAS.items():
                    have = int((monday_all_ready.get("lead_segment", pd.Series(dtype=str)) == segment).sum()) if not monday_all_ready.empty else 0
                    quota_parts.append(f"{segment}: {min(have, quota)}/{quota}")
                st.caption("Mix: " + " | ".join(quota_parts))
            elif campaign == "Diamanten Radar | kleine Direktkunden":
                st.caption(
                    "Das Firmenradar zählt kleine neue Direktkunden mit belastbaren Firmensignalen. "
                    "Eine offene Stelle wird nur behauptet, wenn sie auf einer echten Quelle gefunden wurde."
                )
            else:
                st.caption(
                    "Diese Welle priorisiert kleine Physio, Ergo und Logopädie Praxen mit aktuellem Personalbedarf. "
                    "Die Suche pausiert automatisch, sobald das Ziel erreicht ist."
                )
        terms_text = st.text_area(
            "Suchbegriffe, eine Zeile je Begriff",
            "\n".join(CAMPAIGN_PRESETS[campaign]),
            key=f"terms_v60_{campaign}",
        )
        campaign_regions = CAMPAIGN_REGIONS.get(campaign, DEFAULT_REGIONS)
        regions_text = st.text_area(
            "Regionen im Format Ort,Umkreis",
            "\n".join(f"{city},{radius}" for city, radius in campaign_regions),
            key=f"regions_v60_{campaign}",
        )

        is_diamond_wave = campaign == "Diamanten Radar | kleine Direktkunden"
        source_columns = st.columns(5)
        use_radar = source_columns[0].checkbox(
            "Google Firmenradar",
            value=bool(serpapi_key) and is_diamond_wave,
            key=f"source_radar_v11_{campaign}",
            help="Findet lokale Unternehmen über Google Maps und prüft vorhandene Websites auf Karriere und Recruiting Signale.",
        )
        use_ba = source_columns[1].checkbox(
            "Bundesagentur", value=not is_diamond_wave, key=f"source_ba_v11_{campaign}"
        )
        use_google = source_columns[2].checkbox(
            "Google Jobs", value=bool(serpapi_key) and not is_diamond_wave, key=f"source_google_v11_{campaign}"
        )
        use_adzuna = source_columns[3].checkbox(
            "Adzuna", value=bool(adzuna_app_id and adzuna_api_key) and not is_diamond_wave, key=f"source_adzuna_v11_{campaign}"
        )
        use_careers = source_columns[4].checkbox(
            "Manuelle Karriereseiten", value=False, key=f"source_careers_v11_{campaign}"
        )
        if is_diamond_wave:
            st.caption(
                "Empfohlen: zuerst nur Google Firmenradar. Dadurch suchst du bewusst außerhalb der üblichen Stellenbörsen. "
                "Jede gefundene Firmenwebsite wird auf Karriere und Recruiting Signale geprüft und anschließend in Schritt 2 vertieft."
            )

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

        is_testpilot_wave = campaign in {"Testpilot Therapie 500", "Montagswelle 500 | Testpilot Fachkräfte"}
        settings_columns = st.columns(4)
        days = settings_columns[0].number_input(
            "Veröffentlicht seit Tagen", 1, 30, 14, key=f"days_v10_{campaign}"
        )
        max_pages = settings_columns[1].number_input(
            "Seiten je Suche", 1, 5, 1 if is_diamond_wave else (2 if is_testpilot_wave else 1), key=f"pages_v11_{campaign}"
        )
        task_batch_size = settings_columns[2].number_input(
            "Suchaufgaben pro Klick", 1, 30, 6 if is_diamond_wave else (12 if is_testpilot_wave else 4), key=f"task_batch_v11_{campaign}"
        )
        region_batch_size = settings_columns[3].number_input(
            "Regionen je Suchaufgabe", 1, 8, 3 if is_diamond_wave else (4 if is_testpilot_wave else 3), key=f"region_batch_v11_{campaign}"
        )

        all_terms = [line.strip() for line in terms_text.splitlines() if line.strip()]
        try:
            preview_regions = parse_regions(regions_text)
            upcoming_tasks, completed_task_count, blocked_task_count = next_search_tasks(
                all_terms,
                preview_regions,
                int(task_batch_size),
                int(region_batch_size),
                logs,
                campaign,
            )
            if upcoming_tasks:
                preview = [
                    f"{term}: {', '.join(city for city, _ in region_group)}"
                    for term, region_group in upcoming_tasks
                ]
                st.info("Nächste Suchaufgaben: " + " | ".join(preview))
            else:
                st.success("Diese Kampagne ist für alle eingetragenen Regionen vollständig durchsucht.")
            st.caption(
                f"Fortschritt: {completed_task_count} Suchaufgaben abgeschlossen. "
                f"{blocked_task_count} Aufgaben sind nach drei Fehlern vorübergehend blockiert."
            )
        except Exception:
            upcoming_tasks = []
            st.warning("Die Regionsvorschau konnte nicht erstellt werden. Prüfe das Format Ort,Umkreis.")

        st.caption(
            "Jeder Klick verteilt die Suche auf unterschiedliche Berufsgruppen und kleine Regionspakete. "
            "Nach einem Neustart wird bei der nächsten offenen Kombination fortgesetzt. Kontakte folgen in Schritt 2."
        )

        uploaded = st.file_uploader(
            "Optionaler Salesforce Export, vorhandene Firmen werden ausgeschlossen",
            type=["csv", "xlsx"],
            key="quick_crm_upload_v4",
        )
        if uploaded is not None:
            try:
                crm_companies, detected_column, row_count = read_company_file(uploaded)
                st.info(f"Salesforce Identitäten erkannt: {detected_column}. Zeilen: {row_count}.")
                if campaign == "Montagswelle 500 | Testpilot Fachkräfte":
                    st.session_state["monday_crm_loaded"] = True
                    st.session_state["monday_crm_rows"] = int(row_count)
                    st.success("Frischer Salesforce Export für diese Montagswelle erkannt.")
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

            if campaign == "Montagswelle 500 | Testpilot Fachkräfte":
                if not st.session_state.get("monday_crm_loaded", False):
                    st.error(
                        "Montagswelle Schutzschalter: Bitte in dieser Sitzung zuerst einen aktuellen Salesforce Export hochladen. "
                        "Die Welle startet absichtlich nicht nur auf Basis einer alten Ausschlussliste."
                    )
                    st.stop()
                if int(st.session_state.get("monday_crm_rows", 0) or 0) < CRM_MINIMUM_FOR_MONDAY:
                    st.error(
                        f"Der geladene Salesforce Export enthält nur {int(st.session_state.get('monday_crm_rows', 0) or 0):,} Zeilen. "
                        "Für die 500er Welle bitte den vollständigen Account Export inklusive Pool und Bestandskunden verwenden."
                    )
                    st.stop()

            if len(exclusions) < CRM_MINIMUM_FOR_SCAN:
                st.error(
                    f"Salesforce Schutzschalter aktiv: Es sind nur {len(exclusions):,} Ausschluss Keys geladen. "
                    "Der Suchlauf wird nicht gestartet, damit keine Bestandskunden oder Pool Accounts als Leads entstehen. "
                    "Bitte zuerst den aktuellen Salesforce Export unter Salesforce Abgleich laden."
                )
                st.stop()

            sources: list[str] = []
            if use_radar:
                sources.append("Google Firmenradar")
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
            if (use_google or use_radar) and not serpapi_key:
                st.error("Google Suche ist aktiviert, aber der SerpApi Key fehlt.")
                st.stop()

            scan_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            tasks_to_run, completed_task_count, blocked_task_count = next_search_tasks(
                all_terms,
                regions,
                int(task_batch_size),
                int(region_batch_size),
                logs,
                campaign,
            )
            if not tasks_to_run:
                st.success("Für diese Kampagne und Regionsliste sind aktuell keine offenen Suchaufgaben vorhanden.")
                st.stop()

            career_urls = [line.strip() for line in career_urls_text.splitlines() if line.strip()]
            campaign_marker = f"[KAMPAGNE:{campaign}]"
            append_log(
                scan_id=scan_id,
                stage="Suche",
                status="gestartet",
                processed_terms=" | ".join(term for term, _ in tasks_to_run),
                processed_items=str(len(tasks_to_run)),
                message=(
                    f"{campaign_marker} Suchrunde gestartet. "
                    f"{completed_task_count} Aufgaben waren vorher abgeschlossen, {blocked_task_count} blockiert."
                ),
            )
            st.info(
                "Aktuelle Suche läuft. Die bereits sichtbare Leadliste stammt bis zum ersten gespeicherten "
                "Suchpaket noch aus dem vorherigen Lauf. Schritt 1 prüft jetzt keine Websites mehr tief, "
                "damit neue Firmen schnell gespeichert werden. Die Tiefenrecherche erfolgt ausschließlich in Schritt 2."
            )

            progress = st.progress(0, text="Suchrunde startet.")
            total_jobs = total_inserted = total_updated = 0
            total_job_inserted = total_job_updated = 0
            successful_tasks = failed_tasks = 0
            details: list[str] = []
            completed_terms: list[str] = []

            for position, (term, task_regions) in enumerate(tasks_to_run, start=1):
                if campaign_target:
                    if campaign == "Diamanten Radar | kleine Direktkunden" and not frame.empty:
                        current_campaign_count = int(
                            diamond_candidate_mask(frame[frame["kampagne"] == campaign].copy()).sum()
                        )
                    else:
                        current_campaign_count = int((frame["kampagne"] == campaign).sum()) if not frame.empty else 0
                    if current_campaign_count >= campaign_target:
                        details.append(f"Wellenziel von {campaign_target} Firmen erreicht. Suche automatisch pausiert.")
                        break
                region_names = ", ".join(city for city, _ in task_regions)
                task_marker = _scan_task_marker(campaign, term, task_regions)
                progress.progress(
                    (position - 1) / max(1, len(tasks_to_run)),
                    text=f"Suche {position} von {len(tasks_to_run)}: {term} in {region_names}",
                )
                term_sources = list(sources)
                term_career_urls = career_urls
                if position > 1 and "Karriereseiten" in term_sources:
                    term_sources.remove("Karriereseiten")
                    term_career_urls = []

                try:
                    parsed_jobs, scan_diagnostics = scan_jobs(
                        terms=[term],
                        regions=task_regions,
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
                    # CRM Status ist bereits beim Fund bekannt. Kein erneuter Abgleich
                    # aller Bestandsleads gegen hunderttausende Salesforce Einträge.
                    changed_rows = frame[frame["lead_id"].isin(changed_ids)].copy()
                    persist_rows(changed_rows, frame)

                    total_jobs += sum(1 for job in eligible_jobs if clean_text(job.get("title", "")))
                    total_job_inserted += job_inserted
                    total_job_updated += job_updated
                    total_inserted += inserted
                    total_updated += updated
                    successful_tasks += 1
                    completed_terms.append(term)
                    details.append(
                        f"{term} in {region_names}: {len(eligible_jobs)} priorisierte Funde, "
                        f"{job_inserted} neue Fundzeilen, {inserted} neue Firmen."
                    )
                    details.extend(
                        f"{term} in {region_names}: {message}"
                        for message in scan_diagnostics + discovery_diagnostics
                    )
                    progress.progress(
                        position / max(1, len(tasks_to_run)),
                        text=(
                            f"Gespeichert {position} von {len(tasks_to_run)}: {term}. "
                            f"{job_inserted} neue Funde, {inserted} neue Firmen."
                        ),
                    )
                    # Eine technisch erfolgreiche, aber komplett leere Radar Suche wird
                    # nicht sofort als dauerhaft erledigt markiert. Sonst würde ein leerer
                    # Google Maps Treffer die Kombination für alle späteren Läufe sperren.
                    task_status = "checkpoint" if len(eligible_jobs) > 0 else "task_leer"
                    append_log(
                        scan_id=scan_id,
                        stage="Suche",
                        status=task_status,
                        processed_terms=term,
                        processed_items=str(position),
                        found_jobs=str(len(eligible_jobs)),
                        new_leads=str(inserted),
                        updated_leads=str(updated),
                        message=(
                            f"{task_marker} {campaign_marker} {term} in {region_names} gespeichert: "
                            f"{len(eligible_jobs)} verwertbare Funde, {inserted} neue Firmen, {updated} aktualisierte Firmen."
                        ),
                    )
                except Exception as exc:
                    failed_tasks += 1
                    error_text = f"{type(exc).__name__}: {clean_text(exc)}"
                    trace_text = traceback.format_exc(limit=14)
                    details.append(f"{term} in {region_names} fehlgeschlagen: {error_text}")
                    details.append(trace_text)
                    st.session_state["last_search_exception"] = trace_text
                    try:
                        append_log(
                            scan_id=scan_id,
                            stage="Suche",
                            status="task_fehler",
                            processed_terms=term,
                            processed_items=str(position),
                            message=f"{task_marker} {campaign_marker} {term} in {region_names}: {error_text}",
                        )
                    except Exception as log_exc:
                        details.append(f"Scan Log konnte den Fehler nicht speichern: {type(log_exc).__name__}: {clean_text(log_exc)}")
                    # Ein einzelner Quellenfehler darf die anderen Berufsgruppen nicht mehr blockieren.
                    continue

            progress.progress(1.0, text="Suchrunde abgeschlossen und gespeichert.")
            try:
                append_log(
                    scan_id=scan_id,
                    stage="Suche",
                    status="fertig",
                    processed_terms=" | ".join(completed_terms),
                    processed_items=str(successful_tasks),
                    found_jobs=str(total_jobs),
                    new_leads=str(total_inserted),
                    updated_leads=str(total_updated),
                    message=(
                        f"{campaign_marker} Suchrunde abgeschlossen: {successful_tasks} erfolgreich, "
                        f"{failed_tasks} fehlgeschlagen."
                    ),
                )
            except Exception as log_exc:
                details.append(f"Abschluss Log konnte nicht gespeichert werden: {type(log_exc).__name__}: {clean_text(log_exc)}")
            st.session_state["last_pipeline_details"] = details
            if successful_tasks:
                st.success(
                    f"Gespeichert: {total_job_inserted} neue Stellenzeilen und {total_job_updated} aktualisierte Stellen. "
                    f"Zusätzlich {total_inserted} neue Firmen und {total_updated} aktualisierte Firmen. "
                    f"Suchaufgaben: {successful_tasks} erfolgreich, {failed_tasks} fehlgeschlagen."
                )
            else:
                st.error("Keine Suchaufgabe konnte abgeschlossen werden.")
                last_trace = st.session_state.get("last_search_exception", "")
                if last_trace:
                    st.error("Der echte Python Fehler steht direkt hier:")
                    st.code(last_trace, language="text")
                elif details:
                    st.code("\n\n".join(details[-8:]), language="text")
            progress.empty()

    live_logs = st.session_state.get("xing_logs_cache", logs).copy()
    latest_search = latest_completed_search(live_logs)
    latest_search_scan = clean_text(latest_search.get("scan_id", "")) or latest_scan_id(frame)
    latest_new_mask = (frame["first_seen_scan"] == latest_search_scan) if (not frame.empty and latest_search_scan) else pd.Series(False, index=frame.index)
    latest_updated_mask = (
        (frame["scan_id"] == latest_search_scan)
        & (frame["first_seen_scan"] != latest_search_scan)
    ) if (not frame.empty and latest_search_scan) else pd.Series(False, index=frame.index)

    latest_new_count = int(latest_new_mask.sum()) if not frame.empty else 0
    latest_updated_count = int(latest_updated_mask.sum()) if not frame.empty else 0
    latest_found_jobs = safe_int(latest_search.get("found_jobs", "0")) if latest_search else 0

    if latest_search_scan:
        summary_cols = st.columns(3)
        summary_cols[0].metric("Neu im letzten Lauf", latest_new_count)
        summary_cols[1].metric("Bekannte aktualisiert", latest_updated_count)
        summary_cols[2].metric("Gefundene Stellen", latest_found_jobs)

    current_scan_text = " ".join(
        frame.loc[latest_new_mask | latest_updated_mask, ["research_notes", "last_error"]]
        .fillna("")
        .astype(str)
        .values
        .ravel()
        .tolist()
    ) if (not frame.empty and latest_search_scan) else ""
    if "429" in current_scan_text or "quota" in current_scan_text.lower():
        st.warning(
            "Die Suche hat neue Firmen geliefert, aber mindestens ein externer Dienst meldet aktuell Limit 429. "
            "Dadurch fehlen bei einem Teil der Leads Ansprechpartner, E Mail oder echte KI Texte. "
            "Diese Leads bleiben sichtbar, werden aber nicht als versandbereit dargestellt."
        )

    research_all_global = research_candidate_indices(frame, max(1, len(frame))) if not frame.empty else []
    research_all_latest = research_candidate_indices(frame.loc[latest_new_mask].copy(), max(1, latest_new_count)) if latest_new_count else []
    with st.expander(
        f"Schritt 2: Website, Ansprechpartner, Mail und Telefon recherchieren "
        f"({len(research_all_latest)} neue aus letztem Lauf, {len(research_all_global)} insgesamt offen)"
    ):
        st.write("Standardmäßig werden zuerst ausschließlich die wirklich neuen Firmen des letzten Suchlaufs bearbeitet.")
        research_only_latest = st.checkbox(
            "Nur neue Firmen aus dem letzten Suchlauf",
            value=True,
            key="research_only_latest_v10",
            disabled=not bool(latest_search_scan),
        )
        research_limit = st.number_input("Firmen pro Recherchepaket", 1, 50, 10, key="research_limit_v10")
        research_available = research_all_latest if research_only_latest else research_all_global
        if st.button("Schritt 2 starten", disabled=not research_available, key="start_research_v10"):
            indices = _candidate_indices_for_scope(
                frame, research_candidate_indices, int(research_limit), latest_search_scan, research_only_latest
            )
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
                if crm_match(
                    updated.get("firma", ""),
                    exclusions,
                    website=updated.get("website", ""),
                    email=updated.get("email", ""),
                    phone=updated.get("telefon", ""),
                ):
                    updated["crm_status"] = "Bereits in Salesforce"
                    updated["status"] = "Ausschließen"
                    updated["quality_status"] = "Nicht freigeben"
                    updated["quality_notes"] = "Nach Website oder Kontakt Recherche sicher im Salesforce Bestand erkannt"
                    diagnostics.append(f"{company}: nach Recherche über Domain oder Telefon in Salesforce erkannt und automatisch ausgeschlossen")
                else:
                    updated["crm_status"] = "Neu"
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

    ai_all_global = ai_candidate_indices(frame, max(1, len(frame))) if not frame.empty else []
    ai_all_latest = ai_candidate_indices(frame.loc[latest_new_mask].copy(), max(1, latest_new_count)) if latest_new_count else []
    with st.expander(
        f"Schritt 3: Individuelle Sales Texte erzeugen "
        f"({len(ai_all_latest)} neue aus letztem Lauf, {len(ai_all_global)} insgesamt offen)"
    ):
        st.write("Auch hier werden standardmäßig nur die wirklich neuen Firmen des letzten Suchlaufs verarbeitet.")
        ai_only_latest = st.checkbox(
            "Nur neue Firmen aus dem letzten Suchlauf",
            value=True,
            key="ai_only_latest_v10",
            disabled=not bool(latest_search_scan),
        )
        ai_limit = st.number_input("Firmen pro Textpaket", 1, 50, 10, key="ai_limit_v10")
        ai_available = ai_all_latest if ai_only_latest else ai_all_global
        if st.button("Schritt 3 starten", disabled=not ai_available, key="start_ai_v10"):
            indices = _candidate_indices_for_scope(
                frame, ai_candidate_indices, int(ai_limit), latest_search_scan, ai_only_latest
            )
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
                updated["erstmail_betreff"] = expected_subject(updated)
                for column in COLUMNS:
                    frame.loc[index, column] = updated.get(column, frame.loc[index, column])
                persist_rows(frame.loc[[index]], frame)
                if frame.loc[index, "ai_status"].startswith(("KI erstellt", "Fallback erstellt")):
                    ai_created += 1
                details.extend(diagnostics)
            progress.empty()
            append_log(
                scan_id=run_id,
                stage="Texte",
                status="fertig",
                processed_items=str(len(indices)),
                message=f"Fertige Texte {ai_created}, offene oder alte Fallbacks {len(indices) - ai_created}.",
            )
            st.session_state["last_pipeline_details"] = details
            st.success(f"Textpaket abgeschlossen: {ai_created} fertige Texte, {len(indices) - ai_created} offene oder alte Fallbacks.")

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
        base_open_mask = (
            ~frame["status"].isin(["In Salesforce übernommen", "Ausschließen"])
            & (frame["crm_status"] != "Bereits in Salesforce")
            & (frame["size_fit"] != "Groß oder unpassend")
        )
        true_new_frame = frame[base_open_mask & latest_new_mask].copy()
        updated_last_run_frame = frame[base_open_mask & latest_updated_mask].copy()

        ready_frame = frame[
            base_open_mask
            & (frame["quality_status"].isin(["Versandbereit", "Kurz prüfen"]))
            & (frame["email"] != "")
            & (frame["erstmail"] != "")
        ].copy()
        open_frame = frame[base_open_mask].copy()

        monday_ready = balanced_monday_ready(frame) if not frame.empty else frame.copy()
        if not monday_ready.empty:
            next_monday = date.today() + timedelta(days=(7 - date.today().weekday()) % 7 or 7)
            monday_export = monday_ready[[
                "firma", "ansprechpartner", "rolle", "email", "telefon", "website",
                "job_titles", "orte", "erstmail_betreff", "erstmail", "personalization_evidence",
                "quality_score", "lead_score", "kampagne",
            ]].copy()
            monday_export.insert(0, "geplanter_versand", next_monday.isoformat())
            st.download_button(
                f"Montagswelle Export herunterladen ({len(monday_export)} versandbereit)",
                monday_export.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"xing_montagswelle_{next_monday.isoformat()}_{len(monday_export)}_accounts.csv",
                mime="text/csv",
                key="download_monday_ready_v104",
            )

        view_options = [
            f"Neu aus letztem Lauf ({len(true_new_frame)})",
            f"Im letzten Lauf aktualisiert ({len(updated_last_run_frame)})",
            f"Mit Kontakt und Mail ({len(ready_frame)})",
            f"Alle offenen Leads ({len(open_frame)})",
        ]
        view_mode = st.radio("Arbeitsansicht", view_options, horizontal=True, key="lead_view_v10")

        if view_mode.startswith("Neu aus"):
            display_frame = true_new_frame.copy()
        elif view_mode.startswith("Im letzten Lauf"):
            display_frame = updated_last_run_frame.copy()
        elif view_mode.startswith("Mit Kontakt"):
            display_frame = ready_frame.copy()
        else:
            display_frame = open_frame.copy()

        filter_cols = st.columns([2, 2, 2, 3])
        lead_campaigns = ["Alle Kampagnen"] + sorted([x for x in display_frame["kampagne"].dropna().astype(str).unique().tolist() if x])
        selected_campaign = filter_cols[0].selectbox("Kampagne", lead_campaigns, key="lead_campaign_filter_v10")
        segments = ["Alle Segmente"] + sorted([x for x in display_frame["lead_segment"].dropna().astype(str).unique().tolist() if x])
        selected_segment = filter_cols[1].selectbox("Segment", segments, key="segment_filter_v10")
        contact_filter = filter_cols[2].selectbox(
            "Kontaktstatus",
            ["Alle", "E Mail vorhanden", "Direkte oder Recruiting Mail", "Recherche offen"],
            key="contact_filter_v10",
        )
        search_text = filter_cols[3].text_input(
            "Firma oder Position suchen",
            placeholder="zum Beispiel Architekt, Ingenieur, Steuer oder IT",
            key="lead_search_v10",
        ).strip().lower()

        if selected_campaign != "Alle Kampagnen":
            display_frame = display_frame[display_frame["kampagne"] == selected_campaign].copy()
        if selected_segment != "Alle Segmente":
            display_frame = display_frame[display_frame["lead_segment"] == selected_segment].copy()
        if contact_filter == "E Mail vorhanden":
            display_frame = display_frame[display_frame["email"] != ""].copy()
        elif contact_filter == "Direkte oder Recruiting Mail":
            display_frame = display_frame[display_frame["email_quality"].isin(["Direkt", "Recruiting"])].copy()
        elif contact_filter == "Recherche offen":
            display_frame = display_frame[display_frame["research_status"].isin(["", "offen", "nicht gefunden", "Fehler"])].copy()
        if search_text:
            haystack = (
                display_frame["firma"].fillna("").astype(str) + " "
                + display_frame["job_titles"].fillna("").astype(str) + " "
                + display_frame["lead_segment"].fillna("").astype(str)
            ).str.lower()
            display_frame = display_frame[haystack.str.contains(re.escape(search_text), na=False)].copy()

        display_frame["score_num"] = pd.to_numeric(display_frame["lead_score"], errors="coerce").fillna(0)
        display_frame["small_num"] = pd.to_numeric(display_frame["small_business_score"], errors="coerce").fillna(0)
        display_frame["quality_num"] = pd.to_numeric(display_frame["quality_score"], errors="coerce").fillna(0)
        display_frame["contact_rank"] = display_frame["email_quality"].map(
            {"Direkt": 4, "Recruiting": 3, "Allgemein": 2, "Fehlt": 0}
        ).fillna(0)
        display_frame["has_mail_text"] = ((display_frame["email"] != "") & (display_frame["erstmail"] != "")).astype(int)
        display_frame = display_frame.sort_values(
            ["has_mail_text", "contact_rank", "quality_num", "small_num", "score_num", "firma"],
            ascending=[False, False, False, False, False, True],
        ).head(250)

        st.caption(
            f"Angezeigt: {len(display_frame)}. Echte neue Leads werden über first_seen_scan erkannt. "
            "Bereits bekannte Firmen, die im letzten Lauf erneut gefunden wurden, stehen separat."
        )
        if display_frame.empty:
            st.info("In dieser Ansicht gibt es aktuell keine passenden Leads.")

        for index, row in display_frame.iterrows():
            with st.container(border=True):
                header_columns = st.columns([5, 1.5, 1.5, 2])
                is_true_new = bool(latest_search_scan and clean_text(row.get("first_seen_scan", "")) == latest_search_scan)
                new_badge = "NEU · " if is_true_new else ""
                header_columns[0].subheader(f"{new_badge}{row['firma']}")
                header_columns[1].metric(row["hot_status"] or "COLD", int(float(row["lead_score"] or 0)))
                header_columns[2].metric("Qualität", int(float(row["quality_score"] or 0)))
                header_columns[3].write(row["quality_status"] or "Nicht freigeben")

                st.write(f"**Kampagne:** {row['kampagne'] or 'nicht zugeordnet'} · **Segment:** {row['lead_segment'] or 'Direktkunde'} · **Größenfit:** {row['size_fit'] or 'offen'}")
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
            st.info(f"Erkannte Salesforce Felder: {detected_column}")
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
