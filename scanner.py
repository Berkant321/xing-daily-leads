from __future__ import annotations

import base64
import json
import re
import time
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BA_API_BASE = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service"
HEADERS = {
    "X-API-Key": "jobboerse-jobsuche",
    "User-Agent": "Mozilla/5.0 (compatible; XING-Daily-Leads/2.0)",
    "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
}


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", BeautifulSoup(str(value), "html.parser").get_text(" ")).strip()


def _get(url: str, params: dict | None = None, timeout: int = 20) -> tuple[requests.Response | None, str]:
    try:
        response = requests.get(
            url,
            params=params,
            headers=HEADERS,
            timeout=timeout,
            allow_redirects=True,
        )
        if response.status_code >= 400:
            return None, f"{response.status_code} {response.reason}: {response.text[:250]}"
        return response, ""
    except requests.RequestException as exc:
        return None, str(exc)


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
# 1) Bundesagentur
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
        diagnostics.append(f"BA Detail {reference}: ungültige JSON-Antwort")
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
            for page in range(1, max_pages + 1):
                params = {
                    "angebotsart": 1,
                    "was": term,
                    "wo": city,
                    "umkreis": radius,
                    "page": page,
                    "size": 25,
                    "veroeffentlichtseit": days,
                }
                response, error = _get(f"{BA_API_BASE}/pc/v6/jobs", params=params)
                request_count += 1
                if error:
                    diagnostics.append(f"BA Suche {term} · {city}: {error}")
                    break
                try:
                    payload = response.json() if response else {}
                except ValueError:
                    diagnostics.append(f"BA Suche {term} · {city}: ungültige JSON-Antwort")
                    break

                batch = payload.get("stellenangebote") or payload.get("jobs") or []
                if not batch:
                    break
                for item in batch:
                    item["_term"] = term
                    raw.append(item)
                if len(batch) < 25:
                    break
                time.sleep(0.08)

    parsed: list[dict] = []
    seen: set[str] = set()

    for item in raw:
        reference = _clean(_first(item, "referenznummer", "refnr", "refNr"))
        if reference and reference in seen:
            continue
        if reference:
            seen.add(reference)

        details = _ba_details(reference, diagnostics)
        company = _clean(
            _first(item, "arbeitgeber", "arbeitgeberName", "firma")
            or _first(details, "arbeitgeber", "arbeitgeberName", "firmenname")
        )
        title = _clean(
            _first(item, "titel", "stellenangebotsTitel", "beruf")
            or _first(details, "stellenangebotsTitel", "titel")
        )
        if not company or not title:
            continue

        external_url = _clean(
            _first(item, "externeUrl", "externeURL", "url")
            or _first(details, "externeUrl", "externeURL", "url")
        )
        fallback_url = (
            f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{reference}"
            if reference else ""
        )
        parsed.append(_job(
            company=company,
            title=title,
            city=_nested(item, "arbeitsort", "ort")
                or _nested(details, "arbeitsort", "ort")
                or _first(item, "arbeitsort", "ort"),
            published=_first(
                item, "veroeffentlichungsdatum", "veroeffentlichtAm",
                "modifikationsTimestamp"
            ),
            description=_first(
                details, "stellenangebotsBeschreibung",
                "stellenbeschreibung", "beschreibung"
            ),
            url=external_url or fallback_url,
            email=_first(details, "email", "eMail", "kontaktEmail")
                or _nested(details, "hauptkontakt", "email"),
            phone=_first(details, "telefon", "telefonnummer", "kontaktTelefon")
                or _nested(details, "hauptkontakt", "telefon"),
            contact=_first(details, "ansprechpartner", "kontaktName")
                or _nested(details, "hauptkontakt", "name"),
            source="Bundesagentur",
            reference=reference,
            term=item.get("_term", ""),
        ))

    diagnostics.append(
        f"Bundesagentur: {len(parsed)} Stellen aus {request_count} Suchanfragen."
    )
    return parsed



# ---------------------------------------------------------------------------
# 2) Adzuna – automatische Jobsuche für Deutschland
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
        diagnostics.append(
            "Adzuna: nicht aktiv – adzuna_app_id oder adzuna_api_key fehlt in den Streamlit-Secrets."
        )
        return []

    jobs: list[dict] = []
    request_count = 0
    page_limit = max(1, min(int(max_pages), 3))

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
                response, error = _get(
                    f"https://api.adzuna.com/v1/api/jobs/de/search/{page}",
                    params=params,
                    timeout=30,
                )
                request_count += 1

                if error:
                    diagnostics.append(f"Adzuna {term} · {city}: {error}")
                    break

                try:
                    payload = response.json() if response else {}
                except ValueError:
                    diagnostics.append(
                        f"Adzuna {term} · {city}: ungültige JSON-Antwort"
                    )
                    break

                batch = payload.get("results") or []
                if not batch:
                    break

                for item in batch:
                    company_data = item.get("company") or {}
                    location_data = item.get("location") or {}
                    category_data = item.get("category") or {}

                    company = _clean(
                        company_data.get("display_name")
                        if isinstance(company_data, dict)
                        else company_data
                    )
                    title = _clean(item.get("title"))

                    if not company or not title:
                        continue

                    description = _clean(item.get("description"))
                    category = _clean(
                        category_data.get("label")
                        if isinstance(category_data, dict)
                        else category_data
                    )
                    if category:
                        description = f"{category}. {description}".strip()

                    jobs.append(_job(
                        company=company,
                        title=title,
                        city=(
                            location_data.get("display_name", city)
                            if isinstance(location_data, dict)
                            else city
                        ),
                        published=item.get("created", ""),
                        description=description,
                        url=item.get("redirect_url", ""),
                        source="Adzuna",
                        reference=str(item.get("id", "")),
                        term=term,
                    ))

                if len(batch) < 50:
                    break
                time.sleep(0.08)

    diagnostics.append(
        f"Adzuna: {len(jobs)} Stellen aus {request_count} Suchanfragen."
    )
    return jobs


# ---------------------------------------------------------------------------
# 2) Google Jobs über SerpApi (optional)
# ---------------------------------------------------------------------------

def scan_google_jobs(
    terms: list[str],
    regions: list[tuple[str, int]],
    days: int,
    serpapi_key: str,
    diagnostics: list[str],
) -> list[dict]:
    if not serpapi_key:
        diagnostics.append("Google Jobs: nicht aktiv – SerpApi-Key fehlt.")
        return []

    jobs: list[dict] = []
    for term in terms:
        for city, _radius in regions:
            params = {
                "engine": "google_jobs",
                "q": f"{term} {city}",
                "hl": "de",
                "gl": "de",
                "api_key": serpapi_key,
            }
            response, error = _get("https://serpapi.com/search.json", params=params, timeout=30)
            if error:
                diagnostics.append(f"Google Jobs {term} · {city}: {error}")
                continue
            try:
                payload = response.json() if response else {}
            except ValueError:
                diagnostics.append(f"Google Jobs {term} · {city}: ungültige JSON-Antwort")
                continue

            for item in payload.get("jobs_results", []):
                company = _clean(item.get("company_name"))
                title = _clean(item.get("title"))
                if not company or not title:
                    continue
                detected = item.get("detected_extensions") or {}
                apply_options = item.get("apply_options") or []
                url = ""
                if apply_options:
                    url = apply_options[0].get("link", "")
                url = url or item.get("share_link", "")
                description = item.get("description", "")
                posted = detected.get("posted_at", "")
                jobs.append(_job(
                    company=company,
                    title=title,
                    city=item.get("location", city),
                    published=posted,
                    description=description,
                    url=url,
                    source="Google Jobs",
                    reference=item.get("job_id", ""),
                    term=term,
                ))
    diagnostics.append(f"Google Jobs: {len(jobs)} Stellen.")
    return jobs


# ---------------------------------------------------------------------------
# 3) Direkte Karriereseiten / ATS / JobPosting JSON-LD
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

        jobs.append(_job(
            company=company,
            title=title,
            city=address.get("addressLocality", ""),
            published=item.get("datePosted", ""),
            description=item.get("description", ""),
            url=item.get("url") or page_url,
            source="Karriereseite",
            reference=item.get("identifier", {}).get("value", "")
                if isinstance(item.get("identifier"), dict) else "",
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
    if host.endswith(".jobs.personio.de"):
        return host.split(".jobs.personio.de")[0]
    return ""


def _scan_greenhouse(url: str, diagnostics: list[str]) -> list[dict]:
    token = _greenhouse_token(url)
    if not token:
        return []
    response, error = _get(
        f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
        params={"content": "true"},
    )
    if error:
        diagnostics.append(f"Greenhouse {token}: {error}")
        return []
    payload = response.json() if response else {}
    result = []
    for item in payload.get("jobs", []):
        company = token.replace("-", " ").title()
        location = (item.get("location") or {}).get("name", "")
        result.append(_job(
            company=company,
            title=item.get("title", ""),
            city=location,
            published=item.get("updated_at", ""),
            description=item.get("content", ""),
            url=item.get("absolute_url", ""),
            source="Greenhouse",
            reference=str(item.get("id", "")),
        ))
    return result


def _scan_lever(url: str, diagnostics: list[str]) -> list[dict]:
    token = _lever_token(url)
    if not token:
        return []
    response, error = _get(
        f"https://api.lever.co/v0/postings/{token}",
        params={"mode": "json"},
    )
    if error:
        diagnostics.append(f"Lever {token}: {error}")
        return []
    payload = response.json() if response else []
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
    feed_urls = [
        f"https://{host}.jobs.personio.de/xml",
        f"https://{host}.jobs.personio.de/xml?language=de",
    ]
    response = None
    for feed in feed_urls:
        response, error = _get(feed)
        if response:
            break
    if not response:
        diagnostics.append(f"Personio {host}: XML-Feed nicht erreichbar.")
        return []

    soup = BeautifulSoup(response.content, "xml")
    result = []
    for position in soup.find_all("position"):
        title = _clean(position.find("name").get_text(" ") if position.find("name") else "")
        company = _clean(position.find("subcompany").get_text(" ") if position.find("subcompany") else "")
        company = company or host.replace("-", " ").title()
        office = _clean(position.find("office").get_text(" ") if position.find("office") else "")
        description = " ".join(
            _clean(node.get_text(" ")) for node in position.find_all(["jobDescription", "description"])
        )
        job_id = _clean(position.find("id").get_text(" ") if position.find("id") else "")
        link = f"https://{host}.jobs.personio.de/job/{job_id}" if job_id else url
        if title:
            result.append(_job(
                company=company,
                title=title,
                city=office,
                description=description,
                url=link,
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
            result.extend(jobs)
            diagnostics.append(f"Greenhouse: {len(jobs)} Stellen aus {url}")
            continue
        if _lever_token(url):
            jobs = _scan_lever(url, diagnostics)
            result.extend(jobs)
            diagnostics.append(f"Lever: {len(jobs)} Stellen aus {url}")
            continue
        if _personio_host(url):
            jobs = _scan_personio(url, diagnostics)
            result.extend(jobs)
            diagnostics.append(f"Personio: {len(jobs)} Stellen aus {url}")
            continue

        response, error = _get(url)
        if error:
            diagnostics.append(f"Karriereseite {url}: {error}")
            continue
        if "html" not in response.headers.get("content-type", "").lower():
            diagnostics.append(f"Karriereseite {url}: kein HTML.")
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        jobs = _jsonld_jobs(soup, response.url)
        result.extend(jobs)
        diagnostics.append(f"Karriereseite: {len(jobs)} JobPosting-Treffer aus {url}")

    return result


def deduplicate(jobs: list[dict]) -> list[dict]:
    output: list[dict] = []
    seen: set[str] = set()
    for job in jobs:
        key = "|".join([
            re.sub(r"\W+", "", job.get("company", "").lower()),
            re.sub(r"\W+", "", job.get("title", "").lower()),
            re.sub(r"\W+", "", job.get("city", "").lower()),
        ])
        if not job.get("company") or not job.get("title") or key in seen:
            continue
        seen.add(key)
        output.append(job)
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
        jobs.extend(scan_adzuna(
            terms,
            regions,
            days,
            max_pages,
            adzuna_app_id,
            adzuna_api_key,
            diagnostics,
        ))

    if "Bundesagentur" in sources:
        jobs.extend(scan_ba(terms, regions, days, max_pages, diagnostics))

    if "Google Jobs" in sources:
        jobs.extend(scan_google_jobs(
            terms, regions, days, serpapi_key, diagnostics
        ))

    if "Karriereseiten" in sources:
        jobs.extend(scan_career_urls(career_urls or [], diagnostics))

    unique_jobs = deduplicate(jobs)
    diagnostics.append(
        f"Gesamt: {len(unique_jobs)} eindeutige Stellen aus {len(sources)} aktivierten Quellen."
    )
    return unique_jobs, diagnostics
