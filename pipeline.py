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
    "discovery_score",
    "warum_hot",
    "offene_stellen",
    "job_titles",
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
    "pipeline_stage",
    "research_status",
    "research_notes",
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
    "research_attempts", "research_updated_at", "employee_hint", "location_hint",
]
TEXT_COLUMNS = ASSET_KEYS + ["ai_status", "ai_attempts", "ai_updated_at", "content_hash"]


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


def empty_row() -> dict[str, str]:
    return {column: "" for column in COLUMNS}


def migrate_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    frame = frame.copy() if frame is not None else pd.DataFrame()
    for column in COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    return frame.reindex(columns=COLUMNS).fillna("").astype(str)


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
    if str(research.get("location_hint", "")).isdigit() and int(research["location_hint"]) >= 2:
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
            "warum_hot": reason,
            "offene_stellen": grouped_jobs or " | ".join(titles[:6]),
            "job_titles": " | ".join(titles[:12]),
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
            "telefon": direct_research["phone"],
            "stellenlink": next((clean_text(job.get("job_link", "")) for job in jobs if job.get("job_link")), ""),
            "pipeline_stage": "Gefunden",
            "research_status": "offen",
            "research_notes": "Noch nicht recherchiert. Der Suchlauf wurde bereits gespeichert.",
            "ai_status": "offen",
            "content_hash": facts_hash(company, jobs, benefits, direct_research),
            "crm_status": "Neu / nicht abgeglichen",
            "status": old.get("status", "Neu") if old else "Neu",
            "wiedervorlage": old.get("wiedervorlage", "") if old else (date.today() + timedelta(days=1)).isoformat(),
            "notiz": old.get("notiz", "") if old else "",
        })
        rows.append(row)

    diagnostics = [
        f"Firmen aus Stellen gruppiert: {len(groups)}",
        f"Direkt als Lead vorbereitet: {len(rows)}",
        f"Vermittler oder Großunternehmen zusätzlich übersprungen: {skipped}",
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
    merged = merged.sort_values(["lead_score_num", "firma"], ascending=[False, True]).drop(columns=["lead_score_num"])
    return migrate_frame(merged), inserted, updated, changed_ids


def _row_jobs(row: dict[str, Any]) -> list[dict]:
    titles = split_pipe(row.get("job_titles", "")) or split_pipe(row.get("offene_stellen", ""))
    cities = split_pipe(row.get("orte", ""))
    count = max(1, int(float(row.get("anzahl_stellen", 1) or 1)))
    if not titles:
        titles = ["offene Positionen"]
    jobs: list[dict] = []
    for idx, title in enumerate(titles[:max(count, len(titles))]):
        jobs.append({
            "title": title,
            "city": cities[idx % len(cities)] if cities else "",
            "description": "",
            "source": row.get("source_list", ""),
            "lead_score": row.get("discovery_score", row.get("lead_score", "20")),
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
    candidates = frame[needs & (attempts < 3) & (~frame["status"].isin(["Ausschließen", "In Salesforce übernommen"]))].copy()
    if candidates.empty:
        return []
    candidates["score_num"] = score.loc[candidates.index]
    candidates["attempts_num"] = attempts.loc[candidates.index]
    candidates = candidates.sort_values(["attempts_num", "score_num"], ascending=[True, False]).head(limit)
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
    }
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
    candidates = frame[needs & (attempts < 3) & (~frame["status"].isin(["Ausschließen", "In Salesforce übernommen"]))].copy()
    if candidates.empty:
        return []
    candidates["contact_num"] = ((candidates["email"] != "") | (candidates["telefon"] != "")).astype(int)
    candidates["score_num"] = score.loc[candidates.index]
    candidates["attempts_num"] = attempts.loc[candidates.index]
    candidates = candidates.sort_values(["contact_num", "attempts_num", "score_num"], ascending=[False, True, False]).head(limit)
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
        "text": "",
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
    item["ai_status"] = clean_text(texts.get("ai_status", "")) or "Fallback genutzt"
    item["ai_attempts"] = str(attempts)
    item["ai_updated_at"] = now
    item["pipeline_stage"] = "Texte erstellt" if item["ai_status"].startswith("KI erstellt") else "Text Fallback"
    item["last_error"] = "" if item["pipeline_stage"] == "Texte erstellt" else item["ai_status"]
    item["content_hash"] = facts_hash(item["firma"], jobs, benefits, research)
    return item, [f"{item['firma']}: {item['ai_status']}"]
