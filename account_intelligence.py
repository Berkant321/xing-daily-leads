from __future__ import annotations

from typing import Any

import pandas as pd


def _clean(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def normalize_company(value: Any) -> str:
    text = _clean(value).lower()
    text = text.replace("&", " und ")
    text = text.replace(".", " ")
    text = text.replace("-", " ")
    text = text.replace("_", " ")
    text = " ".join(text.split())
    return text


def _company_match(company_name: Any, frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or not isinstance(frame, pd.DataFrame):
        return frame.iloc[0:0].copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    company_key = normalize_company(company_name)
    if not company_key:
        return frame.iloc[0:0].copy()
    if "firma" in frame.columns:
        candidate_col = "firma"
    elif "company" in frame.columns:
        candidate_col = "company"
    else:
        return frame.iloc[0:0].copy()

    values = frame[candidate_col].map(normalize_company)
    return frame.loc[values.str.contains(company_key, regex=False, na=False)].copy()


def _top_values(series: pd.Series, limit: int = 5) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for raw in series.dropna().astype(str):
        item = _clean(raw)
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        values.append(item)
        if len(values) >= limit:
            break
    return values


def _job_titles_from_frame(frame: pd.DataFrame) -> list[str]:
    titles: list[str] = []
    if frame.empty:
        return titles
    if "position" in frame.columns:
        titles.extend(_top_values(frame["position"], limit=8))
    if "job_titles" in frame.columns:
        extras = frame["job_titles"].dropna().astype(str)
        exploded = extras.str.split("|").explode()
        titles.extend(_top_values(exploded, limit=8))
    if "verified_job_titles" in frame.columns:
        extras = frame["verified_job_titles"].dropna().astype(str)
        exploded = extras.str.split("|").explode()
        titles.extend(_top_values(exploded, limit=8))
    return _top_values(pd.Series(titles), limit=8)


def company_profile(leads: pd.DataFrame, jobs: pd.DataFrame, evidence: pd.DataFrame, company_name: str) -> dict[str, Any]:
    company = _clean(company_name)
    lead_rows = _company_match(company, leads)
    job_rows = _company_match(company, jobs)
    evidence_rows = _company_match(company, evidence)

    if not job_rows.empty or not lead_rows.empty:
        combined = pd.concat([job_rows, lead_rows], ignore_index=True)
        job_titles = _job_titles_from_frame(combined)
    else:
        job_titles = []

    cities: list[str] = []
    if not job_rows.empty:
        for column in ["ort", "city", "location"]:
            if column in job_rows.columns:
                cities.extend(_top_values(job_rows[column], limit=6))
    cities = _top_values(pd.Series(cities), limit=6)

    need_score = 0.0
    claim_score = 0.0
    verified_jobs = 0
    if not lead_rows.empty:
        for column in ["need_score", "claim_score"]:
            if column in lead_rows.columns:
                numeric = pd.to_numeric(lead_rows[column], errors="coerce").fillna(0)
                if column == "need_score":
                    need_score = float(numeric.max()) if not numeric.empty else 0.0
                else:
                    claim_score = float(numeric.max()) if not numeric.empty else 0.0
        if "verified_open_jobs" in lead_rows.columns:
            verified_jobs = int(pd.to_numeric(lead_rows["verified_open_jobs"], errors="coerce").fillna(0).sum())

    job_count = int(len(job_rows))
    evidence_count = int(len(evidence_rows))

    score = 15 + min(35, job_count * 3) + min(25, verified_jobs * 5) + min(10, evidence_count * 2)
    if need_score:
        score += min(15, int(need_score / 10))
    if claim_score:
        score += min(10, int(claim_score / 15))

    if score >= 80:
        priority = "Zeitnah"
    elif score >= 55:
        priority = "Klärung"
    else:
        priority = "Planen"

    signals: list[str] = []
    if job_count:
        signals.append(f"{job_count} dokumentierte Stellen / Job-Signale")
    if verified_jobs:
        signals.append(f"{verified_jobs} verifizierte Stellen oder starke Recruiting-Signale")
    if evidence_count:
        signals.append(f"{evidence_count} interne oder externe Belege")
    if not job_titles:
        signals.append("Keine klaren öffentlichen Job-Signale erkannt")

    risks: list[str] = []
    if not job_titles:
        risks.append("Keine klaren Rollen- oder Hiring-Signale")
    if not evidence_count:
        risks.append("Noch wenig belastbare Unternehmens- oder Marktbelege")
    if not leads.empty and "email" in leads.columns and "firma" in leads.columns:
        match = _company_match(company, leads)
        if not match.empty and "email" in match.columns and not match["email"].astype(str).str.strip().any():
            risks.append("Kontaktbreite noch schwach")

    recommendations = [
        "Website, Karrierebereich und Wachstumsberichte mit Fokus auf Standort- und Hiring-Strategie prüfen",
        "Stakeholder, Buying Center und Entscheidungsträger im Unternehmen mapen",
        "Recruiting-Pain und geschäftliche Wirkung mit klaren Fragen gegen den Jobbedarf validieren",
    ]
    if job_titles:
        recommendations.insert(0, f"Auf {job_titles[0]} fokussieren, weil diese Rolle am stärksten im Portfolio sichtbar ist")

    briefing = (
        f"{company} hat heute {job_count} dokumentierte Job-Signale, {evidence_count} Nachweise und eine "
        f"Portfolio-Priorität von {priority}. "
        f"Die wichtigsten Rollen sind: {', '.join(job_titles[:3]) if job_titles else 'noch unklar'}. "
        f"Standorte: {', '.join(cities) if cities else 'noch unklar'}."
    )

    return {
        "company": company,
        "score": int(score),
        "priority": priority,
        "job_count": int(job_count),
        "verified_jobs": int(verified_jobs),
        "evidence_count": int(evidence_count),
        "job_titles": job_titles,
        "cities": cities,
        "signals": signals,
        "risks": risks,
        "recommendations": recommendations,
        "briefing": briefing,
    }


def portfolio_snapshot(leads: pd.DataFrame, jobs: pd.DataFrame, evidence: pd.DataFrame, limit: int = 20) -> pd.DataFrame:
    companies: list[str] = []
    if not leads.empty and "firma" in leads.columns:
        companies = sorted({_clean(value) for value in leads["firma"].tolist() if _clean(value)})
    elif not jobs.empty and "firma" in jobs.columns:
        companies = sorted({_clean(value) for value in jobs["firma"].tolist() if _clean(value)})
    elif not evidence.empty and "firma" in evidence.columns:
        companies = sorted({_clean(value) for value in evidence["firma"].tolist() if _clean(value)})

    rows: list[dict[str, Any]] = []
    for company in companies:
        profile = company_profile(leads, jobs, evidence, company)
        rows.append(
            {
                "Firma": profile["company"],
                "Priorität": profile["priority"],
                "Score": profile["score"],
                "Stellen": profile["job_count"],
                "Verifiziert": profile["verified_jobs"],
                "Belege": profile["evidence_count"],
                "Hauptrollen": ", ".join(profile["job_titles"][:3]),
                "Standorte": ", ".join(profile["cities"][:3]),
                "Briefing": profile["briefing"],
            }
        )

    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(
            columns=["Firma", "Priorität", "Score", "Stellen", "Verifiziert", "Belege", "Hauptrollen", "Standorte", "Briefing"]
        )
    return frame.sort_values(["Score", "Stellen", "Belege"], ascending=[False, False, False]).head(limit).reset_index(drop=True)


def account_briefing_text(profile: dict[str, Any]) -> str:
    lines = [
        f"Unternehmen: {profile['company']}",
        f"Priorität: {profile['priority']} | Score: {profile['score']}",
        f"Stellen: {profile['job_count']} | Verifiziert: {profile['verified_jobs']} | Belege: {profile['evidence_count']}",
        "",
        "Signale:",
    ]
    for signal in profile.get("signals", []):
        lines.append(f"- {signal}")
    lines.extend(["", "Risiken:"])
    for risk in profile.get("risks", []):
        lines.append(f"- {risk}")
    lines.extend(["", "Empfohlene nächste Schritte:"])
    for item in profile.get("recommendations", []):
        lines.append(f"- {item}")
    return "\n".join(lines)
