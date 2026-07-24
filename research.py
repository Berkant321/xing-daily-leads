from __future__ import annotations

import html
import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests
import tldextract
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


_EXTRACT = tldextract.TLDExtract(suffix_list_urls=None)

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
}

BLOCKED_DOMAINS = {
    "adzuna.de", "adzuna.com", "indeed.com", "indeed.de", "stepstone.de",
    "linkedin.com", "xing.com", "arbeitsagentur.de", "meinestadt.de",
    "stellenanzeigen.de", "jobware.de", "kimeta.de", "jooble.org",
    "glassdoor.de", "monster.de", "talent.com", "jobrapido.com",
    "jobsora.com", "jobvector.de", "yourfirm.de", "stellenonline.de",
    "joblift.de", "careerjet.de", "jobs.de", "kununu.com", "facebook.com",
    "instagram.com", "northdata.de", "unternehmensregister.de", "wikipedia.org",
    "11880.com", "gelbeseiten.de", "dasoertliche.de", "cylex.de",
    "golocal.de", "branchenbuch.meinestadt.de", "companyhouse.de",
}

PAGE_KEYWORDS = {
    "kontakt": 100,
    "contact": 100,
    "impressum": 95,
    "imprint": 95,
    "karriere": 90,
    "career": 90,
    "jobs": 88,
    "stellenangebote": 88,
    "team": 82,
    "ansprechpartner": 82,
    "mitarbeiter": 78,
    "people": 76,
    "ueber-uns": 65,
    "uber-uns": 65,
    "über-uns": 65,
    "unternehmen": 60,
    "about": 60,
}

EMAIL_PREFIX_SCORES = {
    "recruiting": 75,
    "personal": 72,
    "karriere": 70,
    "bewerbung": 70,
    "bewerbungen": 70,
    "jobs": 65,
    "hr": 65,
    "talent": 62,
    "people": 58,
    "office": 30,
    "kontakt": 28,
    "contact": 28,
    "info": 24,
}

BAD_EMAIL_PREFIXES = {
    "noreply", "no-reply", "donotreply", "datenschutz", "privacy",
    "abuse", "postmaster", "webmaster", "newsletter", "marketing",
}

ROLE_SCORES = {
    "talent acquisition": 100,
    "recruiting": 98,
    "recruiter": 96,
    "people and culture": 95,
    "people & culture": 95,
    "head of people": 95,
    "head of hr": 94,
    "hr business partner": 93,
    "hr manager": 92,
    "personalleitung": 92,
    "personalleiter": 92,
    "leiter personal": 91,
    "personalreferent": 88,
    "human resources": 86,
    "ansprechpartner bewerbung": 84,
    "ansprechpartner karriere": 84,
    "praxisinhaber": 80,
    "kanzleiinhaber": 80,
    "geschäftsführer": 78,
    "geschäftsführung": 76,
    "geschäftsleitung": 75,
    "inhaber": 74,
    "partner": 72,
    "vertreten durch": 68,
}

ROLE_PATTERN = (
    r"Talent\s+Acquisition(?:\s+Manager)?|Recruiting(?:\s+Manager)?|Recruiter(?:in)?|"
    r"People\s*(?:&|and)\s*Culture|Head\s+of\s+People|HR\s+Business\s+Partner|"
    r"Head\s+of\s+HR|HR\s+Manager(?:in)?|Human\s+Resources|"
    r"Personalleiter(?:in)?|Personalleitung|Leiter(?:in)?\s+(?:des\s+)?Personal(?:wesens)?|"
    r"Personalreferent(?:in)?|Ansprechpartner(?:in)?\s+(?:für\s+)?(?:Bewerbung(?:en)?|Karriere|Personal)|"
    r"Praxisinhaber(?:in)?|Kanzleiinhaber(?:in)?|Geschäftsführer(?:in)?|Geschäftsführung|Geschäftsleitung|"
    r"Inhaber(?:in)?|Partner(?:in)?|Vertreten\s+durch"
)

NAME_PATTERN = (
    r"(?:(?:Frau|Herr)\s+)?"
    r"(?:Dr\.?\s+|Prof\.?\s+|Dipl\.?[-\s]?[A-Za-zÄÖÜäöüß]+\s+)?"
    r"[A-ZÄÖÜ][A-Za-zÄÖÜäöüß'’.-]{1,30}"
    r"(?:\s+[A-ZÄÖÜ][A-Za-zÄÖÜäöüß'’.-]{1,30}){1,3}"
)


@dataclass
class ResearchResult:
    website: str = ""
    contact_page: str = ""
    imprint_page: str = ""
    career_page: str = ""
    email: str = ""
    phone: str = ""
    person: str = ""
    role: str = ""
    text: str = ""
    status: str = "nicht gefunden"
    notes: str = ""
    employee_hint: str = ""
    location_hint: str = ""
    pages_crawled: int = 0
    candidate_count: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "website": self.website,
            "contact_page": self.contact_page,
            "imprint_page": self.imprint_page,
            "career_page": self.career_page,
            "email": self.email,
            "phone": self.phone,
            "person": self.person,
            "role": self.role,
            "text": self.text,
            "status": self.status,
            "notes": self.notes,
            "employee_hint": self.employee_hint,
            "location_hint": self.location_hint,
            "pages_crawled": self.pages_crawled,
            "candidate_count": self.candidate_count,
            "errors": self.errors,
        }


def _session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        backoff_factor=0.35,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        raise_on_status=False,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    session.headers.update(BROWSER_HEADERS)
    return session


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    value = html.unescape(str(value))
    value = BeautifulSoup(value, "html.parser").get_text(" ")
    return re.sub(r"\s+", " ", value).strip()


def normalize(value: Any) -> str:
    text = clean_text(value).lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("ß", "ss")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def normalize_company(company: str) -> str:
    text = normalize(company)
    legal_patterns = [
        r"\bgmbh\s+und\s+co\s+kg\b", r"\bgmbh\s+co\s+kg\b", r"\bgmbh\b",
        r"\bmbh\b", r"\baktiengesellschaft\b", r"\bag\b", r"\bkg\b",
        r"\bohg\b", r"\bug\b", r"\bhaftungsbeschrankt\b", r"\bpartg\s+mbb\b",
        r"\bpartg\b", r"\be\s+v\b", r"\bev\b", r"\bgbr\b", r"\bse\b",
        r"\bsteuerberatungsgesellschaft\b", r"\brechtsanwaltsgesellschaft\b",
    ]
    for pattern in legal_patterns:
        text = re.sub(pattern, " ", text)
    return re.sub(r"\s+", " ", text).strip()


def company_tokens(company: str) -> list[str]:
    stop = {
        "gruppe", "group", "holding", "gesellschaft", "service", "services",
        "unternehmen", "praxis", "kanzlei", "zentrum", "team", "partner",
        "international", "deutschland", "und", "the", "von", "fur", "fuer",
    }
    return [
        token for token in normalize_company(company).split()
        if len(token) >= 3 and token not in stop
    ]


def root_domain(url: str) -> str:
    parsed = urlparse(url if "://" in url else "https://" + url)
    ext = _EXTRACT(parsed.hostname or "")
    return f"{ext.domain}.{ext.suffix}" if ext.domain and ext.suffix else ""


def homepage_from_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url if "://" in url else "https://" + url)
    if not parsed.hostname:
        return ""
    scheme = parsed.scheme if parsed.scheme in {"http", "https"} else "https"
    return f"{scheme}://{parsed.netloc}"


def is_blocked_url(url: str) -> bool:
    domain = root_domain(url).lower()
    return not domain or any(domain == item or domain.endswith("." + item) for item in BLOCKED_DOMAINS)


def _safe_get(
    session: requests.Session,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: int = 18,
    max_bytes: int = 2_500_000,
) -> tuple[requests.Response | None, str]:
    try:
        response = session.get(url, params=params, timeout=timeout, allow_redirects=True)
        if response.status_code >= 400:
            return None, f"HTTP {response.status_code}"
        content_type = response.headers.get("content-type", "").lower()
        if "text/html" not in content_type and "application/xhtml" not in content_type and "json" not in content_type:
            return None, f"kein HTML ({content_type[:60]})"
        if len(response.content) > max_bytes:
            response._content = response.content[:max_bytes]
        return response, ""
    except requests.RequestException as exc:
        return None, str(exc)[:180]


def _unwrap_search_url(url: str) -> str:
    if not url:
        return ""
    url = html.unescape(url)
    if url.startswith("//"):
        url = "https:" + url
    parsed = urlparse(url)
    if "duckduckgo.com" in (parsed.hostname or ""):
        query = parse_qs(parsed.query)
        if query.get("uddg"):
            return unquote(query["uddg"][0])
    return url


def _candidate_record(url: str, context: str = "", phone: str = "", source: str = "") -> dict[str, str]:
    return {
        "url": _unwrap_search_url(url),
        "context": clean_text(context),
        "phone": clean_text(phone),
        "source": source,
    }


def _search_candidates_serpapi(
    session: requests.Session,
    company: str,
    city: str,
    api_key: str,
    errors: list[str],
) -> list[dict[str, str]]:
    if not api_key:
        return []
    queries = [
        f'"{company}" {city} offizielle Website Kontakt'.strip(),
        f'"{company}" {city} Impressum Telefonnummer E Mail'.strip(),
        f'"{company}" {city} Personal Recruiting HR Geschäftsführer Ansprechpartner'.strip(),
    ]
    candidates: list[dict[str, str]] = []
    for query in queries:
        response, error = _safe_get(
            session,
            "https://serpapi.com/search.json",
            params={"engine": "google", "q": query, "hl": "de", "gl": "de", "api_key": api_key},
            timeout=30,
        )
        if error or not response:
            errors.append(f"SerpApi: {error or 'keine Antwort'}")
            continue
        try:
            payload = response.json()
        except ValueError:
            errors.append("SerpApi: ungültige JSON Antwort")
            continue

        for item in payload.get("organic_results", [])[:12]:
            link = item.get("link", "")
            if link:
                context = " ".join([
                    str(item.get("title", "")),
                    str(item.get("snippet", "")),
                    str(item.get("displayed_link", "")),
                ])
                candidates.append(_candidate_record(link, context=context, source="SerpApi organic"))

        knowledge = payload.get("knowledge_graph") or {}
        if knowledge.get("website"):
            context = " ".join([
                str(knowledge.get("title", "")),
                str(knowledge.get("description", "")),
                str(knowledge.get("address", "")),
            ])
            candidates.append(_candidate_record(
                knowledge["website"],
                context=context,
                phone=str(knowledge.get("phone", "")),
                source="SerpApi knowledge graph",
            ))

        local_results = payload.get("local_results") or {}
        places = local_results.get("places", []) if isinstance(local_results, dict) else []
        for local in places[:8]:
            if local.get("website"):
                context = " ".join([
                    str(local.get("title", "")),
                    str(local.get("address", "")),
                    str(local.get("description", "")),
                ])
                candidates.append(_candidate_record(
                    local["website"],
                    context=context,
                    phone=str(local.get("phone", "")),
                    source="SerpApi local",
                ))
        time.sleep(0.08)
    return candidates


def _search_candidates_duckduckgo(
    session: requests.Session,
    company: str,
    city: str,
    errors: list[str],
) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    for query in (
        f'"{company}" {city} offizielle Website'.strip(),
        f'"{company}" {city} Impressum Kontakt'.strip(),
    ):
        response, error = _safe_get(
            session,
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            timeout=25,
        )
        if error or not response:
            errors.append(f"DuckDuckGo: {error or 'keine Antwort'}")
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        for result in soup.select(".result"):
            anchor = result.select_one("a.result__a, a.result-link")
            if not anchor:
                continue
            href = _unwrap_search_url(anchor.get("href", ""))
            snippet = result.select_one(".result__snippet")
            context = f"{anchor.get_text(' ')} {snippet.get_text(' ') if snippet else ''}"
            if href:
                candidates.append(_candidate_record(href, context=context, source="DuckDuckGo"))
        time.sleep(0.08)
    return candidates


def _candidate_url_score(url: str, company: str, city: str = "") -> int:
    if is_blocked_url(url):
        return -999
    domain = root_domain(url)
    domain_base = domain.split(".")[0].replace("-", " ")
    company_norm = normalize_company(company)
    tokens = company_tokens(company)
    score = 0
    compact_domain = re.sub(r"\W+", "", domain_base)
    compact_company = re.sub(r"\W+", "", company_norm)
    if compact_company and (compact_company in compact_domain or compact_domain in compact_company):
        score += 55
    for token in tokens[:6]:
        if token in normalize(domain_base):
            score += 18
    if city and normalize(city).split(" ")[0] in normalize(url):
        score += 6
    parsed = urlparse(url)
    if parsed.path in {"", "/"}:
        score += 4
    if any(term in normalize(url) for term in ("impressum", "kontakt", "karriere")):
        score += 3
    return score


def _page_company_score(text: str, title: str, company: str, city: str = "") -> int:
    haystack = normalize(f"{title} {text[:12000]}")
    tokens = company_tokens(company)
    score = 0
    for token in tokens[:6]:
        if token in haystack:
            score += 10
    company_norm = normalize_company(company)
    if len(company_norm) >= 5 and company_norm in haystack:
        score += 35
    if city and normalize(city) in haystack:
        score += 5
    return score


def _company_domain_guesses(company: str) -> list[str]:
    """Erzeugt wenige plausible Domains und akzeptiert sie erst nach Inhaltsprüfung."""
    tokens = company_tokens(company)
    if not tokens:
        return []
    variants: list[str] = []
    compact = "".join(tokens[:4])
    hyphenated = "-".join(tokens[:4])
    first_two = "".join(tokens[:2])
    first_two_hyphen = "-".join(tokens[:2])
    for value in (compact, hyphenated, first_two, first_two_hyphen, tokens[0]):
        value = re.sub(r"[^a-z0-9-]", "", normalize(value).replace(" ", "-"))
        if value and value not in variants:
            variants.append(value)
    urls: list[str] = []
    for variant in variants[:3]:
        for tld in ("de", "com", "at", "ch", "li"):
            urls.append(f"https://www.{variant}.{tld}")
    return urls[:8]


def _hint_bundle(context: str) -> dict[str, list]:
    context = clean_text(context)
    people = extract_people(context) if context else []
    return {
        "emails": extract_emails("", context),
        "phones": extract_phones("", context),
        "people": people,
    }


def discover_official_website(
    company: str,
    city: str = "",
    source_urls: Iterable[str] | None = None,
    serpapi_key: str = "",
    session: requests.Session | None = None,
) -> tuple[str, list[str], list[str], dict[str, list[str]]]:
    session = session or _session()
    errors: list[str] = []
    records: list[dict[str, str]] = []

    for source in source_urls or []:
        source = _unwrap_search_url(source)
        if source and not is_blocked_url(source):
            records.append(_candidate_record(homepage_from_url(source), context=company, source="Stellenlink"))

    records.extend(_search_candidates_serpapi(session, company, city, serpapi_key, errors))
    if len(records) < 3:
        records.extend(_search_candidates_duckduckgo(session, company, city, errors))

    # Suchtreffer von XING und LinkedIn werden nicht gecrawlt, ihre öffentlichen
    # Titel und Snippets helfen aber bei Ansprechpartnern und Rollen.
    search_context = " ".join(record.get("context", "") for record in records)
    search_hints = _hint_bundle(search_context)

    # Falls Suchdienste blockiert sind oder keine Treffer liefern, werden wenige
    # plausible Domains getestet. Eine Übernahme erfolgt erst nach Namensprüfung.
    existing_domains = {root_domain(record.get("url", "")) for record in records if record.get("url")}
    has_public_candidate = any(
        record.get("url") and not is_blocked_url(record.get("url", ""))
        for record in records
    )
    if not has_public_candidate:
        for guessed_url in _company_domain_guesses(company):
            if root_domain(guessed_url) not in existing_domains:
                records.append(_candidate_record(guessed_url, context=company, source="Domain Vermutung mit Inhaltsprüfung"))

    merged: dict[str, dict[str, str]] = {}
    for record in records:
        home = homepage_from_url(record.get("url", ""))
        domain = root_domain(home)
        if not home or not domain or is_blocked_url(home):
            continue
        if domain not in merged:
            merged[domain] = {"url": home, "context": "", "phone": "", "source": ""}
        merged[domain]["context"] = clean_text(
            f"{merged[domain].get('context', '')} {record.get('context', '')}"
        )
        merged[domain]["phone"] = merged[domain].get("phone", "") or record.get("phone", "")
        merged[domain]["source"] = clean_text(
            f"{merged[domain].get('source', '')} {record.get('source', '')}"
        )

    unique = list(merged.values())
    unique.sort(
        key=lambda item: (
            _candidate_url_score(item["url"], company, city)
            + _page_company_score(item.get("context", ""), "", company, city)
        ),
        reverse=True,
    )

    best_url = ""
    best_score = -999
    best_record: dict[str, str] = {}
    for record in unique[:15]:
        candidate = record["url"]
        url_score = _candidate_url_score(candidate, company, city)
        context_score = _page_company_score(record.get("context", ""), "", company, city)
        if url_score < 0:
            continue
        candidate_timeout = 7 if "Domain Vermutung" in record.get("source", "") else 18
        response, error = _safe_get(session, candidate, timeout=candidate_timeout)
        if error or not response:
            errors.append(f"{candidate}: {error}")
            continue
        final_home = homepage_from_url(response.url)
        if is_blocked_url(final_home):
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        title = clean_text(soup.title.get_text(" ") if soup.title else "")
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()
        body_text = clean_text(soup.get_text(" "))
        page_score = _page_company_score(body_text, title, company, city)
        score = url_score + context_score + page_score
        if score > best_score:
            best_score = score
            best_url = final_home
            best_record = record
        if score >= 75:
            break

    # Eine Domain wird nur übernommen, wenn Domain, Suchkontext oder Seiteninhalt
    # einen echten Bezug zum Firmennamen zeigen. Kleine Firmen haben oft kurze
    # Websites, deshalb ist die Schwelle bewusst moderat.
    accepted = best_url if best_score >= 18 else ""
    hints = search_hints
    if accepted and best_record:
        context = best_record.get("context", "")
        hints["emails"] = list(dict.fromkeys(hints.get("emails", []) + extract_emails("", context)))
        hints["phones"] = list(dict.fromkeys(
            hints.get("phones", []) + extract_phones("", f"{best_record.get('phone', '')} {context}")
        ))
        hints["people"] = list(hints.get("people", []))
    return accepted, [item["url"] for item in unique], errors, hints

def _same_site(url: str, homepage: str) -> bool:
    return bool(root_domain(url)) and root_domain(url) == root_domain(homepage)


def _page_priority(url: str, anchor_text: str = "") -> int:
    target = normalize(f"{url} {anchor_text}").replace(" ", "-")
    score = 0
    for keyword, points in PAGE_KEYWORDS.items():
        normalized_keyword = normalize(keyword).replace(" ", "-")
        if normalized_keyword in target:
            score = max(score, points)
    return score


def collect_internal_pages(homepage: str, html_text: str, max_pages: int = 12) -> list[str]:
    soup = BeautifulSoup(html_text, "html.parser")
    scored: dict[str, int] = {homepage: 1000}
    for anchor in soup.find_all("a", href=True):
        href = urljoin(homepage, anchor.get("href", ""))
        href = href.split("#", 1)[0]
        if not href.startswith("http") or not _same_site(href, homepage):
            continue
        priority = _page_priority(href, clean_text(anchor.get_text(" ")))
        if priority:
            scored[href] = max(scored.get(href, 0), priority)

    fallback_paths = (
        "/kontakt", "/contact", "/impressum", "/karriere", "/jobs",
        "/stellenangebote", "/team", "/ansprechpartner", "/ueber-uns",
    )
    for path in fallback_paths:
        url = urljoin(homepage.rstrip("/") + "/", path.lstrip("/"))
        scored.setdefault(url, _page_priority(url))

    return [url for url, _ in sorted(scored.items(), key=lambda item: item[1], reverse=True)[:max_pages]]


def _deobfuscate_email_text(text: str) -> str:
    text = html.unescape(text or "")
    replacements = {
        "[at]": "@", "(at)": "@", "{at}": "@", " [ät] ": "@",
        "[dot]": ".", "(dot)": ".", "{dot}": ".",
    }
    for old, new in replacements.items():
        text = text.replace(old, new).replace(old.upper(), new)
    text = re.sub(r"\s+(?:at|ät)\s+", "@", text, flags=re.I)
    text = re.sub(r"\s+(?:dot|punkt)\s+", ".", text, flags=re.I)
    return text


def extract_emails(html_text: str, page_text: str = "") -> list[str]:
    soup = BeautifulSoup(html_text or "", "html.parser")
    values: list[str] = []
    for anchor in soup.select('a[href^="mailto:"]'):
        address = anchor.get("href", "")[7:].split("?", 1)[0]
        if address:
            values.append(unquote(address))
    combined = _deobfuscate_email_text(f"{html_text} {page_text}")
    values.extend(re.findall(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", combined, re.I))

    output: list[str] = []
    seen: set[str] = set()
    for email in values:
        email = email.strip(" .,:;<>[]()\"'").lower()
        if not email or email in seen or len(email) > 160:
            continue
        if re.search(r"\.(?:png|jpg|jpeg|gif|svg|webp)$", email):
            continue
        seen.add(email)
        output.append(email)
    return output


def choose_email(emails: Iterable[str], website_domain: str, person: str = "") -> str:
    domain = root_domain(website_domain) or website_domain.lower().lstrip("www.")
    person_tokens = [
        token for token in normalize(person).split()
        if token not in {"frau", "herr", "dr", "prof", "dipl"} and len(token) >= 2
    ]
    first_name = person_tokens[0] if person_tokens else ""
    last_name = person_tokens[-1] if person_tokens else ""
    best = ""
    best_score = -999
    for email in emails:
        local, _, email_domain = email.lower().partition("@")
        if not local or not email_domain:
            continue
        local_norm = normalize(local).replace(" ", "")
        score = 0
        if root_domain("https://" + email_domain) == domain or email_domain == domain:
            score += 45
        else:
            score -= 35
        if local in BAD_EMAIL_PREFIXES or any(local.startswith(item) for item in BAD_EMAIL_PREFIXES):
            score -= 150
        if last_name and last_name in local_norm:
            score += 125
            if first_name and (first_name in local_norm or local_norm.startswith(first_name[:1] + last_name)):
                score += 35
        for prefix, points in EMAIL_PREFIX_SCORES.items():
            if local == prefix or local.startswith(prefix + ".") or local.startswith(prefix + "-"):
                score += points
        if "." in local and not any(char.isdigit() for char in local):
            score += 25
        if local.startswith("info") or local.startswith("kontakt"):
            score -= 15
        if score > best_score:
            best_score = score
            best = email
    return best if best_score > -50 else ""


def extract_phones(html_text: str, page_text: str = "") -> list[str]:
    soup = BeautifulSoup(html_text or "", "html.parser")
    values: list[str] = []
    for anchor in soup.select('a[href^="tel:"]'):
        values.append(unquote(anchor.get("href", "")[4:]))
    values.extend(re.findall(r"(?:\+49|0049|0)[\d\s()/.-]{7,24}", page_text or ""))

    output: list[str] = []
    seen_digits: set[str] = set()
    for value in values:
        value = re.sub(r"\s+", " ", value).strip(" .,:;-/")
        digits = re.sub(r"\D", "", value)
        if digits.startswith("0049"):
            digits = "49" + digits[4:]
        if not 8 <= len(digits) <= 16 or digits in seen_digits:
            continue
        seen_digits.add(digits)
        output.append(value)
    return output


def _valid_person(name: str) -> bool:
    name = clean_text(name).strip(" ,;:-")
    parts = name.split()
    if not 2 <= len(parts) <= 5:
        return False
    bad = {
        "gmbh", "gesellschaft", "team", "kontakt", "karriere", "personal",
        "impressum", "telefon", "email", "deutschland", "geschäftsführung",
    }
    normalized_parts = {normalize(part) for part in parts if normalize(part) not in {"frau", "herr", "dr", "prof"}}
    if normalized_parts & bad:
        return False
    return sum(1 for part in parts if re.match(r"^(?:Dr\.?|Prof\.?)$|^[A-ZÄÖÜ]", part)) >= 2


def _role_score(role: str) -> int:
    role_norm = normalize(role)
    best = 0
    for key, points in ROLE_SCORES.items():
        if normalize(key) in role_norm:
            best = max(best, points)
    return best


def extract_people(page_text: str) -> list[tuple[str, str, int]]:
    text = clean_text(page_text)
    snippets: list[tuple[str, str]] = []
    patterns = [
        rf"(?P<role>{ROLE_PATTERN})\s*(?::|\||,|–|-)?\s*(?P<name>{NAME_PATTERN})",
        rf"(?P<name>{NAME_PATTERN})\s*(?:\||,|–|-)\s*(?P<role>{ROLE_PATTERN})",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.I):
            snippets.append((match.group("name"), match.group("role")))

    # Zusätzlich zeilenweise, falls Rolle und Name auf getrennten Zeilen stehen.
    raw_lines = [clean_text(line) for line in re.split(r"[\r\n]+|\s{3,}", page_text or "")]
    raw_lines = [line for line in raw_lines if line]
    for index, line in enumerate(raw_lines):
        role_match = re.search(ROLE_PATTERN, line, re.I)
        if not role_match:
            continue
        role = role_match.group(0)
        for candidate_line in (line, raw_lines[index + 1] if index + 1 < len(raw_lines) else ""):
            name_match = re.search(NAME_PATTERN, candidate_line)
            if name_match:
                snippets.append((name_match.group(0), role))
                break

    output: list[tuple[str, str, int]] = []
    seen: set[tuple[str, str]] = set()
    for name, role in snippets:
        name = clean_text(name).strip(" ,;:-")
        role = clean_text(role)
        key = (name.lower(), role.lower())
        if key in seen or not _valid_person(name):
            continue
        seen.add(key)
        output.append((name, role, _role_score(role)))
    output.sort(key=lambda item: item[2], reverse=True)
    return output


def extract_employee_hint(text: str) -> str:
    normalized = clean_text(text)
    patterns = [
        r"(?:über|mehr als|rund|ca\.?|circa)?\s*(\d{2,5})\s+(?:Mitarbeitende|Mitarbeiter(?:innen)?|Beschäftigte)",
        r"Team\s+(?:von|mit)\s+(\d{2,5})",
    ]
    values: list[int] = []
    for pattern in patterns:
        for match in re.finditer(pattern, normalized, re.I):
            try:
                values.append(int(match.group(1)))
            except ValueError:
                pass
    return str(max(values)) if values else ""


def extract_location_hint(text: str) -> str:
    normalized = clean_text(text)
    patterns = [
        r"(\d{1,3})\s+Standorte",
        r"an\s+(\d{1,3})\s+Standorten",
        r"(\d{1,3})\s+Niederlassungen",
    ]
    values: list[int] = []
    for pattern in patterns:
        for match in re.finditer(pattern, normalized, re.I):
            try:
                values.append(int(match.group(1)))
            except ValueError:
                pass
    return str(max(values)) if values else ""


def research_company(
    *,
    company: str,
    city: str = "",
    source_urls: Iterable[str] | None = None,
    source_text: str = "",
    serpapi_key: str = "",
    max_pages: int = 12,
) -> dict[str, Any]:
    result = ResearchResult()
    session = _session()
    source_hints = _hint_bundle(source_text)
    website, candidates, errors, search_hints = discover_official_website(
        company=company,
        city=city,
        source_urls=source_urls,
        serpapi_key=serpapi_key,
        session=session,
    )
    result.candidate_count = len(candidates)
    result.errors.extend(errors[:8])

    combined_hint_emails = list(dict.fromkeys(source_hints.get("emails", []) + search_hints.get("emails", [])))
    combined_hint_phones = list(dict.fromkeys(source_hints.get("phones", []) + search_hints.get("phones", [])))
    combined_hint_people = list(source_hints.get("people", [])) + list(search_hints.get("people", []))
    combined_hint_people.sort(key=lambda item: item[2], reverse=True)

    # Website und öffentliche Suchhinweise werden sofort gespeichert. Viele
    # Unternehmensseiten blockieren automatisierte Abrufe, obwohl die Domain stimmt.
    result.website = website
    result.phone = combined_hint_phones[0] if combined_hint_phones else ""
    if combined_hint_people:
        result.person, result.role, _ = combined_hint_people[0]
    if website:
        result.email = choose_email(combined_hint_emails, root_domain(website), result.person)
    elif combined_hint_emails:
        result.email = combined_hint_emails[0]

    if not website:
        result.status = "teilweise" if (result.email or result.phone or result.person) else "nicht gefunden"
        result.notes = "Keine sicher passende Firmenwebsite gefunden."
        if result.email or result.phone or result.person:
            result.notes += " Kontakthinweise aus Stellenanzeige oder öffentlichen Suchtreffern übernommen."
        if errors:
            result.notes += " " + " | ".join(errors[:2])
        return result.as_dict()

    first, error = _safe_get(session, website, timeout=20)
    if error or not first:
        result.status = "teilweise"
        result.notes = f"Website erkannt, Abruf aber blockiert oder nicht erreichbar: {error}."
        if result.email or result.phone or result.person:
            result.notes += " Öffentliche Kontakthinweise wurden trotzdem übernommen."
        return result.as_dict()

    website = homepage_from_url(first.url)
    result.website = website
    page_urls = collect_internal_pages(website, first.text, max_pages=max_pages)

    all_emails: list[str] = list(dict.fromkeys(combined_hint_emails))
    all_phones: list[str] = list(dict.fromkeys(combined_hint_phones))
    all_people: list[tuple[str, str, int]] = list(combined_hint_people)
    all_texts: list[str] = []
    visited: set[str] = set()

    for page_url in page_urls:
        if page_url in visited:
            continue
        visited.add(page_url)
        response = first if homepage_from_url(page_url) == website and page_url.rstrip("/") == website.rstrip("/") else None
        if response is None:
            response, error = _safe_get(session, page_url, timeout=16)
            if error or not response:
                continue
        if not _same_site(response.url, website):
            continue

        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg", "canvas"]):
            tag.decompose()
        page_text = soup.get_text("\n")
        clean_page = clean_text(page_text)
        if not clean_page:
            continue

        result.pages_crawled += 1
        all_texts.append(clean_page[:30000])
        all_emails.extend(extract_emails(response.text, page_text))
        all_phones.extend(extract_phones(response.text, page_text))
        all_people.extend(extract_people(page_text))

        low_url = normalize(response.url)
        if not result.contact_page and any(term in low_url for term in ("kontakt", "contact")):
            result.contact_page = response.url
        if not result.imprint_page and any(term in low_url for term in ("impressum", "imprint")):
            result.imprint_page = response.url
        if not result.career_page and any(term in low_url for term in ("karriere", "career", "jobs", "stellenangebote")):
            result.career_page = response.url

    combined_text = " ".join(all_texts)
    result.text = combined_text[:45000]
    result.phone = all_phones[0] if all_phones else ""

    if all_people:
        all_people.sort(key=lambda item: item[2], reverse=True)
        result.person, result.role, _ = all_people[0]

    result.email = choose_email(all_emails, root_domain(website), result.person)

    result.employee_hint = extract_employee_hint(combined_text)
    result.location_hint = extract_location_hint(combined_text)

    if result.website and (result.email or result.phone) and result.pages_crawled >= 2:
        result.status = "vollständig"
    elif result.website:
        result.status = "teilweise"
    else:
        result.status = "nicht gefunden"

    found = []
    if result.email:
        found.append("E-Mail")
    if result.phone:
        found.append("Telefon")
    if result.person:
        found.append("Ansprechpartner")
    result.notes = (
        f"{result.pages_crawled} Seiten geprüft. "
        + ("Gefunden: " + ", ".join(found) + "." if found else "Keine direkten Kontaktdaten gefunden.")
    )
    if result.errors and not found:
        result.notes += " Hinweise: " + " | ".join(result.errors[:2])
    return result.as_dict()
