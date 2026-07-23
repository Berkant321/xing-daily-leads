from __future__ import annotations

import hashlib
import re
import time
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any

import pandas as pd
import streamlit as st
from bs4 import BeautifulSoup

from research import normalize_company as research_normalize_company
from research import research_company
from sales_ai import ASSET_KEYS, create_sales_assets, openai_available
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

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

DEFAULT_SEARCH_TERMS = [
    "Physiotherapeut",
    "Ergotherapeut",
    "Logopäde",
    "Pflegefachkraft",
    "Medizinische Fachangestellte",
    "Steuerfachangestellte",
    "Steuerfachwirt",
    "Bilanzbuchhalter",
    "Elektroniker",
    "Mechatroniker",
    "Anlagenmechaniker",
    "Servicetechniker",
    "Industriemechaniker",
    "Schweißer",
    "Bauleiter",
    "Projektingenieur",
    "Konstrukteur",
    "Softwareentwickler",
    "Systemadministrator",
    "DevOps Engineer",
    "Vertriebsmitarbeiter",
    "Account Manager",
    "Controller",
    "Berufskraftfahrer",
    "Disponent",
]

DEFAULT_REGIONS = [
    ("Münster", 100),
    ("Osnabrück", 100),
    ("Dortmund", 100),
    ("Bielefeld", 100),
]

BENEFIT_PATTERNS = {
    "Homeoffice": [r"\bhomeoffice\b", r"\bremote\b", r"mobiles arbeiten"],
    "Flexible Arbeitszeiten": [r"flexible arbeitszeit", r"gleitzeit"],
    "4 Tage Woche": [r"4[\s-]*tage[\s-]*woche", r"vier[\s-]*tage[\s-]*woche"],
    "30 oder mehr Tage Urlaub": [r"\b3[0-9]\s*(tage|urlaubstage)"],
    "JobRad": [r"\bjobrad\b", r"dienstfahrrad", r"bikeleasing"],
    "Jobticket": [r"\bjobticket\b", r"deutschlandticket"],
    "Weiterbildung": [r"weiterbildung", r"fortbildung"],
    "Betriebliche Altersvorsorge": [r"altersvorsorge", r"\bbav\b"],
    "Bonus oder Prämien": [r"\bbonus\b", r"prämie", r"sonderzahlung"],
    "Keine Wochenendarbeit": [r"keine wochenend", r"montag bis freitag"],
    "Keine Überstunden": [r"keine überstunden", r"überstundenausgleich"],
    "Unbefristet": [r"unbefristet"],
    "Digitale Arbeitsweise": [r"digitale kanzlei", r"datev unternehmen online"],
    "Familiäres Team": [r"familiär", r"teamzusammenhalt"],
}

AGENCY_WORDS = [
    "zeitarbeit", "personalvermittlung", "personaldienstleistung",
    "personaldienstleister", "arbeitnehmerüberlassung", "staffing",
    "recruiting agency", "personalservice", "randstad", "adecco",
    "manpower", "persona service", "tempton", "office people",
    "pluss personal", "avitea", "piening", "expertum", "actief",
]

LARGE_COMPANY_WORDS = [
    "deutsche bahn", "db regio", "siemens", "bosch", "amazon", "lidl",
    "aldi", "rewe group", "thyssenkrupp", "telekom", "vodafone",
    "bundeswehr", "universitätsklinikum", "uniklinik", "ministerium",
]

STATUSES = [
    "Neu",
    "Mail vorbereitet",
    "Follow up fällig",
    "Für morgen",
    "In Salesforce übernommen",
    "Ausschließen",
]

COLUMNS = [
    "lead_id",
    "firma",
    "hot_status",
    "lead_score",
    "warum_hot",
    "offene_stellen",
    "anzahl_stellen",
    "orte",
    "veroeffentlicht_am",
    "first_seen",
    "first_seen_scan",
    "zuletzt_gefunden",
    "scan_id",
    "times_seen",
    "source_list",
    "benefits",
    "ansprechpartner",
    "rolle",
    "email",
    "telefon",
    "website",
    "kontaktseite",
    "impressum",
    "karriereseite",
    "stellenlink",
    "research_status",
    "research_notes",
    "employee_hint",
    "location_hint",
    "content_hash",
    "ai_status",
    "text_locked",
    "crm_status",
    "erstmail_betreff",
    "erstmail",
    "call_opener",
    "discovery_fragen",
    "challenger_reframe",
    "follow_up_1",
    "follow_up_2",
    "status",
    "wiedervorlage",
    "notiz",
]

MANUAL_COLUMNS = ["status", "wiedervorlage", "notiz", "text_locked"]
RESEARCH_COLUMNS = [
    "ansprechpartner", "rolle", "email", "telefon", "website", "kontaktseite",
    "impressum", "karriereseite", "research_status", "research_notes",
    "employee_hint", "location_hint",
]
TEXT_COLUMNS = ASSET_KEYS + ["ai_status", "content_hash"]


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------

def clean_text(value: Any) -> str:
    if value is None:
        return ""
    value = BeautifulSoup(str(value), "html.parser").get_text(" ")
    return re.sub(r"\s+", " ", value).strip()


def normalize_company(name: str) -> str:
    # Einheitliche Normalisierung für CRM, Scanner und Speicher.
    return research_normalize_company(clean_text(name))


def lead_id(company: str) -> str:
    return hashlib.sha1(normalize_company(company).encode("utf-8")).hexdigest()[:14]


def unique(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        value = clean_text(value)
        if value and value.lower() not in seen:
            seen.add(value.lower())
            result.append(value)
    return result


def detect_benefits(text: str) -> list[str]:
    text = clean_text(text).lower()
    return [
        benefit
        for benefit, patterns in BENEFIT_PATTERNS.items()
        if any(re.search(pattern, text, re.I) for pattern in patterns)
    ]


def likely_large_or_agency(company: str) -> str:
    low = f" {company.lower()} "
    if any(word in low for word in AGENCY_WORDS):
        return "Vermittler"
    if any(word in low for word in LARGE_COMPANY_WORDS):
        return "Großunternehmen"
    return ""


def _job_family(title: str) -> str:
    value = normalize_company(title)
    families = {
        "Steuer und Finanzen": ["steuerfach", "bilanzbuch", "finanzbuch", "buchhalter", "controller", "lohn", "tax"],
        "Therapie": ["physio", "ergotherapeut", "logop", "therapeut"],
        "Pflege und Medizin": ["pflege", "medizinische fachang", "arzt", "arztin", "mfa", "gesundheits", "kranken"],
        "Elektro und Technik": ["elektroniker", "elektriker", "mechatron", "servicetechn", "sps", "automation"],
        "Metall und Produktion": ["schlosser", "schwei", "industriemechan", "zerspan", "cnc", "monteur", "metall"],
        "Bau und Engineering": ["bauleiter", "architekt", "ingenieur", "konstrukteur", "projektleiter", "tiefbau", "hochbau"],
        "IT": ["software", "entwickler", "developer", "devops", "systemadministrator", "it support", "informatik"],
        "Vertrieb": ["vertrieb", "sales", "account manager", "business development"],
        "Logistik": ["lager", "logistik", "stapler", "fahrer", "disponent", "verlader", "berufskraft"],
        "Verwaltung": ["sachbearbeiter", "assistenz", "office", "personalreferent", "kaufmann", "kauffrau"],
    }
    for family, keywords in families.items():
        if any(keyword in value for keyword in keywords):
            return family
    return "Sonstige"


def _split_pipe(value: str) -> list[str]:
    return [clean_text(item) for item in str(value or "").split("|") if clean_text(item)]


def _empty_row() -> dict[str, str]:
    return {column: "" for column in COLUMNS}


def _migrate_frame(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy() if frame is not None else pd.DataFrame()
    for column in COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    frame = frame.reindex(columns=COLUMNS).fillna("")
    return frame.astype(str)


def _crm_match(company: str, exclusions: set[str]) -> bool:
    normalized = normalize_company(company)
    if not normalized:
        return False
    if normalized in exclusions:
        return True
    if len(normalized) < 8:
        return False
    for existing in exclusions:
        if len(existing) < 8:
            continue
        if normalized in existing or existing in normalized:
            if min(len(normalized), len(existing)) / max(len(normalized), len(existing)) >= 0.72:
                return True
        if SequenceMatcher(None, normalized, existing).ratio() >= 0.94:
            return True
    return False


def _rotate_terms(terms: list[str], batch_size: int, scan_id: str) -> list[str]:
    if batch_size <= 0 or batch_size >= len(terms):
        return terms
    seed = int(hashlib.sha1(scan_id.encode("utf-8")).hexdigest()[:8], 16)
    start = seed % len(terms)
    rotated = terms[start:] + terms[:start]
    return rotated[:batch_size]


def _facts_hash(company: str, jobs: list[dict], benefits: list[str], research: dict[str, Any]) -> str:
    parts = [
        company,
        "|".join(unique([job.get("title", "") for job in jobs])),
        "|".join(benefits),
        clean_text(research.get("person", "")),
        clean_text(research.get("role", "")),
        clean_text(research.get("website", "")),
        clean_text(research.get("text", ""))[:3000],
    ]
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Speicher
# ---------------------------------------------------------------------------

def _google_call(func, *args, **kwargs):
    """Retry only temporary Google quota errors with exponential backoff."""
    delays = (0, 5, 15, 30)
    last_error = None
    for delay in delays:
        if delay:
            time.sleep(delay)
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            last_error = exc
            message = str(exc).lower()
            temporary = "429" in message or "quota exceeded" in message or "resource_exhausted" in message
            if not temporary:
                raise
    raise last_error


class Storage:
    def __init__(self):
        self.mode = "local"
        self.error = ""
        self.ws = None
        self.exclusion_ws = None
        self.local_path = "leads_local.csv"
        self.local_exclusion_path = "crm_ausschluss_local.csv"
        self.google_configured = bool(
            gspread
            and "gcp_service_account" in st.secrets
            and "spreadsheet_name" in st.secrets
        )

        if self.google_configured:
            try:
                creds = Credentials.from_service_account_info(
                    dict(st.secrets["gcp_service_account"]),
                    scopes=[
                        "https://www.googleapis.com/auth/spreadsheets",
                        "https://www.googleapis.com/auth/drive",
                    ],
                )
                client = gspread.authorize(creds)
                book = _google_call(client.open, str(st.secrets["spreadsheet_name"]))

                # One worksheet-list request instead of repeating it for every tab.
                worksheets = {worksheet.title: worksheet for worksheet in _google_call(book.worksheets)}
                self.ws = self._sheet(book, worksheets, "Leads", 8000, max(60, len(COLUMNS) + 5))
                self.exclusion_ws = self._sheet(book, worksheets, "CRM_Ausschluss", 8000, 5)
                self.mode = "google"
            except Exception as exc:
                # Never fall back silently to ephemeral local storage when Google
                # was explicitly configured. That could make users believe data is persistent.
                self.mode = "google_error"
                self.error = str(exc)

    @staticmethod
    def _sheet(book, worksheets: dict, title: str, rows: int, cols: int):
        if title in worksheets:
            return worksheets[title]
        worksheet = _google_call(book.add_worksheet, title=title, rows=rows, cols=cols)
        try:
            _google_call(worksheet.freeze, rows=1)
        except Exception:
            pass
        worksheets[title] = worksheet
        return worksheet

    def load(self) -> pd.DataFrame:
        if self.mode == "google":
            values = _google_call(self.ws.get_all_records)
            return _migrate_frame(pd.DataFrame(values))
        if self.mode == "google_error":
            raise RuntimeError(self.error or "Google Sheets ist nicht verbunden.")
        try:
            return _migrate_frame(pd.read_csv(self.local_path, dtype=str).fillna(""))
        except FileNotFoundError:
            return _migrate_frame(pd.DataFrame())

    def save(self, frame: pd.DataFrame) -> None:
        frame = _migrate_frame(frame)
        if self.mode == "google":
            _google_call(self.ws.clear)
            _google_call(self.ws.update, [COLUMNS] + frame.astype(str).values.tolist())
        elif self.mode == "google_error":
            raise RuntimeError(self.error or "Google Sheets ist nicht verbunden.")
        else:
            frame.to_csv(self.local_path, index=False)

    def load_exclusions(self) -> set[str]:
        if self.mode == "google":
            values = _google_call(self.exclusion_ws.get_all_records)
            return {
                normalize_company(row.get("firma", ""))
                for row in values
                if row.get("firma")
            }
        if self.mode == "google_error":
            raise RuntimeError(self.error or "Google Sheets ist nicht verbunden.")
        try:
            frame = pd.read_csv(self.local_exclusion_path, dtype=str).fillna("")
            return {normalize_company(value) for value in frame.get("firma", []) if value}
        except FileNotFoundError:
            return set()

    def save_exclusions(self, companies: set[str]) -> None:
        rows = sorted({normalize_company(company) for company in companies if normalize_company(company)})
        if self.mode == "google":
            _google_call(self.exclusion_ws.clear)
            _google_call(self.exclusion_ws.update, [["firma"]] + [[company] for company in rows])
        elif self.mode == "google_error":
            raise RuntimeError(self.error or "Google Sheets ist nicht verbunden.")
        else:
            pd.DataFrame({"firma": rows}).to_csv(self.local_exclusion_path, index=False)


@st.cache_resource(show_spinner=False)
def get_storage() -> Storage:
    # Streamlit reruns the script for every widget interaction. Caching the
    # connection prevents a fresh burst of Google API reads on every rerun.
    return Storage()


storage = get_storage()


def persist_frame(frame: pd.DataFrame) -> None:
    migrated = _migrate_frame(frame)
    storage.save(migrated)
    st.session_state["xing_frame_cache"] = migrated.copy()


def persist_exclusions(companies: set[str]) -> None:
    normalized = {normalize_company(company) for company in companies if normalize_company(company)}
    storage.save_exclusions(normalized)
    st.session_state["xing_exclusions_cache"] = set(normalized)


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


def apply_crm_status(frame: pd.DataFrame, exclusions: set[str]) -> pd.DataFrame:
    frame = _migrate_frame(frame)
    frame["crm_status"] = frame["firma"].map(
        lambda company: "Bereits in Salesforce" if _crm_match(company, exclusions) else "Neu"
    )
    return frame


# ---------------------------------------------------------------------------
# Scoring, Recherche und Texte
# ---------------------------------------------------------------------------

def _cached_research(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "website": row.get("website", ""),
        "contact_page": row.get("kontaktseite", ""),
        "imprint_page": row.get("impressum", ""),
        "career_page": row.get("karriereseite", ""),
        "email": row.get("email", ""),
        "phone": row.get("telefon", ""),
        "person": row.get("ansprechpartner", ""),
        "role": row.get("rolle", ""),
        "text": "",
        "status": row.get("research_status", "Cache"),
        "notes": row.get("research_notes", "Aus gespeichertem Lead übernommen."),
        "employee_hint": row.get("employee_hint", ""),
        "location_hint": row.get("location_hint", ""),
    }


def _research_complete(row: dict[str, Any]) -> bool:
    return bool(row.get("website")) and bool(row.get("email") or row.get("telefon"))


def score_lead(
    company: str,
    jobs: list[dict],
    research: dict[str, Any],
    benefits: list[str],
    previous_times_seen: int = 0,
) -> tuple[str, int, str]:
    base_scores = [int(job.get("lead_score", 0) or 0) for job in jobs]
    score = max(base_scores or [20])
    reasons: list[str] = []
    penalties: list[str] = []

    scanner_reasons = unique([job.get("lead_reasons", "") for job in jobs if job.get("lead_reasons")])
    if scanner_reasons:
        reasons.extend(scanner_reasons[:2])

    titles = unique([job.get("title", "") for job in jobs if job.get("title")])
    families = [_job_family(title) for title in titles]
    family_counts: dict[str, int] = {}
    for family in families:
        family_counts[family] = family_counts.get(family, 0) + 1
    dominant_family = max(family_counts, key=family_counts.get) if family_counts else "Sonstige"
    dominant_share = family_counts.get(dominant_family, 0) / max(1, len(families))

    if 2 <= len(jobs) <= 8:
        score += 8
        reasons.append(f"{len(jobs)} konkrete Stellen")
    elif len(jobs) > 15:
        score -= 12
        penalties.append("sehr viele Ausschreibungen")

    if len(titles) >= 2 and dominant_share >= 0.65:
        score += 9
        reasons.append(f"klarer Schwerpunkt: {dominant_family}")

    if research.get("person"):
        score += 8
        reasons.append("Ansprechpartner gefunden")
    if research.get("email"):
        score += 7
        reasons.append("E Mail gefunden")
    if research.get("phone"):
        score += 6
        reasons.append("Telefon gefunden")
    if research.get("website"):
        score += 4
    if len(benefits) >= 4:
        score += 7
        reasons.append("starke Benefits")
    elif len(benefits) >= 2:
        score += 4
        reasons.append("mehrere Benefits")
    if previous_times_seen >= 2:
        score += min(7, previous_times_seen + 2)
        reasons.append("wiederkehrender Personalbedarf")
    if research.get("location_hint") and str(research.get("location_hint")).isdigit():
        if int(research["location_hint"]) >= 2:
            score += 4
            reasons.append("mehrere Standorte")

    classification = likely_large_or_agency(company)
    if classification:
        score -= 55
        penalties.append(classification)

    score = max(0, min(int(score), 100))
    status = "HOT" if score >= 75 else "WARM" if score >= 55 else "COLD"
    explanation = reasons[:6] + [f"Abzug: {item}" for item in penalties[:2]]
    return status, score, ", ".join(explanation)


def _group_jobs(parsed_jobs: list[dict], exclusions: set[str]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for job in parsed_jobs:
        company = clean_text(job.get("company", ""))
        key = normalize_company(company)
        if not key or _crm_match(company, exclusions):
            continue
        groups[key].append(job)
    return groups


def build_leads(
    *,
    parsed_jobs: list[dict],
    exclusions: set[str],
    max_research: int,
    serpapi_key: str,
    existing: pd.DataFrame,
    openai_api_key: str,
    openai_model: str,
    scan_id: str,
) -> tuple[pd.DataFrame, list[str]]:
    groups = _group_jobs(parsed_jobs, exclusions)
    existing = _migrate_frame(existing)
    existing_map = {row["lead_id"]: row.to_dict() for _, row in existing.iterrows()}

    candidates: list[tuple[int, int, int, str, list[dict]]] = []
    for key, jobs in groups.items():
        company = clean_text(jobs[0].get("company", ""))
        if likely_large_or_agency(company):
            continue
        lid = lead_id(company)
        old = existing_map.get(lid, {})
        is_new = 1 if not old else 0
        incomplete = 1 if not old or not _research_complete(old) else 0
        base_score = max([int(job.get("lead_score", 0) or 0) for job in jobs] or [0])
        candidates.append((is_new, incomplete, base_score, key, jobs))

    candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    rows: list[dict[str, Any]] = []
    research_count = 0
    research_success = 0
    ai_created = 0
    ai_fallback = 0
    cache_used = 0
    research_failures: list[str] = []
    ai_failures: list[str] = []

    for _is_new, _incomplete, _base_score, _key, jobs in candidates:
        company = clean_text(jobs[0].get("company", ""))
        lid = lead_id(company)
        old = existing_map.get(lid, {})
        city = next((clean_text(job.get("city", "")) for job in jobs if job.get("city")), "")
        source_urls = unique([
            job.get("external_url", "") or job.get("job_link", "")
            for job in jobs
            if job.get("external_url") or job.get("job_link")
        ])

        if old and _research_complete(old):
            research = _cached_research(old)
            cache_used += 1
        elif research_count < max_research:
            research_count += 1
            research = research_company(
                company=company,
                city=city,
                source_urls=source_urls,
                serpapi_key=serpapi_key,
                max_pages=12,
            )
            if research.get("website"):
                research_success += 1
            else:
                research_failures.append(
                    f"{company}: {research.get('notes', 'keine Website gefunden')}"
                )
        else:
            research = _cached_research(old) if old else {
                "website": "",
                "contact_page": "",
                "imprint_page": "",
                "career_page": "",
                "email": "",
                "phone": "",
                "person": "",
                "role": "",
                "text": "",
                "status": "nicht recherchiert",
                "notes": "Recherchelimit dieses Laufs erreicht.",
                "employee_hint": "",
                "location_hint": "",
            }

        direct_email = next((clean_text(job.get("email", "")) for job in jobs if job.get("email")), "")
        direct_phone = next((clean_text(job.get("phone", "")) for job in jobs if job.get("phone")), "")
        direct_person = next((clean_text(job.get("contact", "")) for job in jobs if job.get("contact")), "")
        research["email"] = research.get("email") or direct_email
        research["phone"] = research.get("phone") or direct_phone
        research["person"] = research.get("person") or direct_person

        benefits = unique(
            detect_benefits(" ".join(clean_text(job.get("description", "")) for job in jobs))
            + detect_benefits(research.get("text", ""))
        )

        old_times_seen = int(float(old.get("times_seen", 0) or 0)) if old else 0
        hot_status, score, reason = score_lead(
            company,
            jobs,
            research,
            benefits,
            previous_times_seen=old_times_seen,
        )

        content_hash = _facts_hash(company, jobs, benefits, research)
        should_keep_text = bool(old and old.get("text_locked") == "ja")
        same_facts = bool(old and old.get("content_hash") == content_hash)
        old_ai_ok = bool(old and str(old.get("ai_status", "")).startswith("KI erstellt"))

        if should_keep_text or (same_facts and old_ai_ok):
            texts = {key: old.get(key, "") for key in ASSET_KEYS}
            texts["ai_status"] = old.get("ai_status", "")
            cache_used += 1
        else:
            texts = create_sales_assets(
                company=company,
                jobs=jobs,
                benefits=benefits,
                person=research.get("person", ""),
                research=research,
                api_key=openai_api_key,
                model=openai_model,
            )
            if texts.get("ai_status", "").startswith("KI erstellt"):
                ai_created += 1
            else:
                ai_fallback += 1
                ai_failures.append(f"{company}: {texts.get('ai_status', 'Fallback ohne Status')}")

        family_summary: dict[str, int] = {}
        for job in jobs:
            family = _job_family(job.get("title", ""))
            family_summary[family] = family_summary.get(family, 0) + 1
        grouped_jobs = ", ".join(
            f"{amount}× {family}"
            for family, amount in sorted(family_summary.items(), key=lambda item: item[1], reverse=True)[:4]
        )

        row = _empty_row()
        row.update({
            "lead_id": lid,
            "firma": company,
            "hot_status": hot_status,
            "lead_score": str(score),
            "warum_hot": reason,
            "offene_stellen": grouped_jobs or " | ".join(unique([job.get("title", "") for job in jobs])[:6]),
            "anzahl_stellen": str(len(jobs)),
            "orte": " | ".join(unique([job.get("city", "") for job in jobs])),
            "veroeffentlicht_am": max([job.get("published", "") for job in jobs if job.get("published")] or [""]),
            "zuletzt_gefunden": date.today().isoformat(),
            "scan_id": scan_id,
            "source_list": " | ".join(unique([
                source.strip()
                for job in jobs
                for source in str(job.get("source", "")).split("|")
                if source.strip()
            ])),
            "benefits": " | ".join(benefits),
            "ansprechpartner": clean_text(research.get("person", "")),
            "rolle": clean_text(research.get("role", "")),
            "email": clean_text(research.get("email", "")),
            "telefon": clean_text(research.get("phone", "")),
            "website": clean_text(research.get("website", "")),
            "kontaktseite": clean_text(research.get("contact_page", "")),
            "impressum": clean_text(research.get("imprint_page", "")),
            "karriereseite": clean_text(research.get("career_page", "")),
            "stellenlink": next((clean_text(job.get("job_link", "")) for job in jobs if job.get("job_link")), ""),
            "research_status": clean_text(research.get("status", "")),
            "research_notes": clean_text(research.get("notes", "")),
            "employee_hint": clean_text(research.get("employee_hint", "")),
            "location_hint": clean_text(research.get("location_hint", "")),
            "content_hash": content_hash,
            "ai_status": texts.get("ai_status", ""),
            "text_locked": old.get("text_locked", "") if old else "",
            "crm_status": "Neu / nicht abgeglichen",
            "status": old.get("status", "Neu") if old else "Neu",
            "wiedervorlage": old.get("wiedervorlage", "") if old else (date.today() + timedelta(days=1)).isoformat(),
            "notiz": old.get("notiz", "") if old else "",
        })
        for key in ASSET_KEYS:
            row[key] = texts.get(key, "")
        rows.append(row)

    diagnostics = [
        f"Firmen gruppiert: {len(groups)}",
        f"Websites recherchiert: {research_count}",
        f"Passende Websites gefunden: {research_success}",
        f"Gespeicherte Recherche oder Texte wiederverwendet: {cache_used}",
        f"KI Texte erstellt: {ai_created}",
        f"Fallback Texte: {ai_fallback}",
    ]
    diagnostics.extend(f"Recherchefehler: {item}" for item in research_failures[:10])
    diagnostics.extend(f"KI Fehler: {item}" for item in ai_failures[:10])
    return _migrate_frame(pd.DataFrame(rows)), diagnostics


def upsert(existing: pd.DataFrame, fresh: pd.DataFrame, scan_id: str) -> tuple[pd.DataFrame, int, int]:
    existing = _migrate_frame(existing)
    fresh = _migrate_frame(fresh)
    existing_map = {row["lead_id"]: row.to_dict() for _, row in existing.iterrows()}
    inserted = updated = 0

    for _, fresh_row in fresh.iterrows():
        item = fresh_row.to_dict()
        lid = item["lead_id"]
        old = existing_map.get(lid)
        if old:
            for column in MANUAL_COLUMNS:
                if old.get(column, ""):
                    item[column] = old[column]
            if old.get("text_locked") == "ja":
                for column in TEXT_COLUMNS:
                    item[column] = old.get(column, item.get(column, ""))
            for column in RESEARCH_COLUMNS:
                if not item.get(column, "") and old.get(column, ""):
                    item[column] = old[column]
            if item.get("ai_status", "").startswith("Fallback") and old.get("ai_status", "").startswith("KI erstellt"):
                for column in TEXT_COLUMNS:
                    item[column] = old.get(column, item.get(column, ""))
            item["first_seen"] = old.get("first_seen", "") or date.today().isoformat()
            item["first_seen_scan"] = old.get("first_seen_scan", "") or old.get("scan_id", "") or "legacy"
            old_times = int(float(old.get("times_seen", 0) or 0))
            item["times_seen"] = str(old_times + (1 if old.get("scan_id") != scan_id else 0))
            existing_map[lid] = item
            updated += 1
        else:
            item["first_seen"] = date.today().isoformat()
            item["first_seen_scan"] = scan_id
            item["times_seen"] = "1"
            existing_map[lid] = item
            inserted += 1

    merged = _migrate_frame(pd.DataFrame(existing_map.values()))
    merged["lead_score_num"] = pd.to_numeric(merged["lead_score"], errors="coerce").fillna(0)
    merged = merged.sort_values(["lead_score_num", "firma"], ascending=[False, True]).drop(columns=["lead_score_num"])
    return _migrate_frame(merged), inserted, updated


def enrich_existing_leads(
    frame: pd.DataFrame,
    *,
    limit: int,
    serpapi_key: str,
    openai_api_key: str,
    openai_model: str,
) -> tuple[pd.DataFrame, list[str]]:
    frame = _migrate_frame(frame)
    candidates = frame[
        (frame["website"] == "")
        | ((frame["email"] == "") & (frame["telefon"] == ""))
        | (frame["ai_status"].str.startswith("Fallback", na=False))
    ].copy()
    candidates["score_num"] = pd.to_numeric(candidates["lead_score"], errors="coerce").fillna(0)
    candidates = candidates.sort_values("score_num", ascending=False).head(limit)

    researched = websites = contacts = ai_count = 0
    for idx, row in candidates.iterrows():
        city = _split_pipe(row["orte"])[0] if _split_pipe(row["orte"]) else ""
        research = research_company(
            company=row["firma"],
            city=city,
            source_urls=[row["website"], row["stellenlink"], row["karriereseite"]],
            serpapi_key=serpapi_key,
            max_pages=12,
        )
        researched += 1
        if research.get("website"):
            websites += 1
        if research.get("email") or research.get("phone"):
            contacts += 1

        mapping = {
            "website": "website",
            "contact_page": "kontaktseite",
            "imprint_page": "impressum",
            "career_page": "karriereseite",
            "email": "email",
            "phone": "telefon",
            "person": "ansprechpartner",
            "role": "rolle",
            "status": "research_status",
            "notes": "research_notes",
            "employee_hint": "employee_hint",
            "location_hint": "location_hint",
        }
        for source_key, column in mapping.items():
            value = clean_text(research.get(source_key, ""))
            if value:
                frame.loc[idx, column] = value

        pseudo_jobs = [{
            "title": row["offene_stellen"] or "offene Positionen",
            "city": city,
            "description": "",
            "source": row["source_list"],
        }]
        benefits = _split_pipe(row["benefits"])
        if row["text_locked"] != "ja":
            texts = create_sales_assets(
                company=row["firma"],
                jobs=pseudo_jobs,
                benefits=benefits,
                person=frame.loc[idx, "ansprechpartner"],
                research=research,
                api_key=openai_api_key,
                model=openai_model,
            )
            for key in ASSET_KEYS:
                frame.loc[idx, key] = texts.get(key, frame.loc[idx, key])
            frame.loc[idx, "ai_status"] = texts.get("ai_status", "")
            if texts.get("ai_status", "").startswith("KI erstellt"):
                ai_count += 1
        frame.loc[idx, "zuletzt_gefunden"] = date.today().isoformat()

    return _migrate_frame(frame), [
        f"Bestehende Leads geprüft: {researched}",
        f"Websites gefunden: {websites}",
        f"Direkte Kontakte gefunden: {contacts}",
        f"KI Texte erstellt: {ai_count}",
    ]


# ---------------------------------------------------------------------------
# UI und Systemcheck
# ---------------------------------------------------------------------------

openai_api_key = str(st.secrets.get("openai_api_key", "")).strip()
openai_model = str(st.secrets.get("openai_model", "gpt-5-mini")).strip() or "gpt-5-mini"
serpapi_key = str(st.secrets.get("serpapi_key", "")).strip()
adzuna_app_id = str(st.secrets.get("adzuna_app_id", "")).strip()
adzuna_api_key = str(st.secrets.get("adzuna_api_key", "")).strip()

st.sidebar.title("XING Daily Leads")
page = st.sidebar.radio(
    "Bereich",
    ["Daily Leads", "Follow ups", "Alle Leads", "Salesforce Abgleich", "CRM Ausschluss"],
)

st.sidebar.markdown("### Systemcheck")
if storage.mode == "google":
    storage_label = "Google Sheets"
elif storage.mode == "google_error":
    storage_label = "Google Sheets Fehler"
else:
    storage_label = "lokaler Testmodus"
st.sidebar.write(f"Speicher: {storage_label}")
st.sidebar.write(f"OpenAI Paket: {'bereit' if openai_available() else 'fehlt'}")
st.sidebar.write(f"OpenAI Key: {'hinterlegt' if openai_api_key else 'fehlt'}")
st.sidebar.write(f"SerpApi: {'hinterlegt' if serpapi_key else 'nicht hinterlegt'}")
st.sidebar.write(f"Adzuna: {'bereit' if adzuna_app_id and adzuna_api_key else 'Zugangsdaten fehlen'}")

if storage.mode == "google_error":
    st.error(
        "Google Sheets ist konfiguriert, konnte aber nicht verbunden werden. "
        "Die App wechselt aus Sicherheitsgründen nicht in den flüchtigen lokalen Speicher. "
        f"Fehler: {storage.error}"
    )
    st.info("Bei Fehler 429 bitte mindestens 60 Sekunden warten und die App danach rebooten.")
    st.stop()

if st.sidebar.button("Daten aus Speicher neu laden"):
    st.session_state.pop("xing_frame_cache", None)
    st.session_state.pop("xing_exclusions_cache", None)
    st.rerun()

# Load from Google only once per browser session. Normal Streamlit widget
# reruns reuse the in-memory copy and no longer consume Sheets read quota.
if "xing_frame_cache" not in st.session_state:
    st.session_state["xing_frame_cache"] = storage.load()
if "xing_exclusions_cache" not in st.session_state:
    st.session_state["xing_exclusions_cache"] = storage.load_exclusions()

frame = _migrate_frame(st.session_state["xing_frame_cache"].copy())
exclusions = set(st.session_state["xing_exclusions_cache"])

# Einmalige Migration älterer Datensätze. Alte Leads dürfen beim ersten V3 Lauf
# nicht fälschlich als neue Unternehmen des aktuellen Scans erscheinen.
if not frame.empty:
    legacy_mask = frame["first_seen_scan"].astype(str).str.strip().eq("")
    if legacy_mask.any():
        frame.loc[legacy_mask, "first_seen_scan"] = "legacy"
        empty_scan_mask = legacy_mask & frame["scan_id"].astype(str).str.strip().eq("")
        frame.loc[empty_scan_mask, "scan_id"] = "legacy"
        persist_frame(frame)


if page == "Daily Leads":
    st.title("Daily Leads")
    st.caption("Neue Direktkunden zuerst, vorhandene Leads nur bei neuen Informationen aktualisieren.")

    with st.expander("Neue Leads suchen", expanded=frame.empty):
        terms_text = st.text_area("Suchbegriffe, eine Zeile je Begriff", "\n".join(DEFAULT_SEARCH_TERMS))
        regions_text = st.text_area(
            "Regionen im Format Ort,Umkreis",
            "\n".join(f"{city},{radius}" for city, radius in DEFAULT_REGIONS),
        )

        st.markdown("#### Quellen")
        source_columns = st.columns(4)
        use_adzuna = source_columns[0].checkbox("Adzuna", value=bool(adzuna_app_id and adzuna_api_key))
        use_ba = source_columns[1].checkbox("Bundesagentur", value=True)
        use_google = source_columns[2].checkbox("Google Jobs", value=bool(serpapi_key))
        use_careers = source_columns[3].checkbox("Karriereseiten", value=True)

        career_urls_text = st.text_area(
            "Optionale Karriereseiten oder ATS Boards, eine URL je Zeile",
            placeholder=(
                "https://firma.jobs.personio.de\n"
                "https://boards.greenhouse.io/firma\n"
                "https://jobs.lever.co/firma\n"
                "https://firma.de/karriere"
            ),
        )

        settings_columns = st.columns(4)
        days = settings_columns[0].number_input("Veröffentlicht seit Tagen", 1, 30, 14)
        max_pages = settings_columns[1].number_input("Seiten je Suche", 1, 5, 1)
        max_research = settings_columns[2].number_input("Websites recherchieren", 0, 100, 30)
        term_batch_size = settings_columns[3].number_input("Suchbegriffe je Lauf", 1, 50, 12)

        st.caption(
            "Die Begriffe werden pro Lauf rotiert. Dadurch bleibt der Scan schnell und liefert nicht jeden Tag exakt dieselben Firmen."
        )

        uploaded = st.file_uploader(
            "Optionaler Salesforce Export, vorhandene Firmen werden ausgeschlossen",
            type=["csv", "xlsx"],
            key="quick_crm_upload",
        )
        if uploaded is not None:
            try:
                crm_companies, detected_column, row_count = read_company_file(uploaded)
                st.info(f"Firmenspalte erkannt: {detected_column}. Zeilen: {row_count}.")
                if st.button("CRM Firmen übernehmen", key="quick_crm_save"):
                    persist_exclusions(set(exclusions) | crm_companies)
                    st.success(f"{len(crm_companies)} Firmen übernommen.")
                    st.rerun()
            except Exception as exc:
                st.error(str(exc))

        if st.button("Jetzt frische Leads laden", type="primary"):
            all_terms = [line.strip() for line in terms_text.splitlines() if line.strip()]
            regions: list[tuple[str, int]] = []
            try:
                for line in regions_text.splitlines():
                    if not line.strip():
                        continue
                    city, radius = line.rsplit(",", 1)
                    regions.append((city.strip(), int(radius.strip())))
            except ValueError:
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
                st.error("Adzuna ist aktiviert, aber adzuna_app_id oder adzuna_api_key fehlt in den Secrets.")
                st.stop()

            scan_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            search_terms = _rotate_terms(all_terms, int(term_batch_size), scan_id)
            career_urls = [line.strip() for line in career_urls_text.splitlines() if line.strip()]

            progress = st.progress(0, text="Jobs werden aus mehreren Quellen geladen.")
            parsed_jobs, scan_diagnostics = scan_jobs(
                terms=search_terms,
                regions=regions,
                days=int(days),
                max_pages=int(max_pages),
                sources=sources,
                career_urls=career_urls,
                serpapi_key=serpapi_key,
                adzuna_app_id=adzuna_app_id,
                adzuna_api_key=adzuna_api_key,
            )
            progress.progress(0.55, text="Firmen werden priorisiert und recherchiert.")

            fresh, research_diagnostics = build_leads(
                parsed_jobs=parsed_jobs,
                exclusions=exclusions,
                max_research=int(max_research),
                serpapi_key=serpapi_key,
                existing=frame,
                openai_api_key=openai_api_key,
                openai_model=openai_model,
                scan_id=scan_id,
            )
            merged, inserted, updated = upsert(frame, fresh, scan_id)
            merged = apply_crm_status(merged, exclusions)
            persist_frame(merged)
            frame = merged
            progress.empty()

            st.success(f"{inserted} neue Firmen, {updated} vorhandene Firmen aktualisiert.")
            st.write(f"Verwendete Suchbegriffe: {', '.join(search_terms)}")
            st.write(f"Priorisierte Stellen: {len(parsed_jobs)}")
            st.write(f"Firmen Leads dieses Laufs: {len(fresh)}")
            with st.expander("Technische Details", expanded=inserted == 0):
                for message in scan_diagnostics + research_diagnostics:
                    st.write(f"• {message}")
            if inserted == 0:
                st.warning(
                    "Dieser Lauf hat keine neue Firma geliefert. Die App zeigt deshalb nicht einfach wieder alle alten Leads als neu an. "
                    "Starte einen weiteren Lauf mit anderen Begriffen, größerem Zeitraum oder einer zusätzlichen Region."
                )

    incomplete_count = int(
        (
            (frame["website"] == "")
            | ((frame["email"] == "") & (frame["telefon"] == ""))
            | frame["ai_status"].str.startswith("Fallback", na=False)
        ).sum()
    ) if not frame.empty else 0

    with st.expander(f"Bestehende Leads nachrecherchieren ({incomplete_count} unvollständig)"):
        enrich_limit = st.number_input("Anzahl Leads", 1, 100, 20, key="enrich_limit")
        st.caption(
            "Diese Funktion sucht für bereits gespeicherte Leads erneut nach Website, Impressum, Kontakt, Telefon und Ansprechpartner."
        )
        if st.button("Unvollständige Leads jetzt anreichern", disabled=incomplete_count == 0):
            progress = st.progress(0, text="Bestehende Leads werden nachrecherchiert.")
            enriched, diagnostics = enrich_existing_leads(
                frame,
                limit=int(enrich_limit),
                serpapi_key=serpapi_key,
                openai_api_key=openai_api_key,
                openai_model=openai_model,
            )
            enriched = apply_crm_status(enriched, exclusions)
            persist_frame(enriched)
            frame = enriched
            progress.empty()
            st.success("Nachrecherche abgeschlossen.")
            for message in diagnostics:
                st.write(f"• {message}")

    if frame.empty:
        st.info("Noch keine Leads vorhanden. Starte oben die erste Suche.")
    else:
        # Nur echte Scan IDs berücksichtigen. Der Migrationswert "legacy" darf
        # niemals als letzter Scan ausgewählt werden.
        scan_ids = [
            str(value) for value in frame["scan_id"].unique().tolist()
            if re.fullmatch(r"\d{8}T\d{6}Z", str(value or ""))
        ]
        latest_scan = max(scan_ids) if scan_ids else ""
        latest_frame = frame[frame["scan_id"] == latest_scan].copy() if latest_scan else frame.copy()
        latest_frame = latest_frame[
            latest_frame["status"].isin(["Neu", "Für morgen", "Mail vorbereitet"])
            & (latest_frame["crm_status"] != "Bereits in Salesforce")
        ].copy()
        latest_frame["score_num"] = pd.to_numeric(latest_frame["lead_score"], errors="coerce").fillna(0)
        latest_frame = latest_frame.sort_values("score_num", ascending=False)
        new_only = latest_frame[latest_frame["first_seen_scan"] == latest_scan].copy() if latest_scan else latest_frame.copy()

        metric_columns = st.columns(4)
        metric_columns[0].metric("Neu im letzten Lauf", len(new_only))
        metric_columns[1].metric("HOT im letzten Lauf", int((latest_frame["score_num"] >= 75).sum()))
        metric_columns[2].metric(
            "Kontaktierbar",
            int(((latest_frame["email"] != "") | (latest_frame["telefon"] != "")).sum()),
        )
        metric_columns[3].metric(
            "KI Texte",
            int(latest_frame["ai_status"].str.startswith("KI erstellt", na=False).sum()),
        )

        if not latest_frame.empty and not latest_frame["ai_status"].str.startswith("KI erstellt", na=False).any():
            failures = unique(latest_frame["ai_status"].tolist())[:3]
            st.error(
                "Für diesen Lauf wurde kein einziger KI Text erstellt. "
                "Die angezeigten Texte sind Fallbacks. Status: " + " | ".join(failures)
            )

        view_mode = st.radio(
            "Ansicht",
            ["Nur neue Unternehmen", "Letzten Lauf komplett", "Alle offenen Leads"],
            horizontal=True,
        )
        if view_mode == "Nur neue Unternehmen":
            display_frame = new_only.head(100)
        elif view_mode == "Letzten Lauf komplett":
            display_frame = latest_frame.head(150)
        else:
            display_frame = frame[
                ~frame["status"].isin(["In Salesforce übernommen", "Ausschließen"])
                & (frame["crm_status"] != "Bereits in Salesforce")
            ].copy()
            display_frame["score_num"] = pd.to_numeric(display_frame["lead_score"], errors="coerce").fillna(0)
            display_frame = display_frame.sort_values("score_num", ascending=False).head(250)

        if display_frame.empty:
            st.info("In dieser Ansicht gibt es aktuell keine Leads.")

        for idx, row in display_frame.iterrows():
            with st.container(border=True):
                header_columns = st.columns([5, 2, 2])
                header_columns[0].subheader(row["firma"])
                header_columns[1].metric(row["hot_status"], int(float(row["lead_score"] or 0)))
                header_columns[2].write(row["veroeffentlicht_am"] or "Datum offen")

                st.write(f"**Stellenschwerpunkte:** {row['offene_stellen']}")
                st.write(f"**Warum interessant:** {row['warum_hot'] or 'noch keine belastbare Begründung'}")
                if row["benefits"]:
                    st.write(f"**Benefits:** {row['benefits']}")
                if row["source_list"]:
                    st.caption(f"Quellen: {row['source_list']} · bisher {row['times_seen'] or '1'} Mal gefunden")

                contact_columns = st.columns(3)
                contact_columns[0].write(f"**Ansprechpartner:** {row['ansprechpartner'] or 'nicht sicher gefunden'}")
                contact_columns[1].write(f"**E Mail:** {row['email'] or 'nicht gefunden'}")
                contact_columns[2].write(f"**Telefon:** {row['telefon'] or 'nicht gefunden'}")

                st.caption(
                    f"Recherche: {row['research_status'] or 'offen'} · {row['research_notes'] or 'keine Details'}"
                )
                st.caption(f"Texte: {row['ai_status'] or 'nicht erstellt'}")

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

                tabs = st.tabs(["Call", "Erstmail", "Follow ups", "Bearbeiten"])
                with tabs[0]:
                    call_value = st.text_area(
                        "Call Opener",
                        row["call_opener"],
                        height=120,
                        key=f"call_{row['lead_id']}",
                    )
                    discovery_value = st.text_area(
                        "Discovery Fragen",
                        row["discovery_fragen"],
                        height=230,
                        key=f"disc_{row['lead_id']}",
                    )
                    challenger_value = st.text_area(
                        "Challenger Reframe",
                        row["challenger_reframe"],
                        height=130,
                        key=f"challenger_{row['lead_id']}",
                    )
                with tabs[1]:
                    subject_value = st.text_input(
                        "Betreff",
                        row["erstmail_betreff"],
                        key=f"subject_{row['lead_id']}",
                    )
                    mail_value = st.text_area(
                        "Mail",
                        row["erstmail"],
                        height=300,
                        key=f"mail_{row['lead_id']}",
                    )
                with tabs[2]:
                    follow1_value = st.text_area(
                        "Follow up 1",
                        row["follow_up_1"],
                        height=220,
                        key=f"follow1_{row['lead_id']}",
                    )
                    follow2_value = st.text_area(
                        "Follow up 2",
                        row["follow_up_2"],
                        height=220,
                        key=f"follow2_{row['lead_id']}",
                    )
                with tabs[3]:
                    status_value = st.selectbox(
                        "Status",
                        STATUSES,
                        index=STATUSES.index(row["status"]) if row["status"] in STATUSES else 0,
                        key=f"status_{row['lead_id']}",
                    )
                    parsed_due = pd.to_datetime(row["wiedervorlage"], errors="coerce")
                    due_default = parsed_due.date() if not pd.isna(parsed_due) else date.today() + timedelta(days=2)
                    due_value = st.date_input(
                        "Wiedervorlage",
                        value=due_default,
                        key=f"due_{row['lead_id']}",
                    )
                    note_value = st.text_area(
                        "Arbeitsnotiz",
                        row["notiz"],
                        key=f"note_{row['lead_id']}",
                    )
                    lock_value = st.checkbox(
                        "Meine Textänderungen bei künftigen Scans beibehalten",
                        value=row["text_locked"] == "ja",
                        key=f"lock_{row['lead_id']}",
                    )
                    if st.button("Änderungen speichern", key=f"save_{row['lead_id']}"):
                        frame.loc[idx, "call_opener"] = call_value
                        frame.loc[idx, "discovery_fragen"] = discovery_value
                        frame.loc[idx, "challenger_reframe"] = challenger_value
                        frame.loc[idx, "erstmail_betreff"] = subject_value
                        frame.loc[idx, "erstmail"] = mail_value
                        frame.loc[idx, "follow_up_1"] = follow1_value
                        frame.loc[idx, "follow_up_2"] = follow2_value
                        frame.loc[idx, "status"] = status_value
                        frame.loc[idx, "wiedervorlage"] = due_value.isoformat()
                        frame.loc[idx, "notiz"] = note_value
                        frame.loc[idx, "text_locked"] = "ja" if lock_value else ""
                        persist_frame(frame)
                        st.success("Gespeichert.")
                        st.rerun()

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
        for idx, row in due_frame.iterrows():
            with st.container(border=True):
                st.subheader(row["firma"])
                st.write(f"**Fällig:** {row['wiedervorlage']} · **Status:** {row['status']}")
                st.write(f"**Kontakt:** {row['ansprechpartner']} · {row['email']} · {row['telefon']}")
                st.text_area("Follow up", row["follow_up_1"], height=240, key=f"due_mail_{row['lead_id']}")
                action_columns = st.columns(2)
                if action_columns[0].button("In Salesforce übernommen", key=f"sf_{row['lead_id']}"):
                    frame.loc[idx, "status"] = "In Salesforce übernommen"
                    persist_frame(frame)
                    st.rerun()
                if action_columns[1].button("Noch drei Tage", key=f"plus3_{row['lead_id']}"):
                    frame.loc[idx, "wiedervorlage"] = (date.today() + timedelta(days=3)).isoformat()
                    persist_frame(frame)
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
        "hot_status", "lead_score", "firma", "crm_status", "anzahl_stellen",
        "offene_stellen", "orte", "ansprechpartner", "rolle", "email", "telefon",
        "website", "kontaktseite", "research_status", "ai_status", "status",
        "wiedervorlage", "first_seen", "zuletzt_gefunden", "times_seen",
    ]].copy()
    table["lead_score"] = pd.to_numeric(table["lead_score"], errors="coerce").fillna(0).astype(int)
    st.dataframe(
        table,
        use_container_width=True,
        hide_index=True,
        column_config={
            "website": st.column_config.LinkColumn("Website"),
            "kontaktseite": st.column_config.LinkColumn("Kontaktseite"),
            "lead_score": st.column_config.NumberColumn("Score", format="%d"),
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
    st.write(
        "Lade einen Salesforce Account Export als CSV oder XLSX hoch. Vorhandene Firmen werden dauerhaft ausgeschlossen."
    )
    crm_file = st.file_uploader("Salesforce Export hochladen", type=["csv", "xlsx"], key="salesforce_export")
    if crm_file is not None:
        try:
            crm_companies, detected_column, row_count = read_company_file(crm_file)
            matches = {
                normalize_company(company)
                for company in frame.get("firma", [])
                if _crm_match(company, crm_companies)
            }
            metric_columns = st.columns(3)
            metric_columns[0].metric("Zeilen im Export", row_count)
            metric_columns[1].metric("Eindeutige Firmen", len(crm_companies))
            metric_columns[2].metric("Treffer in Leadliste", len(matches))
            st.info(f"Erkannte Firmenspalte: {detected_column}")
            if st.button("Salesforce Firmen dauerhaft abgleichen"):
                combined = set(exclusions) | crm_companies
                persist_exclusions(combined)
                frame = apply_crm_status(frame, combined)
                persist_frame(frame)
                st.success(f"{len(crm_companies)} Salesforce Firmen gespeichert.")
                st.rerun()
        except Exception as exc:
            st.error(str(exc))

elif page == "CRM Ausschluss":
    st.title("CRM Ausschluss")
    st.caption("Diese Firmen werden bei neuen Suchläufen nicht mehr als Leads angelegt.")
    manual = st.text_area("Firmen hinzufügen, eine Zeile je Firma")
    if st.button("Firmen speichern"):
        new_items = {normalize_company(value) for value in manual.splitlines() if value.strip()}
        persist_exclusions(set(exclusions) | new_items)
        st.success("Ausschlussliste aktualisiert.")
        st.rerun()
    st.write(f"**Aktuell gespeichert:** {len(exclusions)} Firmen")
    if exclusions:
        st.dataframe(pd.DataFrame({"Firma normalisiert": sorted(exclusions)}), hide_index=True)