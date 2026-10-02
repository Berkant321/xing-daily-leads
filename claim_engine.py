from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET

import pandas as pd
import requests
from bs4 import BeautifulSoup

from research import (
    clean_text as research_clean_text,
    normalize as research_normalize,
    normalize_company as research_normalize_company,
    research_company,
    root_domain,
)


CLAIM_ENGINE_VERSION = "12.0.0"

OLD_LEAD_COLUMNS = [
    "lead_id", "firma", "hot_status", "lead_score", "discovery_score", "lead_segment",
    "size_fit", "small_business_score", "size_reason", "warum_hot", "offene_stellen",
    "job_titles", "job_context", "anzahl_stellen", "orte", "veroeffentlicht_am",
    "first_seen", "first_seen_scan", "zuletzt_gefunden", "scan_id", "times_seen",
    "source_list", "discovery_kind", "need_signal", "diamond_score", "diamond_reason",
    "kampagne", "benefits", "ansprechpartner", "rolle", "email", "email_quality",
    "telefon", "website", "kontaktseite", "impressum", "karriereseite", "stellenlink",
    "pipeline_stage", "research_status", "research_notes", "research_text",
    "research_attempts", "research_updated_at", "employee_hint", "location_hint",
    "content_hash", "ai_status", "ai_attempts", "ai_updated_at", "last_error",
    "text_locked", "crm_status", "erstmail_betreff", "erstmail",
    "personalization_evidence", "mail_variant", "quality_score", "quality_status",
    "quality_notes", "call_opener", "discovery_fragen", "challenger_reframe",
    "follow_up_1", "follow_up_2", "status", "wiedervorlage", "versendet_am",
    "follow_up_1_am", "follow_up_2_am", "antwort_status", "antwort_am",
    "antwort_notiz", "termin_am", "absagegrund", "notiz",
]

CLAIM_COLUMNS = [
    "canonical_company", "canonical_domain", "company_confidence", "employer_type",
    "claim_status", "claim_score", "claim_reason", "need_score", "need_confidence",
    "verified_open_jobs", "verified_job_titles", "job_source_count", "job_evidence_count",
    "job_evidence", "career_signal", "ats_detected", "pages_crawled", "research_score",
    "research_depth", "research_sources", "last_verified_at",
]

LEAD_COLUMNS = OLD_LEAD_COLUMNS + [c for c in CLAIM_COLUMNS if c not in OLD_LEAD_COLUMNS]

OLD_JOB_COLUMNS = [
    "job_id", "lead_id", "firma", "position", "ort", "veroeffentlicht_am", "quelle",
    "suchbegriff", "stellenlink", "referenz", "lead_segment", "size_fit",
    "small_business_score", "lead_score", "email", "telefon", "ansprechpartner",
    "beschreibung", "first_seen", "last_seen", "times_seen", "scan_id", "kampagne",
    "status", "notiz",
]

JOB_EXTRA_COLUMNS = [
    "canonical_domain", "canonical_job_key", "source_portal", "source_job_id", "source_url",
    "evidence_type", "evidence_confidence", "verified_on_company_site", "official_job_url",
    "verified_at",
]
JOB_COLUMNS = OLD_JOB_COLUMNS + [c for c in JOB_EXTRA_COLUMNS if c not in OLD_JOB_COLUMNS]

EVIDENCE_COLUMNS = [
    "evidence_id", "lead_id", "job_id", "firma", "position", "ort", "quelle",
    "quelle_url", "gefunden_am", "verifiziert_am", "evidence_type", "confidence",
    "active", "canonical_domain", "notiz",
]

SCAN_LOG_COLUMNS = [
    "timestamp", "scan_id", "stage", "status", "processed_terms", "processed_items",
    "found_jobs", "new_leads", "updated_leads", "message",
]

STAFFING_TOKENS = (
    "zeitarbeit", "personalvermittlung", "personaldienstleistung", "personaldienstleister",
    "arbeitnehmerueberlassung", "arbeitnehmerüberlassung", "staffing", "recruiting agency",
    "personalservice", "randstad", "adecco", "manpower", "persona service", "tempton",
    "office people", "piening", "expertum", "actief",
)

CRM_GENERIC_TOKENS = {
    "gruppe", "group", "holding", "deutschland", "germany", "international",
    "services", "service", "solutions", "solution", "company", "unternehmen",
}

def company_alias_keys(company: str) -> set[str]:
    normalized = normalize_company(company)
    if not normalized:
        return set()
    tokens = normalized.split()
    keys = {normalized}
    compact = normalized.replace(" ", "")
    if len(compact) >= 8:
        keys.add(compact)
    core = [token for token in tokens if token not in CRM_GENERIC_TOKENS]
    if len(core) >= 2 and sum(len(token) for token in core) >= 8:
        keys.add(" ".join(core))
        keys.add("".join(core))
    if len(core) >= 3:
        for start in range(len(core) - 1):
            pair = core[start:start + 2]
            if sum(len(token) for token in pair) >= 12:
                keys.add(" ".join(pair))
                keys.add("".join(pair))
    return {key for key in keys if key}

PUBLIC_TOKENS = (
    "stadt ", "landkreis", "ministerium", "bundesamt", "bundeswehr", "universitaet",
    "universität", "hochschule", "kommune", "behoerde", "behörde", "landratsamt",
)
ATS_HOSTS = {
    "jobs.personio.de": "Personio",
    "jobs.personio.com": "Personio",
    "greenhouse.io": "Greenhouse",
    "lever.co": "Lever",
    "smartrecruiters.com": "SmartRecruiters",
    "workable.com": "Workable",
    "teamtailor.com": "Teamtailor",
    "softgarden.io": "Softgarden",
    "onlyfy.io": "Onlyfy",
    "join.com": "JOIN",
}
CAREER_TOKENS = (
    "karriere", "career", "jobs", "job", "stellenangebote", "stellen", "vacancies",
    "vacancy", "bewerbung", "bewerben",
)


def clean_text(value: Any) -> str:
    return research_clean_text(value)


def normalize(value: Any) -> str:
    return research_normalize(value)


def normalize_company(value: Any) -> str:
    return research_normalize_company(clean_text(value))


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or str(value).strip() == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def unique(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = clean_text(value)
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def split_pipe(value: Any) -> list[str]:
    return unique(str(value or "").split("|"))


def normalize_job_title(title: str) -> str:
    value = clean_text(title)
    noise = (
        r"\(\s*m\s*/\s*w\s*/\s*d\s*\)", r"\(\s*w\s*/\s*m\s*/\s*d\s*\)",
        r"\(\s*m\s*/\s*f\s*/\s*d\s*\)", r"\(\s*gn\s*\)",
        r"\(\s*all genders\s*\)", r"\[\s*m\s*/\s*w\s*/\s*d\s*\]",
    )
    for pattern in noise:
        value = re.sub(pattern, " ", value, flags=re.I)
    value = re.sub(r"\bm\s*/\s*w\s*/\s*d\b|\bw\s*/\s*m\s*/\s*d\b|\bm\s*/\s*f\s*/\s*d\b", " ", value, flags=re.I)
    value = re.sub(r"\b(mwd|wmd|mfd)\b", " ", value, flags=re.I)
    return re.sub(r"\s+", " ", normalize(value)).strip()


def canonical_company_key(company: str, city: str = "", domain: str = "") -> str:
    domain = root_domain(domain) if domain else ""
    if domain:
        return f"domain:{domain.lower()}"
    return f"company:{normalize_company(company)}|city:{normalize(city)}"


def lead_id(company: str, city: str = "", domain: str = "") -> str:
    identity = canonical_company_key(company, city, domain)
    return hashlib.sha1(identity.encode("utf-8")).hexdigest()[:16]


def canonical_job_key(company: str, title: str, city: str = "", domain: str = "") -> str:
    identity = "|".join([
        canonical_company_key(company, city, domain),
        normalize_job_title(title),
        normalize(city),
    ])
    return hashlib.sha1(identity.encode("utf-8")).hexdigest()[:18]


def job_id(job: dict[str, Any]) -> str:
    reference = clean_text(job.get("reference", "") or job.get("source_job_id", ""))
    source = clean_text(job.get("source", ""))
    if reference:
        raw = f"{source}|{reference}"
    else:
        raw = canonical_job_key(
            clean_text(job.get("company", "") or job.get("firma", "")),
            clean_text(job.get("title", "") or job.get("position", "")),
            clean_text(job.get("city", "") or job.get("ort", "")),
        )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:18]


def migrate_leads(frame: pd.DataFrame | None) -> pd.DataFrame:
    result = frame.copy() if frame is not None else pd.DataFrame()
    for column in LEAD_COLUMNS:
        if column not in result.columns:
            result[column] = ""
    result = result.fillna("")
    return result.reindex(columns=LEAD_COLUMNS)


def migrate_jobs(frame: pd.DataFrame | None) -> pd.DataFrame:
    result = frame.copy() if frame is not None else pd.DataFrame()
    for column in JOB_COLUMNS:
        if column not in result.columns:
            result[column] = ""
    result = result.fillna("")
    return result.reindex(columns=JOB_COLUMNS)


def migrate_evidence(frame: pd.DataFrame | None) -> pd.DataFrame:
    result = frame.copy() if frame is not None else pd.DataFrame()
    for column in EVIDENCE_COLUMNS:
        if column not in result.columns:
            result[column] = ""
    return result.fillna("").reindex(columns=EVIDENCE_COLUMNS)


def _source_portal(source: str) -> str:
    source = clean_text(source)
    if "|" in source:
        source = source.split("|", 1)[0].strip()
    return source or "Unbekannt"


def prepare_jobs(raw_jobs: list[dict[str, Any]], scan_id: str, campaign: str) -> pd.DataFrame:
    today = date.today().isoformat()
    rows: list[dict[str, Any]] = []
    for job in raw_jobs:
        company = clean_text(job.get("company", ""))
        title = clean_text(job.get("title", ""))
        if not company:
            continue
        discovery_kind = clean_text(job.get("discovery_kind", ""))
        if not title and discovery_kind != "Firmenradar":
            continue
        city = clean_text(job.get("city", ""))
        source = clean_text(job.get("source", ""))
        source_url = clean_text(job.get("job_link", "") or job.get("external_url", "") or job.get("url", ""))
        reference = clean_text(job.get("reference", ""))
        jid = job_id(job)
        ckey = canonical_job_key(company, title or "Firmenradar", city)
        row = {column: "" for column in JOB_COLUMNS}
        row.update({
            "job_id": jid,
            "lead_id": lead_id(company, city),
            "firma": company,
            "position": title or "Firmenradar",
            "ort": city,
            "veroeffentlicht_am": clean_text(job.get("published", "")),
            "quelle": source,
            "suchbegriff": clean_text(job.get("term", "")),
            "stellenlink": source_url,
            "referenz": reference,
            "lead_segment": clean_text(job.get("lead_segment", "")),
            "size_fit": clean_text(job.get("size_fit", "")),
            "small_business_score": str(job.get("small_business_score", "") or ""),
            "lead_score": str(job.get("lead_score", "") or ""),
            "email": clean_text(job.get("email", "")),
            "telefon": clean_text(job.get("phone", "")),
            "ansprechpartner": clean_text(job.get("contact", "")),
            "beschreibung": clean_text(job.get("description", ""))[:5000],
            "first_seen": today,
            "last_seen": today,
            "times_seen": "1",
            "scan_id": scan_id,
            "kampagne": campaign,
            "status": "Neu",
            "canonical_job_key": ckey,
            "source_portal": _source_portal(source),
            "source_job_id": reference,
            "source_url": source_url,
            "evidence_type": "Firmenradar" if discovery_kind == "Firmenradar" else "Jobportal",
            "evidence_confidence": "45" if discovery_kind == "Firmenradar" else "75",
            "verified_on_company_site": "",
            "verified_at": "",
        })
        rows.append(row)
    return migrate_jobs(pd.DataFrame(rows))


def merge_jobs(existing: pd.DataFrame, fresh: pd.DataFrame) -> tuple[pd.DataFrame, int, int]:
    existing = migrate_jobs(existing)
    fresh = migrate_jobs(fresh)
    records = {row["job_id"]: row.to_dict() for _, row in existing.iterrows() if clean_text(row["job_id"])}
    inserted = 0
    updated = 0
    for _, row in fresh.iterrows():
        item = row.to_dict()
        jid = clean_text(item.get("job_id", ""))
        if not jid:
            continue
        old = records.get(jid)
        if old:
            item["first_seen"] = old.get("first_seen", "") or item.get("first_seen", "")
            item["times_seen"] = str(safe_int(old.get("times_seen"), 1) + 1)
            for column in JOB_COLUMNS:
                if not clean_text(item.get(column, "")) and clean_text(old.get(column, "")):
                    item[column] = old[column]
            updated += 1
        else:
            inserted += 1
        records[jid] = item
    merged = migrate_jobs(pd.DataFrame(records.values()))
    if not merged.empty:
        merged["_last"] = pd.to_datetime(merged["last_seen"], errors="coerce")
        merged = merged.sort_values(["_last", "firma", "position"], ascending=[False, True, True]).drop(columns="_last")
    return merged, inserted, updated


def build_evidence_from_jobs(jobs: pd.DataFrame) -> pd.DataFrame:
    jobs = migrate_jobs(jobs)
    rows: list[dict[str, str]] = []
    for _, row in jobs.iterrows():
        source = clean_text(row.get("quelle", ""))
        url = clean_text(row.get("source_url", "") or row.get("stellenlink", ""))
        raw = "|".join([clean_text(row.get("job_id", "")), source, url])
        eid = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:18]
        rows.append({
            "evidence_id": eid,
            "lead_id": clean_text(row.get("lead_id", "")),
            "job_id": clean_text(row.get("job_id", "")),
            "firma": clean_text(row.get("firma", "")),
            "position": clean_text(row.get("position", "")),
            "ort": clean_text(row.get("ort", "")),
            "quelle": source,
            "quelle_url": url,
            "gefunden_am": clean_text(row.get("last_seen", "")),
            "verifiziert_am": clean_text(row.get("verified_at", "")),
            "evidence_type": clean_text(row.get("evidence_type", "")) or "Jobportal",
            "confidence": clean_text(row.get("evidence_confidence", "")) or "70",
            "active": "ja",
            "canonical_domain": clean_text(row.get("canonical_domain", "")),
            "notiz": "",
        })
    return migrate_evidence(pd.DataFrame(rows)).drop_duplicates(subset=["evidence_id"], keep="last")


def classify_employer(company: str, text: str = "") -> str:
    haystack = f" {normalize(company)} {normalize(text)} "
    if any(normalize(token) in haystack for token in STAFFING_TOKENS):
        return "Vermittler"
    if any(normalize(token) in haystack for token in PUBLIC_TOKENS):
        return "Öffentlich"
    return "Direktarbeitgeber"


def _freshness_points(values: Iterable[Any]) -> tuple[int, int | None]:
    dates: list[pd.Timestamp] = []
    for value in values:
        parsed = pd.to_datetime(value, errors="coerce", utc=True)
        if not pd.isna(parsed):
            dates.append(parsed)
    if not dates:
        return 0, None
    newest = max(dates)
    age = (pd.Timestamp.now(tz="UTC") - newest).days
    if age <= 7:
        return 15, age
    if age <= 14:
        return 12, age
    if age <= 30:
        return 8, age
    if age <= 45:
        return 3, age
    return -12, age


def calculate_need_score(row: dict[str, Any]) -> tuple[int, str]:
    score = 0
    reasons: list[str] = []
    verified = safe_int(row.get("verified_open_jobs"), 0)
    raw_jobs = safe_int(row.get("anzahl_stellen"), 0)
    sources = safe_int(row.get("job_source_count"), 0)
    if verified > 0:
        score += 45
        reasons.append(f"{verified} Stelle(n) auf Firmenquelle verifiziert")
        score += min(15, max(0, verified - 1) * 5)
    elif raw_jobs > 0:
        score += 28
        reasons.append(f"{raw_jobs} Portalvakanz(en)")
    if sources >= 2:
        score += min(15, 5 + (sources - 2) * 4)
        reasons.append(f"{sources} unabhängige Quellen")
    if clean_text(row.get("karriereseite", "")):
        score += 8
        reasons.append("Karrierebereich")
    if clean_text(row.get("ats_detected", "")):
        score += 7
        reasons.append("ATS erkannt")
    fresh_points, age = _freshness_points([row.get("veroeffentlicht_am"), row.get("zuletzt_gefunden")])
    score += fresh_points
    if age is not None:
        reasons.append(f"jüngstes Signal {age} Tage")
    if clean_text(row.get("discovery_kind", "")) == "Firmenradar" and raw_jobs == 0 and verified == 0:
        score = min(score, 35)
        reasons.append("Firmenradar ohne belegte Vakanz")
    return max(0, min(100, score)), "; ".join(reasons[:6])


def calculate_claim_score(row: dict[str, Any]) -> tuple[int, str]:
    employer = clean_text(row.get("employer_type", "")) or "Direktarbeitgeber"
    if employer in {"Vermittler", "Öffentlich"}:
        return 0, employer
    if clean_text(row.get("crm_status", "")) == "Bereits in Salesforce":
        return 0, "Bereits in Salesforce"
    score = 0
    reasons: list[str] = []
    company_conf = safe_int(row.get("company_confidence"), 0)
    need = safe_int(row.get("need_score"), 0)
    verified = safe_int(row.get("verified_open_jobs"), 0)
    sources = safe_int(row.get("job_source_count"), 0)
    if company_conf >= 90:
        score += 25
        reasons.append("Firma sicher identifiziert")
    elif company_conf >= 75:
        score += 18
        reasons.append("Firma plausibel identifiziert")
    elif company_conf >= 60:
        score += 8
    score += round(need * 0.35)
    if verified >= 1:
        score += 15
    if verified >= 2:
        score += 5
    if sources >= 2:
        score += 7
    if clean_text(row.get("size_fit", "")) == "Klein":
        score += 8
        reasons.append("KMU Fit")
    elif clean_text(row.get("size_fit", "")) == "Mittel":
        score += 4
    if clean_text(row.get("website", "")):
        score += 5
    if clean_text(row.get("karriereseite", "")):
        score += 5
    return max(0, min(100, score)), "; ".join(reasons[:6])


def determine_claim_status(row: dict[str, Any]) -> str:
    if clean_text(row.get("crm_status", "")) == "Bereits in Salesforce":
        return "EXCLUDE"
    if clean_text(row.get("employer_type", "")) in {"Vermittler", "Öffentlich"}:
        return "EXCLUDE"
    company_conf = safe_int(row.get("company_confidence"), 0)
    need = safe_int(row.get("need_score"), 0)
    claim = safe_int(row.get("claim_score"), 0)
    verified = safe_int(row.get("verified_open_jobs"), 0)
    raw_jobs = safe_int(row.get("anzahl_stellen"), 0)
    if company_conf >= 75 and claim >= 65 and (verified >= 1 or (raw_jobs >= 1 and need >= 60)):
        return "CLAIMABLE"
    if company_conf >= 55 or need >= 45:
        return "RESEARCH"
    return "REVIEW"


def _lead_group_key(row: pd.Series) -> str:
    company = clean_text(row.get("firma", ""))
    city = clean_text(row.get("ort", ""))
    normalized = normalize_company(company)
    generic_tokens = {"praxis", "zentrum", "team", "pflege", "therapie", "kanzlei", "service", "services"}
    tokens = set(normalized.split())
    # Eindeutige Firmennamen werden portal- und standortübergreifend zusammengeführt.
    # Sehr generische lokale Namen behalten den Ort als Discriminator.
    if len(tokens) <= 3 and tokens & generic_tokens:
        return canonical_company_key(company, city)
    return f"company:{normalized}"


def rebuild_leads(jobs: pd.DataFrame, old_leads: pd.DataFrame | None = None, campaign: str = "") -> pd.DataFrame:
    jobs = migrate_jobs(jobs)
    old = migrate_leads(old_leads)
    old_by_name: dict[str, dict[str, Any]] = {}
    for _, row in old.iterrows():
        company = normalize_company(row.get("firma", ""))
        if company:
            old_by_name[company] = row.to_dict()
    rows: list[dict[str, Any]] = []
    vacancy_jobs = jobs[jobs["position"].astype(str).str.lower().ne("firmenradar")].copy()
    if jobs.empty:
        return old
    jobs = jobs.copy()
    jobs["_group"] = jobs.apply(_lead_group_key, axis=1)
    for _, group in jobs.groupby("_group", sort=False):
        company = clean_text(group.iloc[0].get("firma", ""))
        company_norm = normalize_company(company)
        previous = old_by_name.get(company_norm, {})
        real_jobs = group[group["position"].astype(str).str.lower().ne("firmenradar")]
        canonical_job_count = int(real_jobs["canonical_job_key"].replace("", pd.NA).nunique(dropna=True)) if not real_jobs.empty else 0
        if canonical_job_count == 0 and not real_jobs.empty:
            canonical_job_count = len(real_jobs)
        titles = unique(real_jobs["position"].tolist())
        cities = unique(group["ort"].tolist())
        sources = unique(group["source_portal"].tolist() + group["quelle"].tolist())
        source_count = len(unique(group["source_portal"].tolist()))
        links = unique(group["stellenlink"].tolist())
        published = [x for x in group["veroeffentlicht_am"].tolist() if clean_text(x)]
        best_small = max([safe_int(x, 0) for x in group["small_business_score"].tolist()] or [0])
        best_lead = max([safe_int(x, 0) for x in group["lead_score"].tolist()] or [0])
        segment = next((clean_text(x) for x in group["lead_segment"].tolist() if clean_text(x)), clean_text(previous.get("lead_segment", "")))
        size_fit = next((clean_text(x) for x in group["size_fit"].tolist() if clean_text(x)), clean_text(previous.get("size_fit", "")))
        city = cities[0] if cities else ""
        lid = clean_text(previous.get("lead_id", "")) or lead_id(company, city)
        row = {column: "" for column in LEAD_COLUMNS}
        for column in LEAD_COLUMNS:
            if clean_text(previous.get(column, "")):
                row[column] = previous[column]
        row.update({
            "lead_id": lid,
            "firma": company,
            "lead_score": str(best_lead),
            "discovery_score": str(best_lead),
            "lead_segment": segment,
            "size_fit": size_fit,
            "small_business_score": str(best_small),
            "offene_stellen": " | ".join(titles[:12]),
            "job_titles": " | ".join(titles[:20]),
            "job_context": "\n\n".join(unique(real_jobs["beschreibung"].tolist()))[:15000],
            "anzahl_stellen": str(canonical_job_count),
            "orte": " | ".join(cities),
            "veroeffentlicht_am": max(published or [clean_text(previous.get("veroeffentlicht_am", ""))]),
            "zuletzt_gefunden": date.today().isoformat(),
            "scan_id": clean_text(group.iloc[0].get("scan_id", "")),
            "source_list": " | ".join(sources),
            "kampagne": campaign or clean_text(group.iloc[0].get("kampagne", "")) or clean_text(previous.get("kampagne", "")),
            "stellenlink": links[0] if links else clean_text(previous.get("stellenlink", "")),
            "pipeline_stage": clean_text(previous.get("pipeline_stage", "")) or "Gefunden",
            "research_status": clean_text(previous.get("research_status", "")) or "offen",
            "first_seen": clean_text(previous.get("first_seen", "")) or date.today().isoformat(),
            "first_seen_scan": clean_text(previous.get("first_seen_scan", "")) or clean_text(group.iloc[0].get("scan_id", "")),
            "times_seen": str(max([safe_int(x, 1) for x in group["times_seen"].tolist()] or [1])),
            "job_source_count": str(source_count),
            "job_evidence_count": str(len(group)),
            "job_evidence": " | ".join(unique([f"{r['source_portal']}: {r['position']}" for _, r in group.iterrows()])[:20]),
            "employer_type": clean_text(previous.get("employer_type", "")) or classify_employer(company, " ".join(group["beschreibung"].tolist())),
            "crm_status": clean_text(previous.get("crm_status", "")) or "Neu",
            "status": clean_text(previous.get("status", "")) or "Neu",
        })
        need_score, need_reason = calculate_need_score(row)
        row["need_score"] = str(need_score)
        row["need_confidence"] = need_reason
        claim_score, claim_reason = calculate_claim_score(row)
        row["claim_score"] = str(claim_score)
        row["claim_reason"] = claim_reason
        row["claim_status"] = determine_claim_status(row)
        rows.append(row)
    result = migrate_leads(pd.DataFrame(rows))
    if not result.empty:
        result["_claim"] = pd.to_numeric(result["claim_score"], errors="coerce").fillna(0)
        result["_need"] = pd.to_numeric(result["need_score"], errors="coerce").fillna(0)
        result = result.sort_values(["_claim", "_need", "firma"], ascending=[False, False, True]).drop(columns=["_claim", "_need"])
    return result


def company_identity_score(company: str, website: str, page_text: str, city: str = "") -> int:
    if not website:
        return 0
    score = 0
    company_norm = normalize_company(company)
    text_norm = normalize(page_text)
    tokens = [t for t in company_norm.split() if len(t) >= 3 and t not in {"gmbh", "gruppe", "group", "praxis", "kanzlei", "zentrum"}]
    if company_norm and company_norm in text_norm:
        score += 40
    token_hits = sum(1 for token in tokens[:6] if token in text_norm)
    score += min(30, token_hits * 8)
    if city and normalize(city) in text_norm:
        score += 10
    domain = root_domain(website)
    base = domain.split(".")[0].replace("-", " ") if domain else ""
    if any(token in normalize(base) for token in tokens[:6]):
        score += 15
    return max(0, min(100, score))


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; XING-Lead-Research/12.0)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
    })
    return session


def _safe_get(session: requests.Session, url: str, timeout: int = 15, max_bytes: int = 3_000_000) -> tuple[requests.Response | None, str]:
    try:
        response = session.get(url, timeout=timeout, allow_redirects=True)
        if response.status_code >= 400:
            return None, f"HTTP {response.status_code}"
        if len(response.content) > max_bytes:
            response._content = response.content[:max_bytes]
        return response, ""
    except requests.RequestException as exc:
        return None, str(exc)[:180]


def detect_ats(urls: Iterable[str]) -> str:
    found: list[str] = []
    for url in urls:
        host = (urlparse(clean_text(url)).hostname or "").lower()
        for suffix, label in ATS_HOSTS.items():
            if host == suffix or host.endswith("." + suffix):
                if label not in found:
                    found.append(label)
    return " | ".join(found)


def extract_jobpostings(html_text: str, base_url: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html_text or "", "html.parser")
    jobs: list[dict[str, str]] = []

    def walk(value: Any) -> Iterable[dict[str, Any]]:
        if isinstance(value, dict):
            if value.get("@type") == "JobPosting" or (isinstance(value.get("@type"), list) and "JobPosting" in value.get("@type", [])):
                yield value
            for nested in value.values():
                yield from walk(nested)
        elif isinstance(value, list):
            for nested in value:
                yield from walk(nested)

    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text(" ")
        if not raw.strip():
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        for item in walk(payload):
            title = clean_text(item.get("title", ""))
            if not title:
                continue
            url = clean_text(item.get("url", ""))
            if url:
                url = urljoin(base_url, url)
            location = ""
            loc = item.get("jobLocation")
            if isinstance(loc, list) and loc:
                loc = loc[0]
            if isinstance(loc, dict):
                address = loc.get("address", {})
                if isinstance(address, dict):
                    location = clean_text(address.get("addressLocality", "") or address.get("addressRegion", ""))
            jobs.append({
                "title": title,
                "url": url or base_url,
                "datePosted": clean_text(item.get("datePosted", "")),
                "validThrough": clean_text(item.get("validThrough", "")),
                "location": location,
            })
    unique_jobs: dict[str, dict[str, str]] = {}
    for job in jobs:
        key = normalize_job_title(job["title"]) + "|" + clean_text(job.get("location", "")).lower()
        unique_jobs[key] = job
    return list(unique_jobs.values())


def discover_sitemap_urls(session: requests.Session, website: str, limit: int = 120) -> list[str]:
    if not website:
        return []
    root = website.rstrip("/")
    queue = [urljoin(root + "/", "sitemap.xml"), urljoin(root + "/", "sitemap_index.xml")]
    seen_sitemaps: set[str] = set()
    candidate_urls: list[str] = []
    while queue and len(seen_sitemaps) < 8 and len(candidate_urls) < limit:
        sitemap_url = queue.pop(0)
        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)
        response, error = _safe_get(session, sitemap_url, timeout=12)
        if error or not response:
            continue
        try:
            xml_root = ET.fromstring(response.text)
        except ET.ParseError:
            continue
        for element in xml_root.iter():
            if not element.tag.endswith("loc") or not element.text:
                continue
            url = element.text.strip()
            low = url.lower()
            if low.endswith(".xml") and "sitemap" in low and url not in seen_sitemaps:
                queue.append(url)
                continue
            if any(token in low for token in CAREER_TOKENS + ("kontakt", "impressum", "team", "mitarbeiter", "people", "about", "unternehmen")):
                candidate_urls.append(url)
                if len(candidate_urls) >= limit:
                    break
    return unique(candidate_urls)


def _research_score(data: dict[str, Any]) -> int:
    score = 0
    if data.get("website"):
        score += 15
    if safe_int(data.get("company_confidence"), 0) >= 80:
        score += 20
    if data.get("karriereseite"):
        score += 15
    if data.get("ats_detected"):
        score += 10
    if safe_int(data.get("verified_open_jobs"), 0) > 0:
        score += 25
    if data.get("impressum"):
        score += 5
    if data.get("telefon"):
        score += 5
    if data.get("ansprechpartner"):
        score += 5
    return min(100, score)


def _research_depth(score: int) -> str:
    if score >= 80:
        return "deep"
    if score >= 55:
        return "standard"
    if score >= 25:
        return "basic"
    return "none"


def deep_research_lead(row: dict[str, Any], serpapi_key: str = "") -> tuple[dict[str, Any], list[str]]:
    item = dict(row)
    company = clean_text(item.get("firma", ""))
    city = split_pipe(item.get("orte", ""))[0] if split_pipe(item.get("orte", "")) else ""
    source_urls = unique([
        item.get("website", ""), item.get("stellenlink", ""), item.get("karriereseite", ""),
        *re.findall(r"https?://[^\s<>'\"]+", clean_text(item.get("job_context", ""))),
    ])
    diagnostics: list[str] = []
    base = research_company(
        company=company,
        city=city,
        source_urls=source_urls,
        source_text=clean_text(item.get("job_context", "")),
        serpapi_key=serpapi_key,
        max_pages=24,
    )
    mapping = {
        "website": "website", "contact_page": "kontaktseite", "imprint_page": "impressum",
        "career_page": "karriereseite", "email": "email", "phone": "telefon",
        "person": "ansprechpartner", "role": "rolle", "employee_hint": "employee_hint",
        "location_hint": "location_hint",
    }
    for source, target in mapping.items():
        if clean_text(base.get(source, "")):
            item[target] = clean_text(base.get(source, ""))
    item["research_text"] = clean_text(base.get("text", ""))[:50000]
    item["research_notes"] = clean_text(base.get("notes", ""))
    item["research_status"] = clean_text(base.get("status", "")) or "teilweise"
    item["pages_crawled"] = str(safe_int(base.get("pages_crawled"), 0))
    item["ats_detected"] = clean_text(base.get("ats_detected", ""))
    if clean_text(base.get("career_signal", "")):
        item["career_signal"] = clean_text(base.get("career_signal", ""))

    website = clean_text(item.get("website", ""))
    company_conf = company_identity_score(company, website, item.get("research_text", ""), city)
    item["company_confidence"] = str(company_conf)
    item["canonical_company"] = company
    item["canonical_domain"] = root_domain(website) if website else ""
    item["employer_type"] = classify_employer(company, item.get("research_text", ""))

    session = _session()
    urls: list[str] = []
    if website:
        sitemap_urls = discover_sitemap_urls(session, website)
        urls.extend(sitemap_urls)
        diagnostics.append(f"Sitemap: {len(sitemap_urls)} relevante URLs")
    if clean_text(item.get("karriereseite", "")):
        urls.insert(0, clean_text(item.get("karriereseite", "")))
    urls = unique(urls)[:30]
    ats = detect_ats(urls + [item.get("karriereseite", "")])
    if ats:
        item["ats_detected"] = " | ".join(unique([item.get("ats_detected", ""), ats]))

    official_jobs: list[dict[str, str]] = []
    pages_extra = 0
    research_sources: list[str] = ["Basis Recherche"]
    for url in urls[:18]:
        response, error = _safe_get(session, url, timeout=15)
        if error or not response:
            continue
        ctype = response.headers.get("content-type", "").lower()
        if "html" not in ctype and "xhtml" not in ctype:
            continue
        pages_extra += 1
        found = extract_jobpostings(response.text, response.url)
        if found:
            official_jobs.extend(found)
            research_sources.append("JobPosting JSON-LD")
        if not clean_text(item.get("karriereseite", "")) and any(token in response.url.lower() for token in CAREER_TOKENS):
            item["karriereseite"] = response.url
    official_map: dict[str, dict[str, str]] = {}
    for job in official_jobs:
        key = normalize_job_title(job.get("title", "")) + "|" + normalize(job.get("location", ""))
        official_map[key] = job
    official_jobs = list(official_map.values())
    item["pages_crawled"] = str(safe_int(item.get("pages_crawled"), 0) + pages_extra)
    item["verified_open_jobs"] = str(len(official_jobs))
    item["verified_job_titles"] = " | ".join(unique([job["title"] for job in official_jobs])[:20])
    if official_jobs:
        item["career_signal"] = f"{len(official_jobs)} konkrete JobPosting Stellen auf Firmen- oder ATS-Quelle verifiziert"
        if not item.get("karriereseite"):
            item["karriereseite"] = official_jobs[0].get("url", "")
    item["research_sources"] = " | ".join(unique(research_sources + (["Sitemap"] if website else [])))
    item["last_verified_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    item["research_updated_at"] = item["last_verified_at"]
    item["research_attempts"] = str(safe_int(item.get("research_attempts"), 0) + 1)
    item["pipeline_stage"] = "Deep Research"

    need_score, need_reason = calculate_need_score(item)
    item["need_score"] = str(need_score)
    item["need_confidence"] = need_reason
    claim_score, claim_reason = calculate_claim_score(item)
    item["claim_score"] = str(claim_score)
    item["claim_reason"] = claim_reason
    item["claim_status"] = determine_claim_status(item)
    research_score = _research_score(item)
    item["research_score"] = str(research_score)
    item["research_depth"] = _research_depth(research_score)
    diagnostics.append(
        f"{company}: Firma {company_conf}/100, Bedarf {need_score}/100, Claim {claim_score}/100, "
        f"offizielle Jobs {len(official_jobs)}, Tiefe {item['research_depth']}."
    )
    return item, diagnostics


def deep_research_candidates(frame: pd.DataFrame, limit: int = 20) -> list[int]:
    frame = migrate_leads(frame)
    if frame.empty:
        return []
    attempts = pd.to_numeric(frame["research_attempts"], errors="coerce").fillna(0)
    need = pd.to_numeric(frame["need_score"], errors="coerce").fillna(0)
    discovery = pd.to_numeric(frame["discovery_score"], errors="coerce").fillna(0)
    depth = frame["research_depth"].astype(str)
    candidates = frame[
        (depth != "deep")
        & (attempts < 4)
        & (~frame["status"].isin(["Ausschließen", "In Salesforce übernommen"]))
        & (frame["crm_status"] != "Bereits in Salesforce")
        & (frame["size_fit"] != "Groß oder unpassend")
        & (frame["employer_type"] != "Vermittler")
    ].copy()
    if candidates.empty:
        return []
    candidates["_need"] = need.loc[candidates.index]
    candidates["_disc"] = discovery.loc[candidates.index]
    candidates["_attempt"] = attempts.loc[candidates.index]
    candidates = candidates.sort_values(["_need", "_disc", "_attempt"], ascending=[False, False, True]).head(max(1, int(limit)))
    return list(candidates.index)


def apply_crm_exclusions(frame: pd.DataFrame, exclusion_keys: set[str]) -> pd.DataFrame:
    frame = migrate_leads(frame)
    exclusion_keys = {clean_text(x).lower() for x in exclusion_keys if clean_text(x)}
    for index, row in frame.iterrows():
        name_keys = {"@name:" + key for key in company_alias_keys(row.get("firma", ""))}
        domain = clean_text(row.get("canonical_domain", "")) or root_domain(clean_text(row.get("website", "")))
        domain_key = "@domain:" + domain.lower() if domain else ""
        phone = re.sub(r"\D", "", clean_text(row.get("telefon", "")))
        phone_key = "@phone:" + phone[-10:] if len(phone) >= 8 else ""
        matched = bool(name_keys & exclusion_keys) or (domain_key and domain_key in exclusion_keys) or (phone_key and phone_key in exclusion_keys)
        frame.at[index, "crm_status"] = "Bereits in Salesforce" if matched else "Neu"
        need_score, need_reason = calculate_need_score(frame.loc[index].to_dict())
        frame.at[index, "need_score"] = str(need_score)
        frame.at[index, "need_confidence"] = need_reason
        claim_score, claim_reason = calculate_claim_score(frame.loc[index].to_dict())
        frame.at[index, "claim_score"] = str(claim_score)
        frame.at[index, "claim_reason"] = claim_reason
        frame.at[index, "claim_status"] = determine_claim_status(frame.loc[index].to_dict())
    return frame


def crm_keys_from_frame(frame: pd.DataFrame) -> set[str]:
    keys: set[str] = set()
    if frame is None or frame.empty:
        return keys
    normalized_columns = {normalize(column): column for column in frame.columns}
    name_col = next((normalized_columns[k] for k in normalized_columns if any(x in k for x in ("account name", "accountname", "unternehmen", "firma", "firmenname", "name"))), None)
    website_col = next((normalized_columns[k] for k in normalized_columns if any(x in k for x in ("website", "webseite", "domain"))), None)
    phone_col = next((normalized_columns[k] for k in normalized_columns if any(x in k for x in ("telefon", "phone", "rufnummer"))), None)
    for _, row in frame.fillna("").iterrows():
        if name_col:
            name = clean_text(row.get(name_col, ""))
            for alias in company_alias_keys(name):
                keys.add("@name:" + alias)
        if website_col:
            value = clean_text(row.get(website_col, ""))
            domain = root_domain(value) if value else ""
            if domain:
                keys.add("@domain:" + domain.lower())
        if phone_col:
            digits = re.sub(r"\D", "", clean_text(row.get(phone_col, "")))
            if len(digits) >= 8:
                keys.add("@phone:" + digits[-10:])
    return keys
