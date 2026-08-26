from __future__ import annotations

import base64
import json
import re
import time
from datetime import date
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BA_API_BASE = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service"
HEADERS = {
    "X-API-Key": "jobboerse-jobsuche",
    "User-Agent": "Mozilla/5.0 (compatible; XING-Daily-Leads/11.0)",
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
    "personalbude", "diepa",
}

PUBLIC_KEYWORDS = {
    "stadtverwaltung", "kreisverwaltung", "landratsamt", "bezirksamt",
    "bundesamt", "landesamt", "ministerium", "polizei", "bundeswehr",
    "agentur für arbeit", "jobcenter", "finanzamt", "justizvollzug",
    "öffentlicher dienst", "tvöd", "tv-l", "kommunalverwaltung",
    "autobahn gmbh des bundes", "gebäudemanagement schleswig-holstein",
    "anstalt öffentlichen rechts", "aör", "aoer",
}

LARGE_COMPANY_KEYWORDS = {
    "deutsche bahn", "db regio", "db infrago", "deutsche post", "dhl",
    "amazon", "siemens", "bosch", "volkswagen", "mercedes-benz", "bmw group",
    "continental", "lidl", "kaufland", "aldi", "rewe group", "edeka zentrale",
    "deutsche telekom", "vodafone", "allianz", "helios kliniken",
    "asklepios", "sana kliniken", "ameos", "korian", "fresenius",
    "thyssenkrupp", "basf", "bayer ag", "rwe ag", "e.on", "ikea", "zalando",
    "deutsche rentenversicherung", "tüv nord", "tüv süd", "tüv rheinland",
    "decathlon", "dm-drogerie", "rossmann", "obi", "hornbach", "toom",
    "vonovia", "deutsche wohnen", "deutsche bank", "commerzbank", "santander",
    "sparkasse", "volksbank", "universitätsklinikum", "uniklinik", "klinikum",
    "fiege", "finanz informatik", "porr", "iu internationale hochschule",
    "diehl aviation", "hamburger hochbahn", "sprinkenhof", "inros lackner",
}

# Signale, die auf einen kleinen, direkt ansprechbaren Arbeitgeber hindeuten.
SMALL_BUSINESS_SIGNALS = {
    "praxis", "physiotherapie", "ergotherapie", "logopädie", "logopaedie",
    "sprachtherapie", "therapiezentrum", "gemeinschaftspraxis", "arztpraxis",
    "zahnarztpraxis", "steuerkanzlei", "steuerberater", "steuerberatung",
    "rechtsanwälte", "rechtsanwaelte", "wirtschaftskanzlei", "notariat",
    "kanzlei", "pflegedienst", "ambulante pflege", "sozialstation",
    "meisterbetrieb", "tischlerei", "schreinerei", "elektrotechnik",
    "haustechnik", "sanitär", "heizung", "klimatechnik", "kältetechnik",
    "metallbau", "maschinenbau", "anlagenbau", "ingenieurbüro", "planungsbüro",
    "architekturbüro", "softwarehaus", "it dienstleister", "logistikdienstleister",
    "spedition", "pharmaunternehmen", "labor", "familienunternehmen",
    "inhabergeführt", "inhabergefuehrt", "familienbetrieb", "mittelstand",
}

# Signale für Konzerne, Ketten oder zentrale Recruiting-Strukturen.
ENTERPRISE_SIGNALS = {
    "konzern", "unternehmensgruppe", "holding", "group", "international",
    "weltweit", "europaweit", "bundesweit", "deutschlandweit", "zentrale",
    "zentraler personalbereich", "karriereportal", "talent acquisition team",
    "shared service", "mehr als 1000 mitarbeiter", "über 1000 mitarbeiter",
    "mehr als 500 mitarbeiter", "über 500 mitarbeiter", "mehr als 50 standorte",
    "über 50 standorte", "mehr als 20 standorte", "über 20 standorte",
    "niederlassungen in ganz deutschland", "filialen in ganz deutschland",
}

CHAIN_NAME_SIGNALS = {
    "gruppe", "group", "holding", "kliniken", "klinikverbund", "gesundheitsgruppe",
    "pflegegruppe", "seniorenzentren", "medical care", "healthcare", "retail",
    "services deutschland", "solutions deutschland", "germany gmbh", "europe gmbh",
}

EMPLOYER_SEGMENT_KEYWORDS = {
    "Therapiepraxis": {
        "physiotherapie", "ergotherapie", "logopaedie", "logopadie",
        "sprachtherapie", "therapiepraxis", "therapiezentrum", "heilmittelpraxis",
    },
    "Steuer und Buchhaltung": {
        "steuerberatung", "steuerkanzlei", "steuerberaterkanzlei",
        "wirtschaftspruefung", "wirtschaftsprufung", "steuerberatungsgesellschaft",
    },
    "Recht und Kanzlei": {
        "rechtsanwaltskanzlei", "rechtsanwaltkanzlei", "wirtschaftskanzlei",
        "rechtsanwaltsgesellschaft", "notariat", "anwaltskanzlei",
    },
    "Pflege und Medizin": {
        "pflegedienst", "ambulante pflege", "arztpraxis", "zahnarztpraxis",
        "medizinisches versorgungszentrum", "mvz",
    },
    "Handwerk und Technik": {
        "elektrotechnik", "haustechnik", "sanitaer", "heizung", "klimatechnik",
        "kaeltetechnik", "metallbau", "tischlerei", "schreinerei", "meisterbetrieb",
    },
    "Industrie und Produktion": {
        "kunststoff", "kunststoffe", "produktion", "fertigung", "maschinenbau",
        "anlagenbau", "werkzeugbau", "metallverarbeitung", "automotive",
    },
    "Bau und Engineering": {
        "ingenieurbuero", "planungsbuero", "architekturbuero", "bauunternehmen",
        "tga planung", "fachplanung",
    },
    "IT und Digitalisierung": {
        "softwarehaus", "it dienstleister", "softwareunternehmen", "digitalagentur",
        "managed service provider",
    },
    "Logistik und Einkauf": {
        "spedition", "logistikdienstleister", "transportlogistik", "lagerlogistik",
    },
    "Pharma und Forschung": {
        "pharmaunternehmen", "pharma", "labor", "biotech", "medizintechnik",
    },
    "Gastronomie und Hotellerie": {
        "hotel", "restaurant", "gasthof", "gasthaus", "resort",
    },
}

THERAPY_NON_PRACTICE_SIGNALS = {
    "klinikum", "krankenhaus", "universitaetsklinikum", "uniklinik", "reha klinik",
    "pflegeheim", "seniorenheim", "personaldienstleister", "zeitarbeit", "staffing",
}

SMALL_ORGANIZATION_SIGNALS = {
    "familienunternehmen", "familienbetrieb", "inhabergefuehrt", "inhabergeführt",
    "inhaber gefuehrt", "inhaber geführt", "mittelstaendisch", "mittelständisch",
    "kleines team", "kleines unternehmen",
}

SEGMENT_KEYWORDS = {
    "Therapiepraxis": {
        "physio", "ergotherapeut", "ergotherapie", "logopä", "logopaed",
        "sprachtherap", "therapie", "praxis", "therapiezentrum",
    },
    "Steuer und Buchhaltung": {
        "steuerfach", "steuerberater", "steuerberatung", "steuerkanzlei",
        "bilanzbuch", "lohnbuch", "finanzbuch", "datev", "accounting",
    },
    "Recht und Kanzlei": {
        "rechtsanw", "jurist", "wirtschaftskanzlei", "notar", "legal", "paralegal",
    },
    "Pflege und Medizin": {
        "ambulante pflege", "pflegedienst", "sozialstation", "pflegefach",
        "altenpflege", "medizinische fachang", "mfa", "arztpraxis", "zahnarzt",
    },
    "Handwerk und Technik": {
        "elektroniker", "elektriker", "mechatron", "anlagenmechaniker", "shk",
        "sanitär", "heizung", "klima", "kälte", "servicetechn", "schweißer",
        "metallbau", "tischler", "schreiner", "dachdecker", "meisterbetrieb",
    },
    "Industrie und Produktion": {
        "produktion", "maschinenbau", "anlagenbau", "industriemechan", "cnc",
        "zerspan", "instandhalt", "qualitäts", "werkzeugmechan", "maschinenbedien",
    },
    "Bau und Engineering": {
        "ingenieurbüro", "ingenieurbuero", "planungsbüro", "bauleiter",
        "projektingenieur", "konstrukteur", "architekt", "tga", "kalkulator", "polier",
    },
    "IT und Digitalisierung": {
        "softwareentwickler", "developer", "devops", "systemadministrator",
        "it support", "softwarehaus", "it dienstleister", "cloud", "data", "cyber",
    },
    "Vertrieb und Marketing": {
        "vertrieb", "sales", "account manager", "business development", "marketing",
        "performance marketing", "e commerce", "customer success",
    },
    "Logistik und Einkauf": {
        "logistik", "lager", "spedition", "disponent", "berufskraft", "fahrer",
        "einkauf", "supply chain", "fachkraft für lagerlogistik",
    },
    "Pharma und Forschung": {
        "pharma", "labor", "chemie", "regulatory", "clinical", "apotheker",
        "pta", "forschung", "wissenschaftler",
    },
    "Personal und Verwaltung": {
        "personalreferent", "recruit", "human resources", "sachbearbeiter",
        "assistenz", "office", "kaufmann", "kauffrau", "verwaltung",
    },
    "Gastronomie und Hotellerie": {
        "gastronomie", "hotel", "restaurant", "koch", "küche", "rezeption", "servicekraft",
    },
    "Direktkunde": set(),
}

_ALL_SEGMENTS = set(SEGMENT_KEYWORDS)

FOCUS_SEGMENTS = {
    "Montagswelle 500 | Testpilot Fachkräfte": {
        "Therapiepraxis", "Pflege und Medizin", "Handwerk und Technik",
        "Industrie und Produktion", "Bau und Engineering", "Steuer und Buchhaltung",
        "Logistik und Einkauf",
    },
    "Testpilot Therapie 500": {"Therapiepraxis"},
    "Breite Massenkampagne": _ALL_SEGMENTS,
    "Alle Direktkunden": _ALL_SEGMENTS,
    "Alle kleinen Direktkunden": _ALL_SEGMENTS,
    "Therapiepraxen": {"Therapiepraxis"},
    "Steuerkanzleien": {"Steuer und Buchhaltung"},
    "Recht und Kanzleien": {"Recht und Kanzlei"},
    "Ambulante Pflege": {"Pflege und Medizin"},
    "Arztpraxen": {"Pflege und Medizin"},
    "Handwerk und Technik": {"Handwerk und Technik"},
    "Industrie und Produktion": {"Industrie und Produktion"},
    "Kleine Ingenieurbüros": {"Bau und Engineering"},
    "Bau und Engineering": {"Bau und Engineering"},
    "Kleine IT Unternehmen": {"IT und Digitalisierung"},
    "IT und Digitalisierung": {"IT und Digitalisierung"},
    "Chancenmix Architektur Ingenieurwesen Steuer IT": {
        "Bau und Engineering", "Steuer und Buchhaltung", "IT und Digitalisierung"
    },
    "Architektur und Planung": {"Bau und Engineering"},
    "Vertrieb und Marketing": {"Vertrieb und Marketing"},
    "Logistik und Einkauf": {"Logistik und Einkauf"},
    "Pharma und Forschung": {"Pharma und Forschung"},
    "Personal und Verwaltung": {"Personal und Verwaltung"},
    "Diamanten Radar | kleine Direktkunden": _ALL_SEGMENTS,
}

TARGET_KEYWORDS = {
    "physio": 24, "ergotherapeut": 24, "logopä": 24, "therapie": 18,
    "pflegefach": 22, "ambulante pflege": 24, "medizinische fachangestellte": 18,
    "steuerfach": 23, "bilanzbuchhalter": 20, "lohnbuchhalter": 19, "controller": 16,
    "rechtsanwalt": 18, "rechtsanwaltsfach": 20, "jurist": 17, "legal": 14,
    "elektriker": 18, "elektroniker": 18, "anlagenmechaniker": 18, "mechatroniker": 17,
    "servicetechniker": 16, "schweißer": 16, "zerspan": 17, "cnc": 17,
    "industriemechaniker": 17, "produktion": 12, "maschinenbediener": 14,
    "bauleiter": 18, "projektleiter": 16, "konstrukteur": 16, "ingenieur": 15,
    "kalkulator": 17, "tga": 16, "architekt": 14,
    "softwareentwickler": 17, "developer": 15, "devops": 16, "systemadministrator": 17,
    "it support": 14, "data engineer": 15, "cloud": 14, "cyber security": 16,
    "vertrieb": 15, "sales": 15, "account manager": 16, "business development": 15,
    "marketing": 13, "performance marketing": 16, "customer success": 14,
    "logistik": 14, "lager": 13, "disponent": 16, "berufskraftfahrer": 16,
    "spedition": 15, "einkäufer": 15, "supply chain": 14,
    "pharma": 16, "laborant": 17, "chemielaborant": 17, "regulatory": 18,
    "clinical research": 17, "apotheker": 17, "pta": 16,
    "personalreferent": 15, "recruiter": 15, "sachbearbeiter": 11,
    "assistenz": 11, "industriekaufmann": 12, "büromanagement": 11,
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
        status_forcelist=(500, 502, 503, 504),
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
    text = str(value)
    if "<" in text and ">" in text:
        text = BeautifulSoup(text, "html.parser").get_text(" ")
    return re.sub(r"\s+", " ", text).strip()


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
    discovery_kind: str = "Vakanz",
    need_signal: str = "",
    website: str = "",
    career_url: str = "",
    evidence: str = "",
    diamond_score: int = 0,
    diamond_reason: str = "",
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
        "discovery_kind": _clean(discovery_kind) or "Vakanz",
        "need_signal": _clean(need_signal),
        "website": _clean(website),
        "career_url": _clean(career_url),
        "evidence": _clean(evidence),
        "diamond_score": int(diamond_score or 0),
        "diamond_reason": _clean(diamond_reason),
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
    fetch_details: bool = False,
    detail_limit: int = 40,
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
    detail_limit = max(0, int(detail_limit))
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
        if fetch_details and reference and detail_calls < detail_limit:
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
        f"{detail_calls} Detailseiten geprüft. Schnellmodus: {'aus' if fetch_details else 'an'}."
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
                    low = error.lower()
                    if "429" in low or "quota" in low or "limit" in low:
                        diagnostics.append("Google Jobs: SerpApi Limit erkannt. Quelle für diesen Lauf gestoppt, andere Quellen laufen weiter.")
                        return jobs
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



RADAR_CAREER_WORDS = (
    "karriere", "career", "jobs", "stellen", "stellenangebote", "bewerbung",
    "arbeiten bei", "werde teil", "verstärkung", "verstaerkung",
)
RADAR_ATS_HOSTS = (
    "jobs.personio.de", "greenhouse.io", "lever.co", "workdayjobs.com",
    "smartrecruiters.com", "join.com", "recruitee.com", "onlyfy.io",
)
RADAR_BLOCKED_WEBSITES = (
    "google.com", "google.de", "facebook.com", "instagram.com", "linkedin.com",
    "xing.com", "11880.com", "gelbeseiten.de", "dasoertliche.de", "cylex.de",
)


def _radar_website_from_local(item: dict) -> str:
    direct = _clean(item.get("website"))
    if direct:
        return direct
    links = item.get("links") or {}
    if isinstance(links, dict):
        direct = _clean(links.get("website") or links.get("webseite"))
        if direct:
            return direct
    return ""


def _radar_valid_website(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url if "://" in url else "https://" + url)
    host = (parsed.hostname or "").lower().lstrip("www.")
    return bool(host) and not any(host == blocked or host.endswith("." + blocked) for blocked in RADAR_BLOCKED_WEBSITES)


def _radar_career_links(base_url: str, html_text: str, limit: int = 5) -> list[str]:
    try:
        soup = BeautifulSoup(html_text or "", "html.parser")
    except Exception:
        return []
    scored: list[tuple[int, str]] = []
    seen: set[str] = set()
    base_host = (urlparse(base_url).hostname or "").lower().lstrip("www.")
    for anchor in soup.find_all("a", href=True):
        href = urljoin(base_url, anchor.get("href", "")).split("#", 1)[0]
        if not href.startswith("http") or href in seen:
            continue
        host = (urlparse(href).hostname or "").lower().lstrip("www.")
        label = _norm(f"{anchor.get_text(' ')} {href}")
        same_site = bool(base_host and (host == base_host or host.endswith("." + base_host)))
        ats = any(host.endswith(ats_host) for ats_host in RADAR_ATS_HOSTS)
        career = any(_norm(word) in label for word in RADAR_CAREER_WORDS)
        if not (career or ats):
            continue
        score = (100 if career else 0) + (35 if ats else 0) + (10 if same_site else 0)
        seen.add(href)
        scored.append((score, href))
    scored.sort(reverse=True)
    return [href for _, href in scored[:limit]]


def _radar_page_signal(text: str) -> tuple[str, int]:
    normal = _norm(text)
    strong = [word for word in ("wir suchen", "stellenangebote", "offene stellen", "jetzt bewerben", "bewerben sie sich", "komm ins team") if _norm(word) in normal]
    if strong:
        return "Recruiting Hinweis auf eigener Website", min(16, 8 + len(strong) * 2)
    if any(_norm(word) in normal for word in RADAR_CAREER_WORDS):
        return "Karriereseite oder Recruiting Bereich vorhanden", 7
    return "Kein öffentlicher Personalbedarf gefunden", 0


def _radar_diamond_score(
    *,
    company: str,
    website: str,
    phone: str,
    career_url: str,
    hiring_points: int,
    segment: str,
    reviews: int = 0,
) -> tuple[int, str]:
    score = 34
    reasons: list[str] = []
    company_norm = _norm(company)
    if segment and segment != "Direktkunde":
        score += 14
        reasons.append(f"klares Segment {segment}")
    if any(_norm(token) in company_norm for token in SMALL_BUSINESS_SIGNALS):
        score += 12
        reasons.append("lokales Direktkunden Signal")
    if website:
        score += 10
        reasons.append("eigene Website")
    if phone:
        score += 6
        reasons.append("direkte Telefonnummer")
    if career_url:
        score += 10
        reasons.append("eigener Karrierebereich")
    if hiring_points:
        score += hiring_points
        reasons.append("Recruiting Signal")
    # Wenige Google Bewertungen sind nur ein schwaches Indiz für lokale Größe.
    if 0 < reviews <= 80:
        score += 4
        reasons.append("kleiner lokaler Footprint")
    if any(_norm(token) in company_norm for token in CHAIN_NAME_SIGNALS):
        score -= 25
    if _hit(company, LARGE_COMPANY_KEYWORDS):
        score -= 60
    score = max(0, min(100, score))
    return score, ", ".join(reasons[:5]) or "lokaler Firmenfund"


def _probe_radar_company(
    *,
    company: str,
    city: str,
    term: str,
    website: str,
    phone: str,
    address: str,
    reviews: int,
    reference: str,
    diagnostics: list[str],
) -> list[dict]:
    segment = _segment_for_employer(company, f"{address} {term}")[0]
    career_url = ""
    need_signal = "Kein öffentlicher Personalbedarf gefunden"
    hiring_points = 0
    evidence_parts = [part for part in (address, phone) if part]
    discovered_jobs: list[dict] = []
    page_text = ""

    if website and _radar_valid_website(website):
        if "://" not in website:
            website = "https://" + website
        response, error = _get(website, timeout=18)
        if response and not error and "html" in response.headers.get("content-type", "").lower():
            website = response.url
            soup = BeautifulSoup(response.text, "html.parser")
            page_text = _clean(soup.get_text(" "))[:12000]
            direct_jobs = _jsonld_jobs(soup, response.url)
            for job in direct_jobs:
                job["term"] = term
                job["source"] = "Google Firmenradar | Karriereseite"
                job["discovery_kind"] = "Karrieresignal"
                job["need_signal"] = "Konkrete Vakanz auf eigener Website"
                job["website"] = website
                job["career_url"] = response.url
                job["evidence"] = f"Eigene Website mit strukturierter Stellenausschreibung. {address}".strip()
            discovered_jobs.extend(direct_jobs)

            career_links = _radar_career_links(response.url, response.text)
            if career_links:
                career_url = career_links[0]
            for candidate in career_links[:3]:
                if discovered_jobs:
                    break
                candidate_response, candidate_error = _get(candidate, timeout=16)
                if candidate_error or not candidate_response:
                    continue
                ctype = candidate_response.headers.get("content-type", "").lower()
                if "html" not in ctype and not any(host in candidate_response.url for host in RADAR_ATS_HOSTS):
                    continue
                try:
                    csoup = BeautifulSoup(candidate_response.text, "html.parser")
                except Exception:
                    continue
                ctext = _clean(csoup.get_text(" "))[:15000]
                page_text += " " + ctext
                jobs_here = _jsonld_jobs(csoup, candidate_response.url)
                for job in jobs_here:
                    job["term"] = term
                    job["source"] = "Google Firmenradar | Karriereseite"
                    job["discovery_kind"] = "Karrieresignal"
                    job["need_signal"] = "Konkrete Vakanz auf eigener Website"
                    job["website"] = website
                    job["career_url"] = candidate_response.url
                    job["evidence"] = f"Karriereseite mit strukturierter Stellenausschreibung. {address}".strip()
                discovered_jobs.extend(jobs_here)
                if not career_url:
                    career_url = candidate_response.url

            need_signal, hiring_points = _radar_page_signal(page_text)
            if career_url and need_signal == "Kein öffentlicher Personalbedarf gefunden":
                need_signal = "Karriereseite vorhanden, aktuelle Vakanz noch nicht belegt"
                hiring_points = max(hiring_points, 6)
        elif error:
            diagnostics.append(f"Firmenradar Website {company}: {error}")

    diamond_score, diamond_reason = _radar_diamond_score(
        company=company,
        website=website,
        phone=phone,
        career_url=career_url,
        hiring_points=hiring_points,
        segment=segment,
        reviews=reviews,
    )

    for job in discovered_jobs:
        job["diamond_score"] = max(int(job.get("diamond_score", 0) or 0), diamond_score)
        job["diamond_reason"] = diamond_reason
        job["lead_segment"] = segment

    if discovered_jobs:
        return discovered_jobs

    evidence_parts.append(need_signal)
    return [_job(
        company=company,
        title="",
        city=city,
        description=". ".join(part for part in [address, need_signal, page_text[:1200]] if part),
        url=website or career_url,
        phone=phone,
        source="Google Firmenradar",
        reference=reference,
        term=term,
        discovery_kind="Firmenradar",
        need_signal=need_signal,
        website=website,
        career_url=career_url,
        evidence=". ".join(evidence_parts)[:1600],
        diamond_score=diamond_score,
        diamond_reason=diamond_reason,
    )]


def scan_google_company_radar(
    terms: list[str],
    regions: list[tuple[str, int]],
    serpapi_key: str,
    diagnostics: list[str],
    *,
    max_pages: int = 1,
    probe_limit_per_query: int = 8,
) -> list[dict]:
    """Findet kleine Unternehmen unabhängig von veröffentlichten Stellen.

    Google Maps dient als Firmenindex. Danach werden vorhandene Firmenwebsites
    leichtgewichtig auf Karrierebereiche und strukturierte JobPosting Daten geprüft.
    Ein Radar Fund ohne belegte Vakanz bleibt ausdrücklich ein Potenzialkunde und
    wird später niemals als aktive Personalsuche formuliert.
    """
    if not serpapi_key:
        diagnostics.append("Google Firmenradar: nicht aktiv, SerpApi Key fehlt.")
        return []

    output: list[dict] = []
    request_count = 0
    candidate_count = 0
    page_limit = max(1, min(int(max_pages), 5))
    probe_limit = max(0, min(int(probe_limit_per_query), 20))
    seen_companies: set[str] = set()

    for term in terms:
        business_queries = _radar_business_queries(term)
        for city, radius in regions:
            for business_query in business_queries[:2]:
                for page in range(page_limit):
                    # Google Maps liefert bei sehr großen Kartenradien nur die relevantesten
                    # Treffer und nicht alle Betriebe im Kreis. Deshalb wird der Ortsname
                    # zusätzlich in die Suchanfrage geschrieben. So werden lokale und kleinere
                    # Anbieter deutlich zuverlässiger sichtbar.
                    params = {
                        "engine": "google_maps",
                        "type": "search",
                        "q": f"{business_query} {city}",
                        "location": f"{city}, Germany",
                        "m": max(5000, min(int(radius) * 1000, 150000)),
                        "hl": "de",
                        "start": page * 20,
                        "api_key": serpapi_key,
                    }
                    response, error = _get("https://serpapi.com/search.json", params=params, timeout=35)
                    request_count += 1
                    if error or not response:
                        message = error or "keine Antwort"
                        diagnostics.append(f"Google Firmenradar {business_query} · {city}: {message}")
                        low = message.lower()
                        if "429" in low or "quota" in low or "limit" in low:
                            diagnostics.append("Google Firmenradar: SerpApi Limit erkannt. Radar für diesen Lauf gestoppt, bereits gefundene Firmen bleiben erhalten.")
                            return output
                        break
                    try:
                        payload = response.json()
                    except ValueError:
                        diagnostics.append(f"Google Firmenradar {business_query} · {city}: ungültige JSON Antwort")
                        break
                    if payload.get("error"):
                        diagnostics.append(f"Google Firmenradar {business_query} · {city}: {payload.get('error')}")
                        break
                    local_results = payload.get("local_results") or []
                    if isinstance(local_results, dict):
                        local_results = local_results.get("places") or local_results.get("results") or []
                    if not isinstance(local_results, list) or not local_results:
                        break
                    candidate_count += len(local_results)
                    for item_index, item in enumerate(local_results):
                        if not isinstance(item, dict):
                            continue
                        company = _clean(item.get("title") or item.get("name"))
                        if not company:
                            continue
                        company_key = _company_key(company)
                        if not company_key or company_key in seen_companies:
                            continue
                        if _hit(company, STAFFING_KEYWORDS) or _hit(company, PUBLIC_KEYWORDS) or _hit(company, LARGE_COMPANY_KEYWORDS):
                            continue
                        seen_companies.add(company_key)
                        address = _clean(item.get("address"))
                        phone = _clean(item.get("phone"))
                        website = _radar_website_from_local(item)
                        reviews_raw = item.get("reviews") or 0
                        try:
                            reviews = int(str(reviews_raw).replace(".", "").replace(",", ""))
                        except ValueError:
                            reviews = 0
                        reference = _clean(item.get("data_id") or item.get("place_id") or item.get("data_cid") or f"{company}:{city}")

                        # Die ersten Treffer werden sofort auf Karrieresignale geprüft.
                        # Weitere Firmen werden trotzdem gespeichert und in Schritt 2 tief recherchiert.
                        if item_index < probe_limit and website:
                            records = _probe_radar_company(
                                company=company,
                                city=city,
                                term=term,
                                website=website,
                                phone=phone,
                                address=address,
                                reviews=reviews,
                                reference=reference,
                                diagnostics=diagnostics,
                            )
                        else:
                            segment = _segment_for_employer(company, f"{address} {business_query}")[0]
                            diamond_score, diamond_reason = _radar_diamond_score(
                                company=company,
                                website=website,
                                phone=phone,
                                career_url="",
                                hiring_points=0,
                                segment=segment,
                                reviews=reviews,
                            )
                            records = [_job(
                                company=company,
                                title="",
                                city=city,
                                description=f"Google Maps Firmenfund. {address}".strip(),
                                url=website,
                                phone=phone,
                                source="Google Firmenradar",
                                reference=reference,
                                term=term,
                                discovery_kind="Firmenradar",
                                need_signal="Website und Karrierebedarf in Schritt 2 prüfen",
                                website=website,
                                evidence=f"Google Maps Firmenfund in {city}. {address}".strip(),
                                diamond_score=diamond_score,
                                diamond_reason=diamond_reason,
                            )]
                        output.extend(records)
                    if len(local_results) < 20:
                        break
                    time.sleep(0.08)

    diagnostics.append(
        f"Google Firmenradar: {len(output)} verwertbare Firmen oder Karrieresignale aus "
        f"{candidate_count} lokalen Treffern und {request_count} SerpApi Suchanfragen."
    )
    return output


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
        if not job.get("company"):
            continue
        if not job.get("title") and job.get("discovery_kind") != "Firmenradar":
            continue
        if key not in merged:
            merged[key] = dict(job)
            merged[key]["sources"] = [job.get("source", "")] if job.get("source") else []
            continue
        current = merged[key]
        current["sources"] = sorted(set(current.get("sources", []) + ([job.get("source", "")] if job.get("source") else [])))
        for field in ("description", "email", "phone", "contact", "external_url", "job_link", "published", "website", "career_url", "evidence", "need_signal", "diamond_reason"):
            if not current.get(field) and job.get(field):
                current[field] = job[field]
        if len(job.get("description", "")) > len(current.get("description", "")):
            current["description"] = job["description"]
        current["diamond_score"] = max(int(current.get("diamond_score", 0) or 0), int(job.get("diamond_score", 0) or 0))
        if current.get("discovery_kind") == "Firmenradar" and job.get("discovery_kind") == "Karrieresignal":
            current["discovery_kind"] = "Karrieresignal"
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



def _segment_for_employer(company: str, description: str) -> tuple[str, list[str]]:
    """Klassifiziert den Arbeitgeber, nicht die gesuchte Rolle."""
    company_normal = _norm(company)
    intro_normal = _norm(description[:1800])
    normal = f"{company_normal} {intro_normal}"
    best_segment = "Direktkunde"
    best_hits: list[str] = []
    for segment, keywords in EMPLOYER_SEGMENT_KEYWORDS.items():
        hits = [keyword for keyword in keywords if _norm(keyword) in normal]
        if len(hits) > len(best_hits):
            best_segment = segment
            best_hits = hits
    if best_segment == "Therapiepraxis" and any(_norm(x) in normal for x in THERAPY_NON_PRACTICE_SIGNALS):
        return "Pflege und Medizin", ["Klinik oder Einrichtung"]
    return best_segment, best_hits[:4]


def _number_size_signal(text: str) -> int:
    """Liest Mitarbeiterangaben einschließlich 5.000 oder 22,000 aus Texten."""
    normal = _norm(text)
    pattern = (
        r"(?:ueber|mehr als|rund|ca\.?|circa)?\s*"
        r"(\d{1,3}(?:[\. ,]\d{3})+|\d{2,6})\s*"
        r"(?:mitarbeiter|mitarbeitende|beschaeftigte|kollegen)"
    )
    values: list[int] = []
    for match in re.findall(pattern, normal):
        digits = re.sub(r"\D", "", str(match))
        if digits:
            try:
                values.append(int(digits))
            except ValueError:
                pass
    return max(values or [0])


def _number_location_signal(text: str) -> int:
    normal = _norm(text)
    pattern = (
        r"(?:ueber|mehr als|rund|ca\.?|circa)?\s*"
        r"(\d{1,3}(?:[\. ,]\d{3})+|\d{1,5})\s*"
        r"(?:standorte|niederlassungen|filialen)"
    )
    values: list[int] = []
    for match in re.findall(pattern, normal):
        digits = re.sub(r"\D", "", str(match))
        if digits:
            try:
                values.append(int(digits))
            except ValueError:
                pass
    return max(values or [0])


def _segment_for_term(term: str) -> str:
    value = _norm(term)
    if any(token in value for token in ("physio", "ergo", "logo", "therapie")):
        return "Therapiepraxis"
    if any(token in value for token in ("pflege", "mfa", "medizin", "arzt", "zahn")):
        return "Pflege und Medizin"
    if any(token in value for token in ("steuer", "bilanzbuch", "lohnbuch", "finanzbuch")):
        return "Steuer und Buchhaltung"
    if any(token in value for token in ("rechtsanw", "notar", "legal", "jurist")):
        return "Recht und Kanzlei"
    if any(token in value for token in ("elektr", "shk", "sanitaer", "heizung", "kaelte", "klima", "dach", "tischler", "schreiner", "metallbau")):
        return "Handwerk und Technik"
    if any(token in value for token in ("maschinenbau", "anlagenbau", "industriemechan", "zerspan", "cnc", "produktion", "mechatron")):
        return "Industrie und Produktion"
    if any(token in value for token in ("software", "devops", "systemadmin", "it admin", "fachinformat", "sap", "it dienst")):
        return "IT und Digitalisierung"
    if any(token in value for token in ("architekt", "bauleiter", "ingenieur", "tga", "bim", "konstrukteur", "bauzeichner", "planung")):
        return "Bau und Engineering"
    if any(token in value for token in ("logistik", "lager", "spedition", "disponent", "fahrer")):
        return "Logistik und Einkauf"
    if any(token in value for token in ("pharma", "labor", "biotech", "medizintechnik")):
        return "Pharma und Forschung"
    if any(token in value for token in ("vertrieb", "sales", "marketing")):
        return "Vertrieb und Marketing"
    return ""


def _radar_business_queries(term: str) -> list[str]:
    """Übersetzt Stellenbegriffe in lokale Unternehmenssuchen.

    Google Maps liefert bessere kleine Direktkunden, wenn nach Betriebstyp statt
    nach einer Stellenbezeichnung gesucht wird. Pro Suchbegriff werden höchstens
    zwei eng verwandte Unternehmensbegriffe verwendet.
    """
    value = _norm(term)
    rules = [
        (("physio", "physiotherapie"), ["Physiotherapie Praxis", "Physiotherapie Zentrum"]),
        (("ergo", "ergotherapie"), ["Ergotherapie Praxis"]),
        (("logo", "sprachtherap"), ["Logopädie Praxis", "Sprachtherapie Praxis"]),
        (("pflege",), ["Ambulanter Pflegedienst", "Pflegedienst"]),
        (("mfa", "medizinische fachang", "arzt"), ["Arztpraxis", "Gemeinschaftspraxis"]),
        (("zahn",), ["Zahnarztpraxis"]),
        (("steuer", "bilanzbuch", "lohnbuch", "finanzbuch"), ["Steuerberater", "Steuerkanzlei"]),
        (("rechtsanw", "legal", "jurist"), ["Rechtsanwaltskanzlei"]),
        (("notar",), ["Notariat"]),
        (("elektr",), ["Elektrotechnik", "Elektroinstallateur"]),
        (("shk", "anlagenmechaniker", "sanitaer", "heizung"), ["Sanitär Heizung Klima", "SHK Betrieb"]),
        (("kaelte", "klima"), ["Kältetechnik", "Klimatechnik"]),
        (("dach",), ["Dachdecker"]),
        (("tischler", "schreiner"), ["Tischlerei", "Schreinerei"]),
        (("metallbau", "schweiss"), ["Metallbau"]),
        (("mechatron", "industriemechan", "zerspan", "cnc", "produktion"), ["Maschinenbau", "Metallverarbeitung"]),
        (("maschinenbau", "anlagenbau"), ["Maschinenbau", "Anlagenbau"]),
        (("bauleiter", "bauunternehmen", "polier"), ["Bauunternehmen"]),
        (("tga", "versorgungsingenieur"), ["TGA Planungsbüro", "Ingenieurbüro Gebäudetechnik"]),
        (("ingenieur", "konstrukteur"), ["Ingenieurbüro", "Planungsbüro"]),
        (("architekt", "bim", "bauzeichner"), ["Architekturbüro", "Planungsbüro"]),
        (("software", "devops", "systemadmin", "fachinformat", "it "), ["IT Dienstleister", "Softwareunternehmen"]),
        (("spedition", "logistik", "lager", "disponent", "fahrer"), ["Spedition", "Logistikunternehmen"]),
        (("pharma", "labor", "biotech", "medizintechnik"), ["Medizintechnik", "Labor"]),
        (("hotel", "koch", "restaurant", "gastronomie"), ["Hotel", "Restaurant"]),
    ]
    for tokens, queries in rules:
        if any(token in value for token in tokens):
            return queries[:2]
    # Für unbekannte Begriffe bleibt die Suche bewusst eng am Original.
    cleaned = _clean(term)
    return [cleaned] if cleaned else []

def _term_matches_job(term: str, title: str, company: str = "", description: str = "") -> bool:
    """Verhindert breite API Treffer wie Software Architect bei Architekt."""
    term_norm = _norm(term)
    title_norm = _norm(title)
    company_norm = _norm(company)
    text = f"{title_norm} {company_norm}"

    if "architekt" in term_norm and "landschaft" not in term_norm and "innen" not in term_norm:
        if any(token in title_norm for token in (
            "software architekt", "software-architekt", "enterprise architect",
            "solution architect", "cloud architect", "it architect", "it/ot",
            "systemarchitektur", "domain architect",
        )):
            return False
        if "duales studium" in title_norm or "student" in title_norm:
            return False
        return "architekt" in title_norm or "architekturburo" in company_norm

    rules = [
        (("steuerfachang", "steuerfachwirt"), ("steuerfach",)),
        (("softwareentwick",), ("softwareentwick", "software developer")),
        (("bauleiter",), ("bauleiter", "bauleitung")),
        (("projektingenieur",), ("projektingenieur",)),
        (("bilanzbuch",), ("bilanzbuch",)),
        (("systemadministrator",), ("systemadministrator", "system admin")),
        (("tga planer",), ("tga planer", "tga-planer", "tga fachplaner", "fachplaner tga")),
        (("elektroingenieur",), ("elektroingenieur", "ingenieur elektrotechnik")),
        (("devops",), ("devops",)),
        (("bim manager",), ("bim manager", "bim koordinator")),
        (("konstrukteur",), ("konstrukteur",)),
        (("lohnbuch",), ("lohnbuch", "payroll")),
        (("it administrator",), ("it administrator", "it-administrator")),
        (("bauzeichner",), ("bauzeichner",)),
        (("versorgungsingenieur",), ("versorgungsingenieur", "ingenieur versorgungstechnik")),
        (("finanzbuch",), ("finanzbuch",)),
        (("fachinformat",), ("fachinformat",)),
        (("projektleiter architektur",), ("projektleiter architektur", "projektleitung architektur")),
        (("landschaftsarchitekt",), ("landschaftsarchitekt",)),
        (("steuerberater",), ("steuerberater",)),
        (("sap berater",), ("sap berater", "sap consultant")),
        (("innenarchitekt",), ("innenarchitekt",)),
    ]
    for term_tokens, title_tokens in rules:
        if any(token in term_norm for token in term_tokens):
            return any(token in title_norm for token in title_tokens)

    important = [token for token in term_norm.split() if len(token) >= 4]
    return bool(important and any(token in text for token in important))


def _small_business_profile(
    *,
    company: str,
    title: str,
    description: str,
    term: str,
    company_data: dict,
    focus: str,
) -> dict[str, Any]:
    combined = " ".join([company, title, description])
    normal = _norm(combined)
    company_normal = _norm(company)
    segment, segment_hits = _segment_for_employer(company, description)
    job_count = int(company_data.get("job_count", 1) or 1)
    distinct_titles = int(company_data.get("distinct_titles", 1) or 1)
    location_count = int(company_data.get("location_count", 1) or 1)
    broad_mode = focus in {"Breite Massenkampagne", "Alle Direktkunden", "Alle kleinen Direktkunden", "Diamanten Radar | kleine Direktkunden"}
    strict_wave = focus == "Montagswelle 500 | Testpilot Fachkräfte"
    radar_mode = not _clean(title)

    small_hits = [keyword for keyword in SMALL_BUSINESS_SIGNALS if _norm(keyword) in company_normal]
    small_hits += [keyword for keyword in SMALL_ORGANIZATION_SIGNALS if _norm(keyword) in _norm(description[:1800])]
    small_hits = list(dict.fromkeys(small_hits))
    enterprise_hits = [keyword for keyword in ENTERPRISE_SIGNALS if _norm(keyword) in normal]
    chain_hits = [keyword for keyword in CHAIN_NAME_SIGNALS if _norm(keyword) in company_normal]
    employee_count = _number_size_signal(description)
    described_locations = _number_location_signal(description)
    if described_locations > location_count:
        location_count = described_locations

    reasons: list[str] = []
    score = 50 if broad_mode else 42
    if small_hits:
        score += min(24, 10 + len(small_hits) * 3)
        reasons.append("Direktkunden Signal: " + ", ".join(small_hits[:3]))
    if segment != "Direktkunde":
        score += 10
        reasons.append("Segment: " + segment)

    if radar_mode:
        reasons.append("Firmenradar ohne unterstellte Vakanz")
    elif job_count <= 3:
        score += 18
        reasons.append(f"{job_count} konkrete Stelle" + ("n" if job_count != 1 else ""))
    elif job_count <= 8:
        score += 8
        reasons.append(f"{job_count} offene Stellen")
    elif job_count <= 15 and broad_mode:
        score += 1
    elif job_count <= 25 and broad_mode:
        score -= 10
    else:
        score -= 50

    if location_count <= 1:
        score += 10
        reasons.append("ein Standort")
    elif location_count <= 3:
        score += 3
    elif location_count <= 6 and broad_mode:
        score -= 5
    elif location_count <= 12 and broad_mode:
        score -= 15
    else:
        score -= 45

    if radar_mode:
        pass
    elif distinct_titles == 1:
        score += 7
    elif distinct_titles <= 4:
        score += 3
    elif distinct_titles <= 10 and broad_mode:
        score -= 5
    else:
        score -= 30

    if employee_count:
        if employee_count <= 50:
            score += 12
            reasons.append(f"ca. {employee_count} Mitarbeitende")
        elif employee_count <= 250:
            score += 4
        elif employee_count <= 1000 and broad_mode:
            score -= 4
        elif employee_count <= 3000 and broad_mode:
            score -= 18
        else:
            score -= 55
            enterprise_hits.append(f"{employee_count} Mitarbeitende")

    if enterprise_hits:
        score -= min(55, 14 + len(enterprise_hits) * 9)
    if chain_hits:
        score -= min(35, 8 + len(chain_hits) * 7)

    allowed_segments = FOCUS_SEGMENTS.get(focus, FOCUS_SEGMENTS["Breite Massenkampagne"])
    focus_match = segment in allowed_segments
    if not broad_mode and not focus_match:
        score -= 45

    hard_reasons: list[str] = []
    max_jobs = 8 if strict_wave else (30 if broad_mode else 8)
    max_locations = 4 if strict_wave else (12 if broad_mode else 3)
    max_titles = 6 if strict_wave else (15 if broad_mode else 6)
    max_employees = 350 if strict_wave else (3000 if broad_mode else 500)
    if not radar_mode and job_count > max_jobs:
        hard_reasons.append(f"{job_count} Stellen")
    if location_count > max_locations:
        hard_reasons.append(f"{location_count} Standorte")
    if not radar_mode and distinct_titles > max_titles:
        hard_reasons.append(f"{distinct_titles} unterschiedliche Rollen")
    if employee_count > max_employees:
        hard_reasons.append(f"{employee_count} Mitarbeitende")
    if strict_wave and (enterprise_hits or chain_hits):
        hard_reasons.append("Konzern oder Kettenstruktur")
    elif not broad_mode and (len(enterprise_hits) >= 2 or chain_hits):
        hard_reasons.append("Konzern oder Kettenstruktur")
    if broad_mode and len(enterprise_hits) >= 4:
        hard_reasons.append("deutliche Konzernstruktur")
    if not broad_mode and not focus_match:
        hard_reasons.append("passt nicht zur gewählten Kampagne")
    if strict_wave and segment == "Direktkunde":
        hard_reasons.append("Arbeitgebersegment nicht belastbar")

    score = max(0, min(100, score))
    positive_small_evidence = bool(
        small_hits
        or (employee_count and employee_count <= 50)
        or segment in {"Therapiepraxis", "Steuer und Buchhaltung", "Recht und Kanzlei"}
    )
    if hard_reasons or score < (25 if broad_mode else 35):
        size_fit = "Groß oder unpassend"
    elif score >= 70 and positive_small_evidence:
        size_fit = "Klein"
    else:
        size_fit = "Mittel"
        if not positive_small_evidence and score > 64:
            score = 64

    return {
        "segment": segment,
        "segment_hits": segment_hits,
        "small_business_score": score,
        "size_fit": size_fit,
        "size_reason": "; ".join(reasons[:5] + (["Abzug: " + ", ".join(hard_reasons)] if hard_reasons else [])),
        "hard_exclude": bool(hard_reasons),
        "focus_match": focus_match,
    }


def score_and_filter(jobs: list[dict], diagnostics: list[str], focus: str = "Alle kleinen Direktkunden") -> list[dict]:
    unique = deduplicate(jobs)
    stats = _company_stats(unique)
    output: list[dict] = []
    excluded = {
        "staffing": 0,
        "public": 0,
        "large_name": 0,
        "oversize": 0,
        "focus": 0,
        "low_score": 0,
        "term_mismatch": 0,
    }

    for job in unique:
        company = job.get("company", "")
        title = job.get("title", "")
        description = job.get("description", "")
        term = job.get("term", "")
        combined = " ".join([company, title, description, term])

        radar_mode = _clean(job.get("discovery_kind", "")) == "Firmenradar"
        if not radar_mode and not _term_matches_job(term, title, company, description):
            excluded["term_mismatch"] += 1
            continue
        company_low = _norm(company)
        description_low = _norm(description[:1200])
        if ("personal" in company_low or "vermittlung" in company_low) and "unser kunde" in description_low:
            excluded["staffing"] += 1
            continue
        if _hit(combined, STAFFING_KEYWORDS):
            excluded["staffing"] += 1
            continue
        if _hit(company + " " + title + " " + description[:1600], PUBLIC_KEYWORDS):
            excluded["public"] += 1
            continue
        if _hit(company, LARGE_COMPANY_KEYWORDS):
            excluded["large_name"] += 1
            continue

        company_data = stats.get(_company_key(company), {})
        profile = _small_business_profile(
            company=company,
            title=title,
            description=description,
            term=term,
            company_data=company_data,
            focus=focus,
        )
        if profile["hard_exclude"]:
            if not profile["focus_match"] and focus != "Alle kleinen Direktkunden":
                excluded["focus"] += 1
            else:
                excluded["oversize"] += 1
            continue
        if focus == "Alle kleinen Direktkunden" and profile["size_fit"] != "Klein":
            excluded["oversize"] += 1
            continue
        if focus == "Diamanten Radar | kleine Direktkunden" and profile["size_fit"] == "Groß oder unpassend":
            excluded["oversize"] += 1
            continue
        if focus == "Testpilot Therapie 500" and profile["segment"] != "Therapiepraxis":
            excluded["focus"] += 1
            continue
        if focus == "Montagswelle 500 | Testpilot Fachkräfte":
            if not profile["focus_match"]:
                excluded["focus"] += 1
                continue
            if profile["size_fit"] == "Groß oder unpassend" or int(profile["small_business_score"]) < 55:
                excluded["oversize"] += 1
                continue

        score = 26 if radar_mode else 10
        reasons: list[str] = []
        if radar_mode:
            score += round(int(profile["small_business_score"]) * 0.35)
            if job.get("website"):
                score += 8
                reasons.append("eigene Website")
            if job.get("phone"):
                score += 6
                reasons.append("direkte Telefonnummer")
            if job.get("career_url"):
                score += 10
                reasons.append("Karrierebereich gefunden")
            if job.get("need_signal") and "Kein öffentlicher" not in str(job.get("need_signal")):
                score += 7
                reasons.append(_clean(job.get("need_signal")))
            if int(job.get("diamond_score", 0) or 0) >= 70:
                score += 8
                reasons.append("starker Diamanten Fit")
        else:
            points, hits = _weighted(combined, TARGET_KEYWORDS)
            if points:
                score += min(28, points)
                reasons.append("Zielgruppe: " + ", ".join(hits[:3]))
            points, hits = _weighted(combined, BUYING_SIGNALS)
            if points:
                score += min(12, points)
                reasons.append("Recruitingdruck: " + ", ".join(hits[:3]))
            points, hits = _weighted(description, BENEFIT_KEYWORDS)
            if points:
                score += min(8, points)
                reasons.append("Benefits: " + ", ".join(hits[:3]))

        job_count = int(company_data.get("job_count", 1) or 1)
        distinct_titles = int(company_data.get("distinct_titles", 1) or 1)
        location_count = int(company_data.get("location_count", 1) or 1)
        source_count = int(company_data.get("source_count", 1) or 1)

        # Kleine Direktkunden werden bewusst vor großen Multipostern priorisiert.
        # Firmenradar Treffer erhalten keinen erfundenen Stellen Bonus.
        if not radar_mode:
            if job_count == 1:
                score += 15
                reasons.append("konkrete Einzelvakanz")
            elif job_count <= 3:
                score += 20
                reasons.append(f"{job_count} konkrete Stellen")
            elif job_count <= 5:
                score += 10
                reasons.append(f"{job_count} überschaubare Stellen")
            else:
                score -= 8

            if distinct_titles == 1:
                score += 7
                reasons.append("klares Suchprofil")
            elif distinct_titles <= 3:
                score += 3
            else:
                score -= 10

        if location_count <= 1:
            score += 9
            reasons.append("regionaler Direktkunde")
        elif location_count == 2:
            score += 3
        else:
            score -= 8

        if source_count >= 2:
            score += 2
        if job.get("email"):
            score += 8
            reasons.append("E Mail vorhanden")
        if job.get("contact"):
            score += 8
            reasons.append("Ansprechpartner vorhanden")
        if job.get("phone"):
            score += 5
        if job.get("external_url"):
            score += 2
        if "Karriereseite" in job.get("source", ""):
            score += 3

        # Der KMU Fit hat mehr Gewicht als reine Stellenmenge.
        score += round((int(profile["small_business_score"]) - 50) * 0.45)
        score = max(0, min(100, score))
        if focus == "Montagswelle 500 | Testpilot Fachkräfte":
            minimum_score = 58
        elif focus == "Diamanten Radar | kleine Direktkunden":
            minimum_score = 46
        else:
            minimum_score = 22 if focus in {"Breite Massenkampagne", "Alle Direktkunden", "Alle kleinen Direktkunden"} else max(MIN_LEAD_SCORE, 30)
        if score < minimum_score:
            excluded["low_score"] += 1
            continue

        job.update(company_data)
        job["lead_score"] = score
        job["lead_quality"] = "A" if score >= 75 else "B" if score >= 55 else "C"
        job["lead_segment"] = profile["segment"]
        job["size_fit"] = profile["size_fit"]
        job["size_reason"] = profile["size_reason"]
        job["small_business_score"] = int(profile["small_business_score"])
        extra_reason = [_clean(job.get("diamond_reason", ""))] if radar_mode and job.get("diamond_reason") else []
        job["lead_reasons"] = "; ".join(
            ([profile["size_reason"]] if profile["size_reason"] else []) + extra_reason + reasons[:6]
        )
        output.append(job)

    output.sort(
        key=lambda item: (
            int(item.get("small_business_score", 0) or 0),
            int(item.get("lead_score", 0) or 0),
            bool(item.get("contact")),
            bool(item.get("email") or item.get("phone")),
            -int(item.get("job_count", 1) or 1),
        ),
        reverse=True,
    )
    diagnostics.append(
        f"Direktkunden Filter ({focus}): {len(unique)} eindeutige Stellen geprüft, {len(output)} Direktkunden priorisiert. "
        f"Raus: Staffing {excluded['staffing']}, öffentlich {excluded['public']}, bekannte Großunternehmen {excluded['large_name']}, "
        f"zu groß oder Kette {excluded['oversize']}, Kampagne {excluded['focus']}, "
        f"Suchbegriff unpassend {excluded['term_mismatch']}, Score {excluded['low_score']}."
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
    ba_fetch_details: bool = False,
    ba_detail_limit: int = 40,
    focus: str = "Alle kleinen Direktkunden",
) -> tuple[list[dict], list[str]]:
    diagnostics: list[str] = []
    jobs: list[dict] = []
    if "Adzuna" in sources:
        jobs.extend(scan_adzuna(terms, regions, days, max_pages, adzuna_app_id, adzuna_api_key, diagnostics))
    if "Bundesagentur" in sources:
        jobs.extend(scan_ba(
            terms, regions, days, max_pages, diagnostics,
            fetch_details=ba_fetch_details,
            detail_limit=ba_detail_limit,
        ))
    if "Google Jobs" in sources:
        jobs.extend(scan_google_jobs(terms, regions, days, max_pages, serpapi_key, diagnostics))
    if "Karriereseiten" in sources:
        jobs.extend(scan_career_urls(career_urls or [], diagnostics))
    if "Google Firmenradar" in sources:
        jobs.extend(scan_google_company_radar(
            terms, regions, serpapi_key, diagnostics,
            max_pages=max_pages,
            probe_limit_per_query=8,
        ))
    filtered = score_and_filter(jobs, diagnostics, focus=focus)
    diagnostics.append(f"Gesamt: {len(filtered)} priorisierte Direktkunden Stellen für {focus} aus {len(sources)} aktivierten Quellen am {date.today().isoformat()}.")
    return filtered, diagnostics
