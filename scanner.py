from __future__ import annotations

import base64
import json
import re
import time
from datetime import date
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BA_API_BASE = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service"
HEADERS = {
    "X-API-Key": "jobboerse-jobsuche",
    "User-Agent": "Mozilla/5.0 (compatible; XING-Daily-Leads/3.0)",
    "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
}

STAFFING_KEYWORDS = {
    "zeitarbeit", "arbeitnehmerüberlassung", "personaldienstleistung",
    "personalvermittlung", "personalberatung", "staffing", "headhunter",
    "direktvermittlung", "randstad", "adecco", "manpower", "office people",
    "iperdi", "bindan", "pluss personalmanagement", "akut medizin",
    "promedis24", "rocket match", "job ag", "runtime", "tempton",
    "timepartner", "dis ag", "amadeus fire", "ferchau", "wirtz medical",
    "avanti", "all.medi", "medcareer", "pacura med", "persona service",
    "piening", "expertum", "actief", "avitea", "meteor personaldienste",
}

PUBLIC_KEYWORDS = {
    "stadtverwaltung", "kreisverwaltung", "landratsamt", "bezirksamt",
    "bundesamt", "landesamt", "ministerium", "polizei", "bundeswehr",
    "agentur für arbeit", "jobcenter", "finanzamt", "justizvollzug",
    "öffentlicher dienst", "tvöd", "tv-l", "kommunalverwaltung",
}

LARGE_COMPANY_KEYWORDS = {
    "deutsche bahn", "db regio", "db infrago", "deutsche post", "dhl",
    "amazon", "siemens", "bosch", "volkswagen", "mercedes-benz", "bmw group",
    "continental", "lidl", "kaufland", "aldi", "rewe group",
    "deutsche telekom", "vodafone", "allianz", "helios kliniken",
    "asklepios", "sana kliniken", "ameos", "korian", "fresenius",
    "thyssenkrupp", "basf", "bayer ag", "rwe ag", "e.on", "ikea", "zalando",
}

TARGET_KEYWORDS = {
    "physio": 24, "ergotherapeut": 24, "ergotherapie": 24, "logopä": 24,
    "sprachtherap": 24, "pflegefach": 22, "ambulante pflege": 24, "pflege": 20,
    "steuerfach": 23, "steuerkanzlei": 22, "bilanzbuchhalter": 20,
    "lohnbuchhalter": 19, "elektriker": 18, "elektroniker": 18,
    "anlagenmechaniker": 18, "shk": 18, "sanitär": 17, "heizung": 17,
    "klima": 17, "metallbau": 16, "schweißer": 16, "zerspan": 17,
    "cnc": 17, "mechatroniker": 17, "tischler": 16, "schreiner": 16,
    "dachdecker": 16, "maler": 15, "bauleiter": 18, "projektleiter": 16,
    "konstrukteur": 16, "ingenieur": 15, "softwareentwickler": 15,
    "it administrator": 15, "systemadministrator": 15, "vertrieb": 12,
    "sales": 12, "produktion": 12, "maschinenbediener": 14, "zahnarzt": 17,
    "zahnmedizin": 18, "medizinische fachangestellte": 18, "mfa": 17,
    "praxis": 12, "therapie": 18, "servicetechniker": 16,
}

BUYING_SIGNALS = {
    "ab sofort": 4, "dringend": 7, "schnellstmöglich": 7,
    "zum nächstmöglichen zeitpunkt": 5, "unbefristet": 3,
    "mehrere standorte": 5, "wachstum": 6, "verstärkung": 3,
    "team erweitern": 6, "neu eröffnet": 8, "neuer standort": 8,
    "weitere verstärkung": 5, "expandieren": 6,
}

BENEFIT_KEYWORDS = {
    "30 tage urlaub": 3, "31 tage urlaub": 4, "32 tage urlaub": 4,
    "33 tage urlaub": 5, "34 tage urlaub": 5, "35 tage urlaub": 6,
    "jobrad": 3, "jobticket": 3, "firmenwagen": 4, "fortbildung": 3,
    "weiterbildung": 3, "flexible arbeitszeit": 3, "homeoffice": 2,
    "betriebliche altersvorsorge": 2, "gesundheitsbudget": 3,
    "keine wochenendarbeit": 4, "keine schichtarbeit": 4, "übertarif": 3,
}

MIN_LEAD_SCORE = 18


def _session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        backoff_factor=0.3,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        raise_on_status=False,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    session.headers.update(HEADERS)
    return session


_SESSION = _session()


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", BeautifulSoup(str(value), "html.parser").get_text(" ")).strip()


def _get(url: str, params: dict | None = None, timeout: int = 25) -> tuple[requests.Response | None, str]:
    try:
        response = _SESSION.get(url, params=params, timeout=timeout, allow_redirects=True)
        if response.status_code >= 400:
            return None, f"{response.status_code} {response.reason}: {response.text[:180]}"
        return response, ""
    except requests.RequestException as exc:
        return None, str(exc)[:220]


def _first(data: dict, *keys: str) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, "", [], {}):
            return value
    return ""


def _nested(data: dict, *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return ""
        current = current.get(key, "")
    return current or ""


def _iso_date(value: Any) -> str:
    text = _clean(value)
    if not text:
        return ""
    match = re.search(r"\d{4}-\d{2}-\d{2}", text)
    return match.group(0) if match else text[:10]


def _job(
    *,
    company: str,
    title: str,
    city: str = "",
    published: str = "",
    description: str = "",
    url: str = "",
    email: str = "",
    phone: str = "",
    contact: str = "",
    source: str = "",
    reference: str = "",
    term: str = "",
) -> dict:
    return {
        "reference": _clean(reference) or f"{source}:{url}:{company}:{title}",
        "company": _clean(company),
        "title": _clean(title),
        "description": _clean(description),
        "city": _clean(city),
        "published": _iso_date(published),
        "external_url": _clean(url),
        "job_link": _clean(url),
        "email": _clean(email),
        "phone": _clean(phone),
        "contact": _clean(contact),
        "term": _clean(term),
        "source": source,
    }


# ---------------------------------------------------------------------------
# Bundesagentur
# ---------------------------------------------------------------------------

def _ba_details(reference: str, diagnostics: list[str]) -> dict:
    if not reference:
        return {}
    encoded = base64.b64encode(reference.encode("utf-8")).decode("utf-8")
    response, error = _get(f"{BA_API_BASE}/pc/v4/jobdetails/{encoded}")
    if error:
        diagnostics.append(f"BA Detail {reference}: {error}")
        return {}
    try:
        return response.json() if response else {}
    except ValueError:
        diagnostics.append(f"BA Detail {reference}: ungültige JSON Antwort")
        return {}


def scan_ba(
    terms: list[str],
    regions: list[tuple[str, int]],
    days: int,
    max_pages: int,
    diagnostics: list[str],
) -> list[dict]:
    raw: list[dict] = []
    request_count = 0
    for term in terms:
        for city, radius in regions:
            for page in range(1, max(1, min(int(max_pages), 5)) + 1):
                params = {
                    "angebotsart": 1,
                    "was": term,
                    "wo": city,
                    "umkreis": radius,
                    "page": page,
                    "size": 25,
                    "veroeffentlichtseit": days,
                    "zeitarbeit": "false",
                    "pav": "false",
                }
                response, error = _get(f"{BA_API_BASE}/pc/v6/jobs", params=params)
                request_count += 1
                if error:
                    diagnostics.append(f"BA Suche {term} · {city}: {error}")
                    break
                try:
                    payload = response.json() if response else {}
                except ValueError:
                    diagnostics.append(f"BA Suche {term} · {city}: ungültige JSON Antwort")
                    break
                batch = payload.get("stellenangebote") or payload.get("jobs") or []
                if not batch:
                    break
                for item in batch:
                    item["_term"] = term
                    raw.append(item)
                if len(batch) < 25:
                    break
                time.sleep(0.05)

    parsed: list[dict] = []
    seen: set[str] = set()
    detail_calls = 0
    detail_limit = 220
    for item in raw:
        reference = _clean(_first(item, "referenznummer", "refnr", "refNr"))
        if reference and reference in seen:
            continue
        if reference:
            seen.add(reference)

        summary_company = _clean(_first(item, "arbeitgeber", "arbeitgeberName", "firma"))
        summary_title = _clean(_first(item, "titel", "stellenangebotsTitel", "beruf"))
        summary_combined = f"{summary_company} {summary_title}"
        if _hit(summary_combined, STAFFING_KEYWORDS) or _hit(summary_company, LARGE_COMPANY_KEYWORDS):
            continue

        details = {}
        if reference and detail_calls < detail_limit:
            details = _ba_details(reference, diagnostics)
            detail_calls += 1
        company = _clean(
            summary_company
            or _first(details, "arbeitgeber", "arbeitgeberName", "firmenname")
        )
        title = _clean(
            summary_title
            or _first(details, "stellenangebotsTitel", "titel")
        )
        if not company or not title:
            continue
        external_url = _clean(
            _first(item, "externeUrl", "externeURL", "url")
            or _first(details, "externeUrl", "externeURL", "url")
        )
        fallback_url = f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{reference}" if reference else ""
        parsed.append(_job(
            company=company,
            title=title,
            city=_nested(item, "arbeitsort", "ort") or _nested(details, "arbeitsort", "ort") or _first(item, "arbeitsort", "ort"),
            published=_first(item, "veroeffentlichungsdatum", "veroeffentlichtAm", "modifikationsTimestamp"),
            description=_first(details, "stellenangebotsBeschreibung", "stellenbeschreibung", "beschreibung"),
            url=external_url or fallback_url,
            email=_first(details, "email", "eMail", "kontaktEmail") or _nested(details, "hauptkontakt", "email"),
            phone=_first(details, "telefon", "telefonnummer", "kontaktTelefon") or _nested(details, "hauptkontakt", "telefon"),
            contact=_first(details, "ansprechpartner", "kontaktName") or _nested(details, "hauptkontakt", "name"),
            source="Bundesagentur",
            reference=reference,
            term=item.get("_term", ""),
        ))
    diagnostics.append(
        f"Bundesagentur: {len(parsed)} Stellen aus {request_count} Suchanfragen, "
        f"{detail_calls} Detailseiten geprüft."
    )
    return parsed


# ---------------------------------------------------------------------------
# Adzuna
# ---------------------------------------------------------------------------

def scan_adzuna(
    terms: list[str],
    regions: list[tuple[str, int]],
    days: int,
    max_pages: int,
    app_id: str,
    api_key: str,
    diagnostics: list[str],
) -> list[dict]:
    if not app_id or not api_key:
        diagnostics.append("Adzuna: nicht aktiv, Zugangsdaten fehlen.")
        return []
    jobs: list[dict] = []
    request_count = 0
    page_limit = max(1, min(int(max_pages), 5))
    for term in terms:
        for city, radius in regions:
            for page in range(1, page_limit + 1):
                params = {
                    "app_id": app_id,
                    "app_key": api_key,
                    "what": term,
                    "where": city,
                    "distance": radius,
                    "max_days_old": days,
                    "results_per_page": 50,
                    "content-type": "application/json",
                    "sort_by": "date",
                }
                response, error = _get(f"https://api.adzuna.com/v1/api/jobs/de/search/{page}", params=params, timeout=30)
                request_count += 1
                if error:
                    diagnostics.append(f"Adzuna {term} · {city}: {error}")
                    break
                try:
                    payload = response.json() if response else {}
                except ValueError:
                    diagnostics.append(f"Adzuna {term} · {city}: ungültige JSON Antwort")
                    break
                batch = payload.get("results") or []
                if not batch:
                    break
                for item in batch:
                    company_data = item.get("company") or {}
                    location_data = item.get("location") or {}
                    category_data = item.get("category") or {}
                    company = _clean(company_data.get("display_name") if isinstance(company_data, dict) else company_data)
                    title = _clean(item.get("title"))
                    if not company or not title:
                        continue
                    description = _clean(item.get("description"))
                    category = _clean(category_data.get("label") if isinstance(category_data, dict) else category_data)
                    if category:
                        description = f"{category}. {description}".strip()
                    jobs.append(_job(
                        company=company,
                        title=title,
                        city=location_data.get("display_name", city) if isinstance(location_data, dict) else city,
                        published=item.get("created", ""),
                        description=description,
                        url=item.get("redirect_url", ""),
                        source="Adzuna",
                        reference=str(item.get("id", "")),
                        term=term,
                    ))
                if len(batch) < 50:
                    break
                time.sleep(0.05)
    diagnostics.append(f"Adzuna: {len(jobs)} Stellen aus {request_count} Suchanfragen.")
    return jobs


# ---------------------------------------------------------------------------
# Google Jobs via SerpApi mit Pagination
# ---------------------------------------------------------------------------

def scan_google_jobs(
    terms: list[str],
    regions: list[tuple[str, int]],
    days: int,
    max_pages: int,
    serpapi_key: str,
    diagnostics: list[str],
) -> list[dict]:
    if not serpapi_key:
        diagnostics.append("Google Jobs: nicht aktiv, SerpApi Key fehlt.")
        return []
    jobs: list[dict] = []
    request_count = 0
    for term in terms:
        for city, _radius in regions:
            next_page_token = ""
            for page in range(max(1, min(int(max_pages), 3))):
                params = {
                    "engine": "google_jobs",
                    "q": f"{term} {city}",
                    "hl": "de",
                    "gl": "de",
                    "api_key": serpapi_key,
                }
                if next_page_token:
                    params["next_page_token"] = next_page_token
                response, error = _get("https://serpapi.com/search.json", params=params, timeout=30)
                request_count += 1
                if error:
                    diagnostics.append(f"Google Jobs {term} · {city}: {error}")
                    break
                try:
                    payload = response.json() if response else {}
                except ValueError:
                    diagnostics.append(f"Google Jobs {term} · {city}: ungültige JSON Antwort")
                    break
                batch = payload.get("jobs_results", [])
                for item in batch:
                    company = _clean(item.get("company_name"))
                    title = _clean(item.get("title"))
                    if not company or not title:
                        continue
                    detected = item.get("detected_extensions") or {}
                    apply_options = item.get("apply_options") or []
                    url = apply_options[0].get("link", "") if apply_options else ""
                    url = url or item.get("share_link", "")
                    jobs.append(_job(
                        company=company,
                        title=title,
                        city=item.get("location", city),
                        published=detected.get("posted_at", ""),
                        description=item.get("description", ""),
                        url=url,
                        source="Google Jobs",
                        reference=item.get("job_id", ""),
                        term=term,
                    ))
                next_page_token = (payload.get("serpapi_pagination") or {}).get("next_page_token", "")
                if not batch or not next_page_token:
                    break
                time.sleep(0.08)
    diagnostics.append(f"Google Jobs: {len(jobs)} Stellen aus {request_count} Suchanfragen.")
    return jobs


# ---------------------------------------------------------------------------
# Direkte Karriereseiten und ATS
# ---------------------------------------------------------------------------

def _iter_jsonld(soup: BeautifulSoup):
    for node in soup.select('script[type="application/ld+json"]'):
        raw = node.string or node.get_text()
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        queue = data if isinstance(data, list) else [data]
        while queue:
            item = queue.pop(0)
            if isinstance(item, list):
                queue.extend(item)
            elif isinstance(item, dict):
                graph = item.get("@graph")
                if isinstance(graph, list):
                    queue.extend(graph)
                yield item


def _jsonld_jobs(soup: BeautifulSoup, page_url: str) -> list[dict]:
    jobs: list[dict] = []
    for item in _iter_jsonld(soup):
        item_type = item.get("@type")
        types = item_type if isinstance(item_type, list) else [item_type]
        if "JobPosting" not in types:
            continue
        org = item.get("hiringOrganization") or {}
        location = item.get("jobLocation") or {}
        if isinstance(location, list):
            location = location[0] if location else {}
        address = location.get("address") if isinstance(location, dict) else {}
        if not isinstance(address, dict):
            address = {}
        company = org.get("name", "") if isinstance(org, dict) else ""
        title = item.get("title", "")
        if not company or not title:
            continue
        identifier = item.get("identifier") or {}
        jobs.append(_job(
            company=company,
            title=title,
            city=address.get("addressLocality", ""),
            published=item.get("datePosted", ""),
            description=item.get("description", ""),
            url=item.get("url") or page_url,
            source="Karriereseite",
            reference=identifier.get("value", "") if isinstance(identifier, dict) else "",
        ))
    return jobs


def _greenhouse_token(url: str) -> str:
    match = re.search(r"(?:boards|job-boards)\.greenhouse\.io/([^/?#]+)", url)
    return match.group(1) if match else ""


def _lever_token(url: str) -> str:
    match = re.search(r"jobs\.lever\.co/([^/?#]+)", url)
    return match.group(1) if match else ""


def _personio_host(url: str) -> str:
    parsed = urlparse(url if "://" in url else "https://" + url)
    host = parsed.netloc.lower()
    return host.split(".jobs.personio.de")[0] if host.endswith(".jobs.personio.de") else ""


def _scan_greenhouse(url: str, diagnostics: list[str]) -> list[dict]:
    token = _greenhouse_token(url)
    if not token:
        return []
    response, error = _get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs", params={"content": "true"})
    if error:
        diagnostics.append(f"Greenhouse {token}: {error}")
        return []
    try:
        payload = response.json() if response else {}
    except ValueError:
        return []
    return [
        _job(
            company=token.replace("-", " ").title(),
            title=item.get("title", ""),
            city=(item.get("location") or {}).get("name", ""),
            published=item.get("updated_at", ""),
            description=item.get("content", ""),
            url=item.get("absolute_url", ""),
            source="Greenhouse",
            reference=str(item.get("id", "")),
        )
        for item in payload.get("jobs", [])
        if item.get("title")
    ]


def _scan_lever(url: str, diagnostics: list[str]) -> list[dict]:
    token = _lever_token(url)
    if not token:
        return []
    response, error = _get(f"https://api.lever.co/v0/postings/{token}", params={"mode": "json"})
    if error:
        diagnostics.append(f"Lever {token}: {error}")
        return []
    try:
        payload = response.json() if response else []
    except ValueError:
        return []
    result = []
    for item in payload if isinstance(payload, list) else []:
        categories = item.get("categories") or {}
        result.append(_job(
            company=token.replace("-", " ").title(),
            title=item.get("text", ""),
            city=categories.get("location", ""),
            description=item.get("descriptionPlain", "") or item.get("description", ""),
            url=item.get("hostedUrl", ""),
            source="Lever",
            reference=item.get("id", ""),
        ))
    return result


def _scan_personio(url: str, diagnostics: list[str]) -> list[dict]:
    host = _personio_host(url)
    if not host:
        return []
    response = None
    for feed in (f"https://{host}.jobs.personio.de/xml", f"https://{host}.jobs.personio.de/xml?language=de"):
        response, _error = _get(feed)
        if response:
            break
    if not response:
        diagnostics.append(f"Personio {host}: XML Feed nicht erreichbar.")
        return []
    try:
        soup = BeautifulSoup(response.content, "xml")
    except Exception:
        soup = BeautifulSoup(response.content, "html.parser")
    result = []
    for position in soup.find_all("position"):
        title = _clean(position.find("name").get_text(" ") if position.find("name") else "")
        company = _clean(position.find("subcompany").get_text(" ") if position.find("subcompany") else "") or host.replace("-", " ").title()
        office = _clean(position.find("office").get_text(" ") if position.find("office") else "")
        description = " ".join(_clean(node.get_text(" ")) for node in position.find_all(["jobDescription", "description"]))
        job_id = _clean(position.find("id").get_text(" ") if position.find("id") else "")
        if title:
            result.append(_job(
                company=company,
                title=title,
                city=office,
                description=description,
                url=f"https://{host}.jobs.personio.de/job/{job_id}" if job_id else url,
                source="Personio",
                reference=job_id,
            ))
    return result


def scan_career_urls(urls: list[str], diagnostics: list[str]) -> list[dict]:
    result: list[dict] = []
    for raw_url in urls:
        url = raw_url.strip()
        if not url:
            continue
        if "://" not in url:
            url = "https://" + url
        if _greenhouse_token(url):
            jobs = _scan_greenhouse(url, diagnostics)
        elif _lever_token(url):
            jobs = _scan_lever(url, diagnostics)
        elif _personio_host(url):
            jobs = _scan_personio(url, diagnostics)
        else:
            response, error = _get(url)
            if error or not response:
                diagnostics.append(f"Karriereseite {url}: {error or 'nicht erreichbar'}")
                continue
            if "html" not in response.headers.get("content-type", "").lower():
                diagnostics.append(f"Karriereseite {url}: kein HTML.")
                continue
            jobs = _jsonld_jobs(BeautifulSoup(response.text, "html.parser"), response.url)
        result.extend(jobs)
        diagnostics.append(f"Karriereseite: {len(jobs)} Stellen aus {url}")
    return result


# ---------------------------------------------------------------------------
# Deduplication und Scoring
# ---------------------------------------------------------------------------

def _norm(value: Any) -> str:
    text = _clean(value).lower()
    return text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")


def _company_key(company: str) -> str:
    text = _norm(company)
    for token in [" gmbh", " mbh", " ag", " kg", " ohg", " ug", " e.v.", " ev", " gbr", " se", " & co"]:
        text = text.replace(token, " ")
    return re.sub(r"\W+", "", text)


def _dedup_key(job: dict) -> str:
    return "|".join([
        _company_key(job.get("company", "")),
        re.sub(r"\W+", "", _norm(job.get("title", ""))),
        re.sub(r"\W+", "", _norm(job.get("city", ""))),
    ])


def deduplicate(jobs: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for job in jobs:
        key = _dedup_key(job)
        if not job.get("company") or not job.get("title"):
            continue
        if key not in merged:
            merged[key] = dict(job)
            merged[key]["sources"] = [job.get("source", "")] if job.get("source") else []
            continue
        current = merged[key]
        current["sources"] = sorted(set(current.get("sources", []) + ([job.get("source", "")] if job.get("source") else [])))
        for field in ("description", "email", "phone", "contact", "external_url", "job_link", "published"):
            if not current.get(field) and job.get(field):
                current[field] = job[field]
        if len(job.get("description", "")) > len(current.get("description", "")):
            current["description"] = job["description"]
    output = list(merged.values())
    for job in output:
        job["source"] = " | ".join(job.pop("sources", []))
    return output


def _hit(text: str, keywords: set[str]) -> str:
    normal = _norm(text)
    for keyword in keywords:
        if _norm(keyword) in normal:
            return keyword
    return ""


def _weighted(text: str, mapping: dict[str, int]) -> tuple[int, list[str]]:
    normal = _norm(text)
    score, hits = 0, []
    for keyword, points in mapping.items():
        if _norm(keyword) in normal:
            score += points
            hits.append(keyword)
    return score, hits


def _company_stats(jobs: list[dict]) -> dict[str, dict]:
    grouped: dict[str, list[dict]] = {}
    for job in jobs:
        grouped.setdefault(_company_key(job.get("company", "")), []).append(job)
    result = {}
    for key, items in grouped.items():
        result[key] = {
            "job_count": len(items),
            "distinct_titles": len({_norm(x.get("title", "")) for x in items}),
            "location_count": len({_norm(x.get("city", "")) for x in items if x.get("city")}),
            "source_count": len({part.strip() for x in items for part in x.get("source", "").split("|") if part.strip()}),
        }
    return result


def score_and_filter(jobs: list[dict], diagnostics: list[str]) -> list[dict]:
    unique = deduplicate(jobs)
    stats = _company_stats(unique)
    output = []
    excluded = {"staffing": 0, "public": 0, "large": 0, "low_score": 0}
    for job in unique:
        company = job.get("company", "")
        title = job.get("title", "")
        description = job.get("description", "")
        combined = " ".join([company, title, description, job.get("term", "")])
        if _hit(combined, STAFFING_KEYWORDS):
            excluded["staffing"] += 1
            continue
        if _hit(company + " " + title + " " + description[:1200], PUBLIC_KEYWORDS):
            excluded["public"] += 1
            continue
        if _hit(company, LARGE_COMPANY_KEYWORDS):
            excluded["large"] += 1
            continue

        company_data = stats.get(_company_key(company), {})
        score = 8
        reasons = []
        points, hits = _weighted(combined, TARGET_KEYWORDS)
        if points:
            score += min(34, points)
            reasons.append("Zielgruppe: " + ", ".join(hits[:3]))
        points, hits = _weighted(combined, BUYING_SIGNALS)
        if points:
            score += min(15, points)
            reasons.append("Recruitingdruck: " + ", ".join(hits[:3]))
        points, hits = _weighted(description, BENEFIT_KEYWORDS)
        if points:
            score += min(12, points)
            reasons.append("Benefits: " + ", ".join(hits[:3]))

        job_count = company_data.get("job_count", 1)
        distinct_titles = company_data.get("distinct_titles", 1)
        location_count = company_data.get("location_count", 1)
        source_count = company_data.get("source_count", 1)
        if 2 <= job_count <= 9:
            score += min(18, 5 + (job_count - 2) * 2)
            reasons.append(f"{job_count} offene Stellen")
        if distinct_titles >= 2:
            score += min(8, distinct_titles * 2)
            reasons.append(f"{distinct_titles} verschiedene Rollen")
        if location_count >= 2:
            score += min(7, location_count * 2)
            reasons.append(f"{location_count} Standorte")
        if source_count >= 2:
            score += 4
            reasons.append("mehrere Jobquellen")
        if job.get("email"):
            score += 8
            reasons.append("E Mail vorhanden")
        if job.get("contact"):
            score += 7
            reasons.append("Ansprechpartner vorhanden")
        if job.get("phone"):
            score += 4
        if job.get("external_url"):
            score += 3
        if len(description) >= 500:
            score += 3
        if "Karriereseite" in job.get("source", ""):
            score += 5
            reasons.append("eigene Karriereseite")
        if job_count >= 20:
            score -= 18
        elif job_count >= 10:
            score -= 8
        score = max(0, min(100, score))
        if score < MIN_LEAD_SCORE:
            excluded["low_score"] += 1
            continue
        job.update(company_data)
        job["lead_score"] = score
        job["lead_quality"] = "A" if score >= 75 else "B" if score >= 55 else "C"
        job["lead_reasons"] = "; ".join(reasons[:7])
        output.append(job)

    output.sort(key=lambda x: (x.get("lead_score", 0), x.get("job_count", 0), bool(x.get("contact")), bool(x.get("email"))), reverse=True)
    diagnostics.append(
        f"Lead Filter: {len(unique)} eindeutige Stellen geprüft, {len(output)} verkaufsrelevante Treffer. "
        f"Raus: Staffing {excluded['staffing']}, öffentlich {excluded['public']}, "
        f"Großunternehmen {excluded['large']}, Score {excluded['low_score']}."
    )
    return output


def scan_jobs(
    *,
    terms: list[str],
    regions: list[tuple[str, int]],
    days: int,
    max_pages: int,
    sources: list[str],
    career_urls: list[str] | None = None,
    serpapi_key: str = "",
    adzuna_app_id: str = "",
    adzuna_api_key: str = "",
) -> tuple[list[dict], list[str]]:
    diagnostics: list[str] = []
    jobs: list[dict] = []
    if "Adzuna" in sources:
        jobs.extend(scan_adzuna(terms, regions, days, max_pages, adzuna_app_id, adzuna_api_key, diagnostics))
    if "Bundesagentur" in sources:
        jobs.extend(scan_ba(terms, regions, days, max_pages, diagnostics))
    if "Google Jobs" in sources:
        jobs.extend(scan_google_jobs(terms, regions, days, max_pages, serpapi_key, diagnostics))
    if "Karriereseiten" in sources:
        jobs.extend(scan_career_urls(career_urls or [], diagnostics))
    filtered = score_and_filter(jobs, diagnostics)
    diagnostics.append(f"Gesamt: {len(filtered)} priorisierte Stellen aus {len(sources)} aktivierten Quellen am {date.today().isoformat()}.")
    return filtered, diagnostics
