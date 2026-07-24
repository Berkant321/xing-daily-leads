from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any

import pandas as pd
from bs4 import BeautifulSoup

from research import normalize_company as research_normalize_company
from research import research_company
from sales_ai import ASSET_KEYS, create_sales_assets

PIPELINE_SCHEMA_VERSION = "6.0.0"


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
    "deutsche post", "dhl", "volkswagen", "mercedes-benz", "bmw group",
    "continental", "kaufland", "allianz", "helios", "asklepios", "sana kliniken",
    "ameos", "korian", "fresenius", "basf", "bayer ag", "rwe ag", "e.on",
    "sparkasse", "volksbank", "tüv nord", "tüv süd", "tüv rheinland",
]

STATUSES = [
    "Neu",
    "Mail vorbereitet",
    "Versendet",
    "Follow up fällig",
    "Antwort erhalten",
    "Termin vereinbart",
    "Für morgen",
    "In Salesforce übernommen",
    "Ausschließen",
]

COLUMNS = [
    "lead_id",
    "firma",
    "hot_status",
    "lead_score",
    "discovery_score",
    "lead_segment",
    "size_fit",
    "small_business_score",
    "size_reason",
    "warum_hot",
    "offene_stellen",
    "job_titles",
    "job_context",
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
    "email_quality",
    "telefon",
    "website",
    "kontaktseite",
    "impressum",
    "karriereseite",
    "stellenlink",
    "pipeline_stage",
    "research_status",
    "research_notes",
    "research_text",
    "research_attempts",
    "research_updated_at",
    "employee_hint",
    "location_hint",
    "content_hash",
    "ai_status",
    "ai_attempts",
    "ai_updated_at",
    "last_error",
    "text_locked",
    "crm_status",
    "erstmail_betreff",
    "erstmail",
    "personalization_evidence",
    "mail_variant",
    "quality_score",
    "quality_status",
    "quality_notes",
    "call_opener",
    "discovery_fragen",
    "challenger_reframe",
    "follow_up_1",
    "follow_up_2",
    "status",
    "wiedervorlage",
    "versendet_am",
    "follow_up_1_am",
    "follow_up_2_am",
    "antwort_status",
    "antwort_am",
    "antwort_notiz",
    "termin_am",
    "absagegrund",
    "notiz",
]

JOB_COLUMNS = [
    "job_id",
    "lead_id",
    "firma",
    "position",
    "ort",
    "veroeffentlicht_am",
    "quelle",
    "suchbegriff",
    "stellenlink",
    "referenz",
    "lead_segment",
    "size_fit",
    "small_business_score",
    "lead_score",
    "email",
    "telefon",
    "ansprechpartner",
    "beschreibung",
    "first_seen",
    "last_seen",
    "times_seen",
    "scan_id",
    "kampagne",
    "status",
    "notiz",
]

MANUAL_COLUMNS = [
    "status", "wiedervorlage", "notiz", "text_locked",
    "versendet_am", "follow_up_1_am", "follow_up_2_am",
    "antwort_status", "antwort_am", "antwort_notiz", "termin_am", "absagegrund",
]
RESEARCH_COLUMNS = [
    "ansprechpartner", "rolle", "email", "email_quality", "telefon", "website", "kontaktseite",
    "impressum", "karriereseite", "research_status", "research_notes", "research_text",
    "research_attempts", "research_updated_at", "employee_hint", "location_hint",
]
TEXT_COLUMNS = ASSET_KEYS + [
    "personalization_evidence", "mail_variant", "quality_score", "quality_status", "quality_notes",
    "ai_status", "ai_attempts", "ai_updated_at", "content_hash",
]


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    if "<" in text and ">" in text:
        text = BeautifulSoup(text, "html.parser").get_text(" ")
    return re.sub(r"\s+", " ", text).strip()


def normalize_company(name: str) -> str:
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


def split_pipe(value: str) -> list[str]:
    return [clean_text(item) for item in str(value or "").split("|") if clean_text(item)]


def classify_email_quality(email: str) -> tuple[str, int]:
    email = clean_text(email).lower()
    local = email.split("@", 1)[0] if "@" in email else ""
    if not local:
        return "Fehlt", 0
    blocked = ("noreply", "no reply", "datenschutz", "privacy", "newsletter", "marketing")
    if any(token.replace(" ", "") in local.replace("-", "").replace("_", "") for token in blocked):
        return "Ungeeignet", 0
    recruiting = ("recruit", "personal", "karriere", "bewerbung", "jobs", "talent", "people", "hr")
    generic = ("info", "kontakt", "office", "service", "hello", "mail")
    if any(local == token or local.startswith(token + ".") or local.startswith(token + "-") for token in recruiting):
        return "Recruiting", 12
    if any(local == token or local.startswith(token + ".") or local.startswith(token + "-") for token in generic):
        return "Allgemein", 4
    if "." in local or "_" in local or len(local) >= 5:
        return "Direkt", 15
    return "Allgemein", 4


def evaluate_lead_quality(row: dict[str, Any]) -> tuple[int, str, str]:
    company = clean_text(row.get("firma", ""))
    subject = clean_text(row.get("erstmail_betreff", ""))
    mail = str(row.get("erstmail", "") or "").strip()
    job_titles = split_pipe(row.get("job_titles", ""))
    evidence = clean_text(row.get("personalization_evidence", ""))
    email = clean_text(row.get("email", ""))
    email_label, email_points = classify_email_quality(email)
    score = 0
    strengths: list[str] = []
    gaps: list[str] = []

    if job_titles and not all(title.lower() in {"offene positionen", "offene stellen"} for title in job_titles):
        score += 12
        strengths.append("konkrete Vakanz")
    else:
        gaps.append("keine konkrete Vakanz")
    if clean_text(row.get("veroeffentlicht_am", "")):
        score += 4
    if clean_text(row.get("stellenlink", "")) or clean_text(row.get("source_list", "")):
        score += 4
    if clean_text(row.get("website", "")):
        score += 5
    research_text = clean_text(row.get("research_text", ""))
    if len(research_text) >= 250:
        score += 8
        strengths.append("Website Fakten vorhanden")
    elif len(research_text) >= 80:
        score += 4
    else:
        gaps.append("wenig Unternehmenskontext")
    if evidence:
        score += 10
        strengths.append("Personalisierung belegt")
    else:
        gaps.append("Personalisierungsbeleg fehlt")
    if clean_text(row.get("ansprechpartner", "")):
        score += 10
        strengths.append("Ansprechpartner")
    else:
        gaps.append("Ansprechpartner fehlt")
    score += email_points
    if email_label in {"Direkt", "Recruiting"}:
        strengths.append(f"{email_label} E Mail")
    elif email_label == "Allgemein":
        gaps.append("nur allgemeine E Mail")
    else:
        gaps.append("E Mail fehlt")
    if clean_text(row.get("telefon", "")):
        score += 4
    if split_pipe(row.get("benefits", "")):
        score += 4
    exact_subject = f"Exklusive Einladung | {company}" if company else "Exklusive Einladung"
    if subject == exact_subject:
        score += 8
    else:
        gaps.append("Betreff weicht ab")

    required = [
        "XING Kampagne",
        "nicht nur darum",
        "gezielt",
        "direkt ansprechen",
        "drehen Sie den Spieß um",
        "vormittags oder nachmittags",
    ]
    found = sum(1 for phrase in required if phrase.lower() in mail.lower())
    score += round(found / len(required) * 13)
    if found == len(required):
        strengths.append("Kampagnenstruktur vollständig")
    else:
        gaps.append(f"Kampagnenstruktur {found} von {len(required)}")
    word_count = len(re.findall(r"\b\w+\b", mail))
    if 105 <= word_count <= 195:
        score += 5
    elif mail:
        gaps.append(f"Mail Länge {word_count} Wörter")
    else:
        gaps.append("Mail fehlt")
    if company and company.lower() in mail.lower():
        score += 4
    if "Senior Account Executive" in mail and "Berkant Devrim" in mail:
        score += 3
    if not re.search(r"\s[–—]\s", mail):
        score += 2

    score = max(0, min(100, int(score)))
    hard_ready = bool(
        mail
        and job_titles
        and evidence
        and email_label in {"Direkt", "Recruiting"}
        and subject == exact_subject
        and found == len(required)
    )
    if score >= 85 and hard_ready:
        status = "Versandbereit"
    elif score >= 70:
        status = "Kurz prüfen"
    else:
        status = "Nicht freigeben"
    notes = "; ".join((strengths[:5] + ["Offen: " + ", ".join(gaps[:5]) if gaps else ""]))
    return score, status, notes.strip("; ")


def refresh_quality(frame: pd.DataFrame | None) -> tuple[pd.DataFrame, bool]:
    result = migrate_frame(frame)
    changed = False
    for index, row in result.iterrows():
        email_label, _ = classify_email_quality(row.get("email", ""))
        score, status, notes = evaluate_lead_quality(row.to_dict())
        values = {
            "email_quality": email_label,
            "quality_score": str(score),
            "quality_status": status,
            "quality_notes": notes,
        }
        for column, value in values.items():
            if clean_text(result.at[index, column]) != clean_text(value):
                result.at[index, column] = value
                changed = True
    return result, changed


def job_id(job: dict[str, Any]) -> str:
    """Stabile ID pro Firma, Position und Ort.

    Dieselbe Vakanz aus mehreren Quellen landet damit in nur einer Tabellenzeile.
    """
    key = "|".join([
        normalize_company(clean_text(job.get("company", ""))),
        re.sub(r"\W+", "", clean_text(job.get("title", "")).lower()),
        re.sub(r"\W+", "", clean_text(job.get("city", "")).lower()),
    ])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:18]


def migrate_jobs_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    result = frame.copy() if frame is not None else pd.DataFrame()
    for column in JOB_COLUMNS:
        if column not in result.columns:
            result[column] = ""
    return result.reindex(columns=JOB_COLUMNS).fillna("").astype(str)


def build_job_rows(
    parsed_jobs: list[dict[str, Any]],
    *,
    scan_id: str,
    campaign: str,
) -> pd.DataFrame:
    """Erzeugt eine echte Stellen-Tabelle: eine Zeile pro Vakanz."""
    today = date.today().isoformat()
    rows: list[dict[str, str]] = []
    for job in parsed_jobs:
        company = clean_text(job.get("company", ""))
        title = clean_text(job.get("title", ""))
        if not company or not title:
            continue
        row = {column: "" for column in JOB_COLUMNS}
        row.update({
            "job_id": job_id(job),
            "lead_id": lead_id(company),
            "firma": company,
            "position": title,
            "ort": clean_text(job.get("city", "")),
            "veroeffentlicht_am": clean_text(job.get("published", "")),
            "quelle": clean_text(job.get("source", "")),
            "suchbegriff": clean_text(job.get("term", "")),
            "stellenlink": clean_text(job.get("job_link", "") or job.get("external_url", "")),
            "referenz": clean_text(job.get("reference", "")),
            "lead_segment": clean_text(job.get("lead_segment", "")),
            "size_fit": clean_text(job.get("size_fit", "")),
            "small_business_score": str(job.get("small_business_score", "") or ""),
            "lead_score": str(job.get("lead_score", "") or ""),
            "email": clean_text(job.get("email", "")),
            "telefon": clean_text(job.get("phone", "")),
            "ansprechpartner": clean_text(job.get("contact", "")),
            "beschreibung": clean_text(job.get("description", ""))[:3000],
            "first_seen": today,
            "last_seen": today,
            "times_seen": "1",
            "scan_id": scan_id,
            "kampagne": campaign,
            "status": "Neu",
            "notiz": "",
        })
        rows.append(row)
    return migrate_jobs_frame(pd.DataFrame(rows))


def backfill_jobs_from_leads(leads: pd.DataFrame) -> pd.DataFrame:
    """Rekonstruiert aus alten Firmenzeilen eine nutzbare Stellen-Tabelle.

    Historische Einzelquellen lassen sich nicht vollständig zurückholen. Die Zeilen
    werden deshalb klar als Bestandsimport gekennzeichnet; neue Scans liefern danach
    die exakten Daten pro Vakanz.
    """
    leads = migrate_frame(leads)
    rows: list[dict[str, Any]] = []
    for _, lead in leads.iterrows():
        company = clean_text(lead.get("firma", ""))
        if not company:
            continue
        titles = split_pipe(lead.get("job_titles", ""))
        if not titles:
            continue
        locations = split_pipe(lead.get("orte", ""))
        location = locations[0] if locations else ""
        for title in titles:
            job = {
                "company": company,
                "title": title,
                "city": location,
                "published": clean_text(lead.get("veroeffentlicht_am", "")),
                "source": clean_text(lead.get("source_list", "")) or "Bestandsimport",
                "term": title,
                "job_link": clean_text(lead.get("stellenlink", "")),
                "reference": "",
                "lead_segment": clean_text(lead.get("lead_segment", "")),
                "size_fit": clean_text(lead.get("size_fit", "")),
                "small_business_score": clean_text(lead.get("small_business_score", "")),
                "lead_score": clean_text(lead.get("lead_score", "")),
                "email": clean_text(lead.get("email", "")),
                "phone": clean_text(lead.get("telefon", "")),
                "contact": clean_text(lead.get("ansprechpartner", "")),
                "description": "Aus bestehendem Lead rekonstruiert. Neue Scans ergänzen exakte Quelldaten.",
            }
            job_frame = build_job_rows(
                [job],
                scan_id=clean_text(lead.get("scan_id", "")) or "legacy",
                campaign="Bestandsimport",
            )
            if job_frame.empty:
                continue
            row = job_frame.iloc[0].to_dict()
            row["first_seen"] = clean_text(lead.get("first_seen", "")) or row["first_seen"]
            row["last_seen"] = clean_text(lead.get("zuletzt_gefunden", "")) or row["last_seen"]
            row["times_seen"] = clean_text(lead.get("times_seen", "")) or "1"
            row["status"] = "Bestandsimport"
            rows.append(row)
    return migrate_jobs_frame(pd.DataFrame(rows)).drop_duplicates(subset=["job_id"], keep="last")


def upsert_jobs(
    existing: pd.DataFrame,
    fresh: pd.DataFrame,
    *,
    scan_id: str,
) -> tuple[pd.DataFrame, int, int, set[str]]:
    """Fügt Stellen ohne Dubletten ein und bewahrt manuelle Felder."""
    existing = migrate_jobs_frame(existing)
    fresh = migrate_jobs_frame(fresh)
    existing_map = {row["job_id"]: row.to_dict() for _, row in existing.iterrows() if row["job_id"]}
    inserted = updated = 0
    changed_ids: set[str] = set()

    for _, fresh_row in fresh.iterrows():
        item = fresh_row.to_dict()
        jid = item["job_id"]
        old = existing_map.get(jid)
        if old:
            item["first_seen"] = old.get("first_seen", "") or item["first_seen"]
            item["status"] = old.get("status", "") or item["status"]
            item["notiz"] = old.get("notiz", "")
            old_times = int(float(old.get("times_seen", 0) or 0))
            item["times_seen"] = str(old_times + (1 if old.get("scan_id") != scan_id else 0))
            # Vorhandene Kontaktdaten bleiben erhalten, wenn die neue Quelle leer ist.
            for column in ("email", "telefon", "ansprechpartner", "stellenlink", "beschreibung"):
                if not item.get(column) and old.get(column):
                    item[column] = old[column]
            existing_map[jid] = item
            updated += 1
        else:
            existing_map[jid] = item
            inserted += 1
        changed_ids.add(jid)

    merged = migrate_jobs_frame(pd.DataFrame(existing_map.values()))
    if not merged.empty:
        merged["last_seen_sort"] = pd.to_datetime(merged["last_seen"], errors="coerce")
        merged["score_sort"] = pd.to_numeric(merged["small_business_score"], errors="coerce").fillna(0)
        merged = merged.sort_values(
            ["last_seen_sort", "score_sort", "firma", "position"],
            ascending=[False, False, True, True],
        ).drop(columns=["last_seen_sort", "score_sort"])
    return migrate_jobs_frame(merged), inserted, updated, changed_ids


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


def job_family(title: str) -> str:
    value = normalize_company(title)
    families = {
        "Steuer und Finanzen": ["steuerfach", "bilanzbuch", "finanzbuch", "buchhalter", "controller", "lohn", "tax", "accounting"],
        "Recht": ["rechtsanw", "jurist", "legal", "notar", "paralegal", "wirtschaftsrecht"],
        "Therapie": ["physio", "ergotherapeut", "logop", "therapeut", "heilpaed"],
        "Pflege und Medizin": ["pflege", "medizinische fachang", "arzt", "arztin", "mfa", "gesundheits", "kranken", "zahn"],
        "Elektro und Technik": ["elektroniker", "elektriker", "mechatron", "servicetechn", "sps", "automation", "instandhalt"],
        "Metall und Produktion": ["schlosser", "schwei", "industriemechan", "zerspan", "cnc", "monteur", "metall", "produktion", "maschinenbedien"],
        "Bau und Engineering": ["bauleiter", "architekt", "ingenieur", "konstrukteur", "projektleiter", "tiefbau", "hochbau", "tga", "kalkulator", "polier"],
        "IT und Daten": ["software", "entwickler", "developer", "devops", "systemadministrator", "it support", "informatik", "data", "cloud", "security"],
        "Vertrieb und Marketing": ["vertrieb", "sales", "account manager", "business development", "marketing", "e commerce", "performance"],
        "Logistik und Einkauf": ["lager", "logistik", "stapler", "fahrer", "disponent", "verlader", "berufskraft", "spedition", "einkauf"],
        "Pharma und Forschung": ["pharma", "labor", "chemie", "regulatory", "clinical", "apotheker", "pta", "forschung"],
        "Personal und Verwaltung": ["sachbearbeiter", "assistenz", "office", "personalreferent", "recruit", "human resources", "kaufmann", "kauffrau"],
        "Gastronomie und Hotellerie": ["koch", "kueche", "restaurant", "hotel", "servicekraft", "rezeption"],
    }
    for family, keywords in families.items():
        if any(keyword in value for keyword in keywords):
            return family
    return "Sonstige"



def infer_lead_segment(text: str) -> str:
    value = normalize_company(text)
    groups = {
        "Therapiepraxis": ["physio", "ergotherapeut", "logop", "sprachtherap", "therapie", "praxis"],
        "Steuer und Buchhaltung": ["steuerfach", "steuerberater", "steuerberatung", "steuerkanzlei", "bilanzbuch", "lohnbuch", "datev", "accounting"],
        "Recht und Kanzlei": ["rechtsanw", "jurist", "wirtschaftskanzlei", "notar", "legal"],
        "Pflege und Medizin": ["ambulante pflege", "pflegedienst", "sozialstation", "pflegefach", "medizinische fachang", "mfa", "arztpraxis", "zahnarzt"],
        "Handwerk und Technik": ["elektroniker", "elektriker", "mechatron", "anlagenmechaniker", "shk", "sanitaer", "heizung", "klima", "servicetechn", "schweiss", "metallbau", "tischler", "schreiner"],
        "Industrie und Produktion": ["produktion", "maschinenbau", "industriemechan", "cnc", "zerspan", "instandhalt", "qualitaetssicherung"],
        "Bau und Engineering": ["ingenieurbuero", "planungsbuero", "bauleiter", "projektingenieur", "konstrukteur", "architekturbuero", "tga", "kalkulator"],
        "IT und Digitalisierung": ["softwareentwickler", "developer", "devops", "systemadministrator", "softwarehaus", "it dienstleister", "cloud", "data"],
        "Vertrieb und Marketing": ["vertrieb", "sales", "account manager", "business development", "marketing", "e commerce"],
        "Logistik und Einkauf": ["logistik", "lager", "spedition", "disponent", "berufskraft", "einkauf"],
        "Pharma und Forschung": ["pharma", "labor", "chemie", "regulatory", "clinical", "apotheke", "forschung"],
        "Personal und Verwaltung": ["personalreferent", "recruit", "human resources", "sachbearbeiter", "assistenz", "office", "kaufmann"],
        "Gastronomie und Hotellerie": ["gastronomie", "hotel", "restaurant", "koch", "kueche", "rezeption"],
    }
    best = "Direktkunde"
    best_count = 0
    for segment, keywords in groups.items():
        count = sum(1 for keyword in keywords if keyword in value)
        if count > best_count:
            best = segment
            best_count = count
    return best



def _hint_number(value: Any) -> int:
    numbers = [int(item) for item in re.findall(r"\d+", clean_text(value))]
    return max(numbers or [0])


def classify_size_fit(
    *,
    company: str,
    job_count: int,
    locations: int,
    segment: str,
    employee_hint: str = "",
    current_score: int = 0,
) -> tuple[str, int, str]:
    low = normalize_company(company)
    employee_count = _hint_number(employee_hint)
    enterprise_words = [
        "konzern", "universitaetsklinikum", "deutsche bahn", "amazon", "siemens",
        "bosch", "lidl", "aldi", "rewe group", "telekom", "dhl", "bundeswehr",
    ]
    large_name = bool(likely_large_or_agency(company)) or any(word in low for word in enterprise_words)
    reasons: list[str] = []
    score = current_score or 50

    if job_count <= 3:
        score += 18
        reasons.append(f"{job_count} offene Stelle" + ("n" if job_count != 1 else ""))
    elif job_count <= 8:
        score += 8
        reasons.append(f"{job_count} offene Stellen")
    elif job_count <= 15:
        score -= 5
    elif job_count <= 25:
        score -= 15
    else:
        score -= 50
        reasons.append(f"zu viele Stellen: {job_count}")

    if locations <= 1:
        score += 10
        reasons.append("regionaler Arbeitgeber")
    elif locations <= 3:
        score += 2
    elif locations <= 6:
        score -= 8
    elif locations <= 12:
        score -= 18
    else:
        score -= 45
        reasons.append(f"zu viele Standorte: {locations}")

    if segment not in {"Direktkunde", "Kleiner Direktkunde"}:
        score += 8
        reasons.append(segment)

    if employee_count:
        if employee_count <= 50:
            score += 12
            reasons.append(f"bis ca. {employee_count} Mitarbeitende")
        elif employee_count <= 250:
            score += 3
        elif employee_count <= 1000:
            score -= 5
        elif employee_count <= 3000:
            score -= 18
        else:
            score -= 55
            reasons.append(f"zu groß: {employee_count} Mitarbeitende")

    if large_name:
        score -= 60
        reasons.append("bekannte Großstruktur")

    score = max(0, min(100, score))
    if large_name or job_count > 25 or locations > 12 or employee_count > 3000 or score < 25:
        fit = "Groß oder unpassend"
    elif score >= 70:
        fit = "Klein"
    else:
        fit = "Mittel"
    return fit, score, "; ".join(reasons[:6])


def empty_row() -> dict[str, str]:
    return {column: "" for column in COLUMNS}


def migrate_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    frame = frame.copy() if frame is not None else pd.DataFrame()
    for column in COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    frame = frame.reindex(columns=COLUMNS).fillna("").astype(str)

    # Bestehende Leads aus älteren Versionen erhalten automatisch einen KMU Fit.
    for index, row in frame.iterrows():
        segment = clean_text(row.get("lead_segment", "")) or infer_lead_segment(
            " ".join([row.get("firma", ""), row.get("job_titles", ""), row.get("offene_stellen", "")])
        )
        locations = max(1, len(split_pipe(row.get("orte", ""))))
        try:
            job_count = max(1, int(float(row.get("anzahl_stellen", 1) or 1)))
        except (TypeError, ValueError):
            job_count = 1
        try:
            current_score = int(float(row.get("small_business_score", 0) or 0))
        except (TypeError, ValueError):
            current_score = 0
        fit, small_score, reason = classify_size_fit(
            company=row.get("firma", ""),
            job_count=job_count,
            locations=locations,
            segment=segment,
            employee_hint=row.get("employee_hint", ""),
            current_score=current_score,
        )
        if not clean_text(row.get("lead_segment", "")):
            frame.at[index, "lead_segment"] = segment
        if not clean_text(row.get("size_fit", "")) or clean_text(row.get("size_fit", "")) == "offen":
            frame.at[index, "size_fit"] = fit
        if not clean_text(row.get("small_business_score", "")):
            frame.at[index, "small_business_score"] = str(small_score)
        if not clean_text(row.get("size_reason", "")):
            frame.at[index, "size_reason"] = reason
    return frame


def crm_match(company: str, exclusions: set[str]) -> bool:
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


def apply_crm_status(frame: pd.DataFrame, exclusions: set[str]) -> pd.DataFrame:
    frame = migrate_frame(frame)
    frame["crm_status"] = frame["firma"].map(
        lambda company: "Bereits in Salesforce" if crm_match(company, exclusions) else "Neu"
    )
    return frame


def facts_hash(company: str, jobs: list[dict], benefits: list[str], research: dict[str, Any]) -> str:
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


def score_lead(
    company: str,
    jobs: list[dict],
    research: dict[str, Any],
    benefits: list[str],
    previous_times_seen: int = 0,
    base_score_override: int | None = None,
) -> tuple[str, int, str]:
    base_scores = [int(float(job.get("lead_score", 0) or 0)) for job in jobs]
    score = int(base_score_override) if base_score_override is not None else max(base_scores or [20])
    reasons: list[str] = []
    penalties: list[str] = []

    scanner_reasons = unique([job.get("lead_reasons", "") for job in jobs if job.get("lead_reasons")])
    if scanner_reasons:
        reasons.extend(scanner_reasons[:2])

    titles = unique([job.get("title", "") for job in jobs if job.get("title")])
    families = [job_family(title) for title in titles]
    family_counts: dict[str, int] = {}
    for family in families:
        family_counts[family] = family_counts.get(family, 0) + 1
    dominant_family = max(family_counts, key=family_counts.get) if family_counts else "Sonstige"
    dominant_share = family_counts.get(dominant_family, 0) / max(1, len(families))

    segment = clean_text(next((job.get("lead_segment", "") for job in jobs if job.get("lead_segment")), ""))
    segment = segment or infer_lead_segment(" ".join([company] + titles))
    size_fit = clean_text(next((job.get("size_fit", "") for job in jobs if job.get("size_fit")), ""))
    small_scores = [int(float(job.get("small_business_score", 0) or 0)) for job in jobs]
    small_score = max(small_scores or [50])

    if len(jobs) <= 3:
        score += 12
        reasons.append(f"kleiner Bedarf mit {len(jobs)} Stelle" + ("n" if len(jobs) != 1 else ""))
    elif len(jobs) <= 5:
        score += 5
    elif len(jobs) > 8:
        score -= 45
        penalties.append("zu viele Ausschreibungen")

    if len(titles) == 1:
        score += 6
        reasons.append("klares Suchprofil")
    elif len(titles) >= 2 and dominant_share >= 0.65:
        score += 5
        reasons.append(f"klarer Schwerpunkt: {dominant_family}")
    elif len(titles) > 5:
        score -= 20
        penalties.append("zu viele verschiedene Rollen")

    if size_fit == "Klein":
        score += 12
        reasons.append("kleiner Direktkunde")
    elif size_fit == "Mittel":
        score += 3
    elif size_fit == "Groß oder unpassend":
        score -= 60
        penalties.append("Großunternehmen oder Kette")

    score += round((small_score - 50) * 0.25)

    if research.get("person"):
        score += 9
        reasons.append("Ansprechpartner gefunden")
    if research.get("email"):
        score += 8
        reasons.append("E Mail gefunden")
    if research.get("phone"):
        score += 7
        reasons.append("Telefon gefunden")
    if research.get("website"):
        score += 3
    if len(benefits) >= 4:
        score += 7
        reasons.append("starke Benefits")
    elif len(benefits) >= 2:
        score += 4
    if previous_times_seen >= 2:
        score += min(7, previous_times_seen + 2)
        reasons.append("wiederkehrender Personalbedarf")

    employee_hint = clean_text(research.get("employee_hint", ""))
    location_hint = clean_text(research.get("location_hint", ""))
    fit_after_research, refined_small_score, refined_reason = classify_size_fit(
        company=company,
        job_count=len(jobs),
        locations=max(1, _hint_number(location_hint) or 1),
        segment=segment,
        employee_hint=employee_hint,
        current_score=small_score,
    )
    if fit_after_research == "Groß oder unpassend":
        score -= 55
        penalties.append("Recherche zeigt zu große Struktur")
    elif fit_after_research == "Klein" and size_fit != "Klein":
        score += 8
        reasons.append("Recherche bestätigt KMU Fit")

    classification = likely_large_or_agency(company)
    if classification:
        score -= 70
        penalties.append(classification)

    score = max(0, min(int(score), 100))
    status = "HOT" if score >= 75 else "WARM" if score >= 55 else "COLD"
    explanation = reasons[:6] + [f"Abzug: {item}" for item in penalties[:3]]
    return status, score, ", ".join(explanation)


def _group_jobs(parsed_jobs: list[dict], exclusions: set[str]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for job in parsed_jobs:
        company = clean_text(job.get("company", ""))
        key = normalize_company(company)
        if not key or crm_match(company, exclusions):
            continue
        groups[key].append(job)
    return groups


def build_discovery_leads(
    *,
    parsed_jobs: list[dict],
    exclusions: set[str],
    existing: pd.DataFrame,
    scan_id: str,
    focus: str = "Alle kleinen Direktkunden",
) -> tuple[pd.DataFrame, list[str]]:
    groups = _group_jobs(parsed_jobs, exclusions)
    existing = migrate_frame(existing)
    existing_map = {row["lead_id"]: row.to_dict() for _, row in existing.iterrows()}
    rows: list[dict[str, Any]] = []
    skipped = 0

    for jobs in groups.values():
        company = clean_text(jobs[0].get("company", ""))
        if likely_large_or_agency(company):
            skipped += 1
            continue
        lead_segment = clean_text(next((job.get("lead_segment", "") for job in jobs if job.get("lead_segment")), ""))
        lead_segment = lead_segment or infer_lead_segment(" ".join([company] + [job.get("title", "") for job in jobs]))
        size_fit = clean_text(next((job.get("size_fit", "") for job in jobs if job.get("size_fit")), "")) or "Mittel"
        small_business_score = max([int(float(job.get("small_business_score", 0) or 0)) for job in jobs] or [50])
        size_reason = clean_text(next((job.get("size_reason", "") for job in jobs if job.get("size_reason")), ""))
        broad_campaign = focus in {"Breite Massenkampagne", "Alle Direktkunden", "Alle kleinen Direktkunden"}
        max_jobs = 25 if broad_campaign else 8
        if size_fit == "Groß oder unpassend" or len(jobs) > max_jobs:
            skipped += 1
            continue
        lid = lead_id(company)
        old = existing_map.get(lid, {})
        direct_research = {
            "email": next((clean_text(job.get("email", "")) for job in jobs if job.get("email")), ""),
            "phone": next((clean_text(job.get("phone", "")) for job in jobs if job.get("phone")), ""),
            "person": next((clean_text(job.get("contact", "")) for job in jobs if job.get("contact")), ""),
            "role": "",
            "website": "",
            "location_hint": "",
        }
        benefits = unique(detect_benefits(" ".join(clean_text(job.get("description", "")) for job in jobs)))
        previous_times = int(float(old.get("times_seen", 0) or 0)) if old else 0
        hot_status, score, reason = score_lead(
            company,
            jobs,
            direct_research,
            benefits,
            previous_times_seen=previous_times,
        )

        family_summary: dict[str, int] = {}
        for job in jobs:
            family = job_family(job.get("title", ""))
            family_summary[family] = family_summary.get(family, 0) + 1
        grouped_jobs = ", ".join(
            f"{amount}× {family}"
            for family, amount in sorted(family_summary.items(), key=lambda item: item[1], reverse=True)[:4]
        )
        titles = unique([job.get("title", "") for job in jobs])

        row = empty_row()
        row.update({
            "lead_id": lid,
            "firma": company,
            "hot_status": hot_status,
            "lead_score": str(score),
            "discovery_score": str(score),
            "lead_segment": lead_segment,
            "size_fit": size_fit,
            "small_business_score": str(small_business_score),
            "size_reason": size_reason,
            "warum_hot": reason,
            "offene_stellen": grouped_jobs or " | ".join(titles[:6]),
            "job_titles": " | ".join(titles[:12]),
            "job_context": "\n\n".join(
                f"{clean_text(job.get('title', ''))}: {clean_text(job.get('description', ''))[:2200]}"
                for job in jobs[:8]
                if clean_text(job.get("description", ""))
            )[:12000],
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
            "ansprechpartner": direct_research["person"],
            "email": direct_research["email"],
            "email_quality": classify_email_quality(direct_research["email"])[0],
            "telefon": direct_research["phone"],
            "stellenlink": next((clean_text(job.get("job_link", "")) for job in jobs if job.get("job_link")), ""),
            "pipeline_stage": "Gefunden",
            "research_status": "offen",
            "research_notes": "Noch nicht recherchiert. Der Suchlauf wurde bereits gespeichert.",
            "research_text": "",
            "ai_status": "offen",
            "quality_score": "0",
            "quality_status": "Nicht freigeben",
            "quality_notes": "Recherche und individuelle Texte fehlen",
            "content_hash": facts_hash(company, jobs, benefits, direct_research),
            "crm_status": "Neu / nicht abgeglichen",
            "status": old.get("status", "Neu") if old else "Neu",
            "wiedervorlage": old.get("wiedervorlage", "") if old else (date.today() + timedelta(days=1)).isoformat(),
            "notiz": old.get("notiz", "") if old else "",
        })
        rows.append(row)

    diagnostics = [
        f"Firmen aus Stellen gruppiert: {len(groups)}",
        f"Direkt als kleiner Lead vorbereitet: {len(rows)} ({focus})",
        f"Vermittler, Ketten oder zu große Unternehmen zusätzlich übersprungen: {skipped}",
        "Kontaktdaten und Texte werden bewusst erst in Schritt 2 und 3 erzeugt.",
    ]
    return migrate_frame(pd.DataFrame(rows)), diagnostics


def upsert_leads(
    existing: pd.DataFrame,
    fresh: pd.DataFrame,
    scan_id: str,
) -> tuple[pd.DataFrame, int, int, set[str]]:
    existing = migrate_frame(existing)
    fresh = migrate_frame(fresh)
    existing_map = {row["lead_id"]: row.to_dict() for _, row in existing.iterrows()}
    inserted = updated = 0
    changed_ids: set[str] = set()

    for _, fresh_row in fresh.iterrows():
        item = fresh_row.to_dict()
        lid = item["lead_id"]
        old = existing_map.get(lid)
        if old:
            for column in MANUAL_COLUMNS:
                if old.get(column, ""):
                    item[column] = old[column]
            for column in RESEARCH_COLUMNS:
                if not item.get(column, "") and old.get(column, ""):
                    item[column] = old[column]
            for column in TEXT_COLUMNS:
                if old.get("text_locked") == "ja" or (not item.get(column, "") and old.get(column, "")):
                    item[column] = old.get(column, item.get(column, ""))
            if old.get("pipeline_stage") in {"Recherchiert", "Texte erstellt", "Text Fallback"}:
                item["pipeline_stage"] = old.get("pipeline_stage", item.get("pipeline_stage", ""))
            item["last_error"] = old.get("last_error", "") if not item.get("last_error") else item["last_error"]
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
        changed_ids.add(lid)

    merged = migrate_frame(pd.DataFrame(existing_map.values()))
    merged["lead_score_num"] = pd.to_numeric(merged["lead_score"], errors="coerce").fillna(0)
    merged["small_score_num"] = pd.to_numeric(merged["small_business_score"], errors="coerce").fillna(0)
    merged = merged.sort_values(
        ["small_score_num", "lead_score_num", "firma"],
        ascending=[False, False, True],
    ).drop(columns=["small_score_num", "lead_score_num"])
    return migrate_frame(merged), inserted, updated, changed_ids


def _row_jobs(row: dict[str, Any]) -> list[dict]:
    titles = split_pipe(row.get("job_titles", "")) or split_pipe(row.get("offene_stellen", ""))
    cities = split_pipe(row.get("orte", ""))
    job_context = clean_text(row.get("job_context", ""))
    count = max(1, int(float(row.get("anzahl_stellen", 1) or 1)))
    if not titles:
        titles = ["offene Positionen"]
    jobs: list[dict] = []
    for idx, title in enumerate(titles[:max(count, len(titles))]):
        jobs.append({
            "title": title,
            "city": cities[idx % len(cities)] if cities else "",
            "description": job_context,
            "source": row.get("source_list", ""),
            "lead_score": row.get("discovery_score", row.get("lead_score", "20")),
            "lead_segment": row.get("lead_segment", ""),
            "size_fit": row.get("size_fit", ""),
            "size_reason": row.get("size_reason", ""),
            "small_business_score": row.get("small_business_score", "50"),
        })
    return jobs


def research_candidate_indices(frame: pd.DataFrame, limit: int) -> list[int]:
    frame = migrate_frame(frame)
    attempts = pd.to_numeric(frame["research_attempts"], errors="coerce").fillna(0)
    score = pd.to_numeric(frame["lead_score"], errors="coerce").fillna(0)
    needs = (
        (frame["website"] == "")
        | ((frame["email"] == "") & (frame["telefon"] == ""))
        | (frame["research_status"].isin(["", "offen", "nicht gefunden", "Fehler"]))
    )
    candidates = frame[
        needs
        & (attempts < 3)
        & (~frame["status"].isin(["Ausschließen", "In Salesforce übernommen"]))
        & (frame["size_fit"] != "Groß oder unpassend")
    ].copy()
    if candidates.empty:
        return []
    candidates["score_num"] = score.loc[candidates.index]
    candidates["small_num"] = pd.to_numeric(candidates["small_business_score"], errors="coerce").fillna(0)
    candidates["attempts_num"] = attempts.loc[candidates.index]
    candidates = candidates.sort_values(
        ["attempts_num", "small_num", "score_num"],
        ascending=[True, False, False],
    ).head(limit)
    return list(candidates.index)


def enrich_lead(
    row: dict[str, Any],
    *,
    serpapi_key: str,
) -> tuple[dict[str, str], list[str]]:
    item = migrate_frame(pd.DataFrame([row])).iloc[0].to_dict()
    city = split_pipe(item.get("orte", ""))[0] if split_pipe(item.get("orte", "")) else ""
    source_urls = unique([
        item.get("website", ""), item.get("stellenlink", ""),
        item.get("karriereseite", ""), item.get("kontaktseite", ""),
    ])
    attempts = int(float(item.get("research_attempts", 0) or 0)) + 1
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    try:
        research = research_company(
            company=item["firma"],
            city=city,
            source_urls=source_urls,
            serpapi_key=serpapi_key,
            max_pages=12,
        )
    except Exception as exc:
        item["research_attempts"] = str(attempts)
        item["research_updated_at"] = now
        item["research_status"] = "Fehler"
        item["research_notes"] = clean_text(exc)
        item["last_error"] = f"Recherche: {clean_text(exc)}"
        item["pipeline_stage"] = "Recherche versucht"
        return item, [f"{item['firma']}: Recherchefehler {clean_text(exc)}"]

    mapping = {
        "website": "website",
        "contact_page": "kontaktseite",
        "imprint_page": "impressum",
        "career_page": "karriereseite",
        "email": "email",
        "phone": "telefon",
        "person": "ansprechpartner",
        "role": "rolle",
        "employee_hint": "employee_hint",
        "location_hint": "location_hint",
    }
    for source_key, column in mapping.items():
        value = clean_text(research.get(source_key, ""))
        if value:
            item[column] = value

    item["research_status"] = clean_text(research.get("status", "")) or "abgeschlossen"
    item["research_notes"] = clean_text(research.get("notes", ""))
    item["research_text"] = clean_text(research.get("text", ""))[:12000]
    item["email_quality"] = classify_email_quality(item.get("email", ""))[0]
    item["research_attempts"] = str(attempts)
    item["research_updated_at"] = now
    item["pipeline_stage"] = "Recherchiert" if item.get("website") or item.get("email") or item.get("telefon") else "Recherche versucht"
    item["last_error"] = "" if item["pipeline_stage"] == "Recherchiert" else item["research_notes"]

    jobs = _row_jobs(item)
    benefits = unique(split_pipe(item.get("benefits", "")) + detect_benefits(research.get("text", "")))
    item["benefits"] = " | ".join(benefits)
    research_for_score = {
        "person": item.get("ansprechpartner", ""),
        "email": item.get("email", ""),
        "phone": item.get("telefon", ""),
        "website": item.get("website", ""),
        "location_hint": item.get("location_hint", ""),
        "employee_hint": item.get("employee_hint", ""),
    }
    segment = item.get("lead_segment", "") or infer_lead_segment(
        " ".join([item.get("firma", ""), item.get("job_titles", ""), research.get("text", "")])
    )
    location_count = max(1, _hint_number(item.get("location_hint", "")) or len(split_pipe(item.get("orte", ""))) or 1)
    fit, small_score, size_reason = classify_size_fit(
        company=item.get("firma", ""),
        job_count=max(1, int(float(item.get("anzahl_stellen", 1) or 1))),
        locations=location_count,
        segment=segment,
        employee_hint=item.get("employee_hint", ""),
        current_score=int(float(item.get("small_business_score", 0) or 0)),
    )
    item["lead_segment"] = segment
    item["size_fit"] = fit
    item["small_business_score"] = str(small_score)
    item["size_reason"] = size_reason
    base = int(float(item.get("discovery_score", item.get("lead_score", 20)) or 20))
    status, score, reason = score_lead(
        item["firma"], jobs, research_for_score, benefits,
        previous_times_seen=int(float(item.get("times_seen", 0) or 0)),
        base_score_override=base,
    )
    item["hot_status"] = status
    item["lead_score"] = str(score)
    item["warum_hot"] = reason
    item["content_hash"] = facts_hash(item["firma"], jobs, benefits, research)
    quality_score, quality_status, quality_notes = evaluate_lead_quality(item)
    item["quality_score"] = str(quality_score)
    item["quality_status"] = quality_status
    item["quality_notes"] = quality_notes

    diagnostics = [
        f"{item['firma']}: Website {'gefunden' if item.get('website') else 'nicht gefunden'}",
        f"{item['firma']}: Kontakt {'gefunden' if item.get('email') or item.get('telefon') else 'nicht gefunden'}",
    ]
    return item, diagnostics


def ai_candidate_indices(frame: pd.DataFrame, limit: int, force: bool = False) -> list[int]:
    frame = migrate_frame(frame)
    attempts = pd.to_numeric(frame["ai_attempts"], errors="coerce").fillna(0)
    score = pd.to_numeric(frame["lead_score"], errors="coerce").fillna(0)
    if force:
        needs = frame["text_locked"] != "ja"
    else:
        needs = (~frame["ai_status"].str.startswith("KI erstellt", na=False)) & (frame["text_locked"] != "ja")
    candidates = frame[
        needs
        & (attempts < 3)
        & (~frame["status"].isin(["Ausschließen", "In Salesforce übernommen"]))
        & (frame["size_fit"] != "Groß oder unpassend")
    ].copy()
    if candidates.empty:
        return []
    candidates["contact_num"] = ((candidates["email"] != "") | (candidates["telefon"] != "")).astype(int)
    candidates["score_num"] = score.loc[candidates.index]
    candidates["small_num"] = pd.to_numeric(candidates["small_business_score"], errors="coerce").fillna(0)
    candidates["attempts_num"] = attempts.loc[candidates.index]
    candidates = candidates.sort_values(
        ["contact_num", "small_num", "attempts_num", "score_num"],
        ascending=[False, False, True, False],
    ).head(limit)
    return list(candidates.index)


def generate_lead_assets(
    row: dict[str, Any],
    *,
    api_key: str,
    model: str,
) -> tuple[dict[str, str], list[str]]:
    item = migrate_frame(pd.DataFrame([row])).iloc[0].to_dict()
    if item.get("text_locked") == "ja":
        return item, [f"{item['firma']}: Texte sind manuell gesperrt."]

    attempts = int(float(item.get("ai_attempts", 0) or 0)) + 1
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    jobs = _row_jobs(item)
    research = {
        "website": item.get("website", ""),
        "contact_page": item.get("kontaktseite", ""),
        "imprint_page": item.get("impressum", ""),
        "career_page": item.get("karriereseite", ""),
        "email": item.get("email", ""),
        "phone": item.get("telefon", ""),
        "person": item.get("ansprechpartner", ""),
        "role": item.get("rolle", ""),
        "text": item.get("research_text", ""),
        "status": item.get("research_status", ""),
        "notes": item.get("research_notes", ""),
        "employee_hint": item.get("employee_hint", ""),
        "location_hint": item.get("location_hint", ""),
    }
    benefits = split_pipe(item.get("benefits", ""))
    try:
        texts = create_sales_assets(
            company=item["firma"],
            jobs=jobs,
            benefits=benefits,
            person=item.get("ansprechpartner", ""),
            research=research,
            api_key=api_key,
            model=model,
        )
    except Exception as exc:
        item["ai_attempts"] = str(attempts)
        item["ai_updated_at"] = now
        item["ai_status"] = "Fehler"
        item["last_error"] = f"KI: {clean_text(exc)}"
        item["pipeline_stage"] = "Text Fallback"
        return item, [f"{item['firma']}: KI Fehler {clean_text(exc)}"]

    for key in ASSET_KEYS:
        value = clean_text(texts.get(key, "")) if key == "erstmail_betreff" else str(texts.get(key, "")).strip()
        if value:
            item[key] = value
    item["personalization_evidence"] = clean_text(texts.get("personalization_evidence", ""))
    item["mail_variant"] = clean_text(texts.get("mail_variant", "")) or "Exklusive Einladung V1"
    item["email_quality"] = classify_email_quality(item.get("email", ""))[0]
    item["ai_status"] = clean_text(texts.get("ai_status", "")) or "Fallback genutzt"
    item["ai_attempts"] = str(attempts)
    item["ai_updated_at"] = now
    item["pipeline_stage"] = "Texte erstellt" if item["ai_status"].startswith("KI erstellt") else "Text Fallback"
    item["last_error"] = "" if item["pipeline_stage"] == "Texte erstellt" else item["ai_status"]
    item["content_hash"] = facts_hash(item["firma"], jobs, benefits, research)
    quality_score, quality_status, quality_notes = evaluate_lead_quality(item)
    item["quality_score"] = str(quality_score)
    item["quality_status"] = quality_status
    item["quality_notes"] = quality_notes
    return item, [f"{item['firma']}: {item['ai_status']}, Qualität {quality_score} Punkte, {quality_status}"]
