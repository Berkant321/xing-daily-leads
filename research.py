from __future__ import annotations

import html
import json
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
_SERPAPI_PAUSED_UNTIL = 0.0
_SERPAPI_PAUSE_SECONDS = 15 * 60

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
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

ATS_HOSTS = {
    "jobs.personio.de", "jobs.personio.com", "greenhouse.io", "lever.co",
    "smartrecruiters.com", "workable.com", "teamtailor.com", "softgarden.io",
    "onlyfy.io", "join.com",
}

PAGE_KEYWORDS = {
    "karriere": 120, "career": 120, "jobs": 115, "stellenangebote": 115,
    "stellen": 110, "bewerbung": 105, "bewerben": 105,
    "team": 90, "mitarbeiter": 90, "people": 90, "ansprechpartner": 90,
    "kontakt": 85, "contact": 85, "impressum": 80, "imprint": 80,
    "ueber-uns": 65, "uber-uns": 65, "über-uns": 65, "unternehmen": 60,
    "about": 60,
}

ROLE_SCORES = {
    "talent acquisition": 100, "recruiting": 98, "recruiter": 96,
    "people and culture": 95, "people & culture": 95, "head of people": 95,
    "head of hr": 94, "hr business partner": 93, "hr manager": 92,
    "personalleitung": 92, "personalleiter": 92, "leiter personal": 91,
    "personalreferent": 88, "human resources": 86,
    "ansprechpartner bewerbung": 84, "ansprechpartner karriere": 84,
    "praxisinhaber": 82, "kanzleiinhaber": 82,
    "geschäftsführer": 80, "geschäftsführerin": 80, "geschäftsführung": 78,
    "geschäftsleitung": 76, "inhaber": 76, "inhaberin": 76,
    "partner": 72, "vertreten durch": 68,
}

ROLE_PATTERN = (
    r"Talent\s+Acquisition(?:\s+Manager)?|Recruiting(?:\s+Manager)?|Recruiter(?:in)?|"
    r"People\s*(?:&|and)\s*Culture|Head\s+of\s+People|HR\s+Business\s+Partner|"
    r"Head\s+of\s+HR|HR\s+Manager(?:in)?|Human\s+Resources|"
    r"Personalleiter(?:in)?|Personalleitung|Leiter(?:in)?\s+(?:des\s+)?Personal(?:wesens)?|"
    r"Personalreferent(?:in)?|Ansprechpartner(?:in)?(?:\s+(?:für|fuer)\s+(?:Bewerbung(?:en)?|Karriere|Personal))?|"
    r"Kontaktperson|Praxisinhaber(?:in)?|Kanzleiinhaber(?:in)?|"
    r"Geschäftsführer(?:in)?|Geschaeftsfuehrer(?:in)?|Geschäftsführung|Geschäftsleitung|"
    r"Inhaber(?:in)?|Partner(?:in)?|Vertreten\s+durch"
)

GENERIC_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "gmx.de", "gmx.net",
    "web.de", "icloud.com", "yahoo.com", "yahoo.de", "t-online.de",
}
BAD_EMAIL_PREFIXES = {
    "noreply", "no-reply", "donotreply", "datenschutz", "privacy", "abuse",
    "postmaster", "webmaster", "newsletter", "marketing",
}
EMAIL_PREFIX_SCORES = {
    "recruiting": 75, "personal": 72, "karriere": 70, "bewerbung": 70,
    "bewerbungen": 70, "jobs": 65, "hr": 65, "talent": 62, "people": 58,
    "office": 30, "kontakt": 28, "contact": 28, "info": 24,
}

PERSON_BAD_TOKENS = {
    "ihre", "ihr", "unsere", "unser", "wir", "sie", "stellenanzeige", "anzeige",
    "landet", "direkt", "individuelle", "kundenwunsche", "kundenwuensche", "mit",
    "physiotherapeut", "physiotherapie", "ergotherapeut", "ergotherapie", "logopade",
    "logopaede", "logopadie", "examen", "bewerbung", "bewerbungen", "karriere",
    "kontakt", "team", "personal", "impressum", "telefon", "email", "e-mail",
    "geschaftsfuhrer", "geschaftsfuhrerin", "geschaftsfuhrung", "geschaeftsfuehrer",
    "geschaeftsfuehrerin", "geschaeftsfuehrung", "inhaber", "inhaberin", "partner",
    "recruiting", "human", "resources", "ansprechpartner", "kontaktperson",
    "deutschland", "stellenangebot", "job", "jobs", "stelle", "stellen",
}

NAME_CONNECTORS = {"von", "van", "de", "der", "den", "zu", "zur", "zum", "da", "di"}
TITLE_TOKENS = {"herr", "frau", "dr", "dr.", "prof", "prof.", "dipl", "dipl."}


def _serpapi_is_paused() -> bool:
    return time.monotonic() < _SERPAPI_PAUSED_UNTIL


def _pause_serpapi() -> None:
    global _SERPAPI_PAUSED_UNTIL
    _SERPAPI_PAUSED_UNTIL = max(_SERPAPI_PAUSED_UNTIL, time.monotonic() + _SERPAPI_PAUSE_SECONDS)


def _session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=2, connect=2, read=2, backoff_factor=0.35,
        status_forcelist=(500, 502, 503, 504), allowed_methods=("GET",),
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
    if re.search(r"<[A-Za-z][^>]*>", value):
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
    return [token for token in normalize_company(company).split() if len(token) >= 3 and token not in stop]


def root_domain(url: str) -> str:
    parsed = urlparse(url if "://" in str(url) else "https://" + str(url))
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


def _candidate_url_score(url: str, company: str, city: str = "") -> int:
    if is_blocked_url(url):
        return -999
    domain = root_domain(url)
    domain_base = domain.split(".")[0].replace("-", " ")
    tokens = company_tokens(company)
    score = 0
    for token in tokens[:6]:
        if token in normalize(domain_base):
            score += 22
    compact_domain = re.sub(r"\W+", "", domain_base)
    compact_company = re.sub(r"\W+", "", normalize_company(company))
    if compact_company and compact_domain and (compact_company in compact_domain or compact_domain in compact_company):
        score += 45
    if city and normalize(city).split(" ")[0] in normalize(url):
        score += 6
    if urlparse(url).path in {"", "/"}:
        score += 4
    return score


def _page_company_score(text: str, title: str, company: str, city: str = "") -> int:
    haystack = normalize(f"{title} {text[:18000]}")
    company_norm = normalize_company(company)
    tokens = company_tokens(company)
    score = 0
    if company_norm and len(company_norm) >= 5 and company_norm in haystack:
        score += 45
    token_hits = sum(1 for token in tokens[:6] if token in haystack)
    score += min(36, token_hits * 9)
    if city and normalize(city) in haystack:
        score += 12
    return score


def _search_duckduckgo(session: requests.Session, company: str, city: str, errors: list[str]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    queries = [
        f'"{company}" {city} offizielle Website'.strip(),
        f'"{company}" {city} Karriere Impressum'.strip(),
    ]
    for query in queries:
        response, error = _safe_get(session, "https://html.duckduckgo.com/html/", params={"q": query}, timeout=25)
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
            context = clean_text(f"{anchor.get_text(' ')} {snippet.get_text(' ') if snippet else ''}")
            if href:
                output.append({"url": href, "context": context, "source": "DuckDuckGo"})
    return output


def _search_serpapi(session: requests.Session, company: str, city: str, api_key: str, errors: list[str]) -> list[dict[str, str]]:
    if not api_key or _serpapi_is_paused():
        return []
    output: list[dict[str, str]] = []
    queries = [
        f'"{company}" {city} offizielle Website'.strip(),
        f'"{company}" {city} Karriere Jobs'.strip(),
    ]
    for query in queries:
        response, error = _safe_get(
            session,
            "https://serpapi.com/search.json",
            params={"engine": "google", "q": query, "hl": "de", "gl": "de", "api_key": api_key},
            timeout=30,
        )
        if error or not response:
            message = error or "keine Antwort"
            errors.append(f"SerpApi: {message}")
            if any(token in message.lower() for token in ("429", "quota", "limit")):
                _pause_serpapi()
                break
            continue
        try:
            payload = response.json()
        except ValueError:
            errors.append("SerpApi: ungueltige JSON Antwort")
            continue
        for item in payload.get("organic_results", [])[:12]:
            link = item.get("link", "")
            if link:
                output.append({
                    "url": link,
                    "context": clean_text(" ".join([str(item.get("title", "")), str(item.get("snippet", ""))])),
                    "source": "SerpApi",
                })
        knowledge = payload.get("knowledge_graph") or {}
        if knowledge.get("website"):
            output.append({
                "url": knowledge["website"],
                "context": clean_text(" ".join([str(knowledge.get("title", "")), str(knowledge.get("description", "")), str(knowledge.get("address", ""))])),
                "source": "SerpApi Knowledge",
            })
    return output


def discover_official_website(
    company: str,
    city: str = "",
    source_urls: Iterable[str] | None = None,
    serpapi_key: str = "",
    session: requests.Session | None = None,
) -> tuple[str, list[str], list[str]]:
    session = session or _session()
    errors: list[str] = []
    records: list[dict[str, str]] = []
    for source in source_urls or []:
        source = _unwrap_search_url(clean_text(source))
        if source and not is_blocked_url(source):
            records.append({"url": homepage_from_url(source), "context": company, "source": "Bekannte URL"})
    records.extend(_search_duckduckgo(session, company, city, errors))
    if len(records) < 4:
        records.extend(_search_serpapi(session, company, city, serpapi_key, errors))

    merged: dict[str, dict[str, str]] = {}
    for record in records:
        home = homepage_from_url(record.get("url", ""))
        domain = root_domain(home)
        if not home or not domain or is_blocked_url(home):
            continue
        if domain not in merged:
            merged[domain] = {"url": home, "context": "", "source": ""}
        merged[domain]["context"] = clean_text(f"{merged[domain]['context']} {record.get('context', '')}")
        merged[domain]["source"] = clean_text(f"{merged[domain]['source']} {record.get('source', '')}")

    candidates = list(merged.values())
    candidates.sort(key=lambda item: _candidate_url_score(item["url"], company, city), reverse=True)
    checked: list[str] = []
    best_url = ""
    best_score = -999
    for candidate in candidates[:10]:
        url = candidate["url"]
        response, error = _safe_get(session, url, timeout=16)
        if error or not response:
            continue
        final_home = homepage_from_url(response.url)
        if is_blocked_url(final_home):
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        title = soup.title.get_text(" ") if soup.title else ""
        page_text = soup.get_text(" ")
        page_score = _page_company_score(page_text, title, company, city)
        url_score = _candidate_url_score(final_home, company, city)
        context_score = _page_company_score(candidate.get("context", ""), "", company, city)
        total = page_score + min(35, max(0, url_score)) + min(20, context_score)
        checked.append(final_home)
        # Hohe Mindestschwelle: lieber kein Kontakt als falsche Firma.
        minimum = 50 if len(company_tokens(company)) >= 2 else 58
        if page_score < 18 and url_score < 35:
            continue
        if total >= minimum and total > best_score:
            best_score = total
            best_url = final_home
    return best_url, checked, errors


def _same_site(url: str, website: str) -> bool:
    return bool(root_domain(url) and root_domain(url) == root_domain(website))


def collect_internal_pages(website: str, html_text: str, max_pages: int = 20) -> list[str]:
    soup = BeautifulSoup(html_text or "", "html.parser")
    scored: list[tuple[int, str]] = []
    seen: set[str] = set()
    home = homepage_from_url(website)
    if home:
        scored.append((1000, home))
        seen.add(home.rstrip("/"))
    for anchor in soup.find_all("a", href=True):
        url = urljoin(website, anchor.get("href", ""))
        if not _same_site(url, website):
            continue
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            continue
        clean_url = url.split("#", 1)[0]
        key = clean_url.rstrip("/")
        if key in seen:
            continue
        low = normalize(f"{clean_url} {anchor.get_text(' ')}")
        score = max([points for keyword, points in PAGE_KEYWORDS.items() if normalize(keyword) in low] or [0])
        if score <= 0:
            continue
        seen.add(key)
        scored.append((score, clean_url))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [url for _, url in scored[:max(1, max_pages)]]


def extract_career_links(website: str, html_text: str, limit: int = 10) -> list[str]:
    soup = BeautifulSoup(html_text or "", "html.parser")
    scored: list[tuple[int, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        url = urljoin(website, anchor.get("href", ""))
        low = normalize(f"{url} {anchor.get_text(' ')}")
        if not any(token in low for token in ("karriere", "career", "jobs", "stellen", "bewerbung")):
            continue
        host = (urlparse(url).hostname or "").lower()
        same = _same_site(url, website)
        is_ats = any(host == ats or host.endswith("." + ats) for ats in ATS_HOSTS)
        if not same and not is_ats:
            continue
        if url in seen:
            continue
        seen.add(url)
        score = 100 if same else 90
        if "jobs" in low or "stellen" in low:
            score += 10
        scored.append((score, url))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [url for _, url in scored[:limit]]


def _deobfuscate_email_text(text: str) -> str:
    replacements = {
        "[at]": "@", "(at)": "@", "{at}": "@", " [aet] ": "@", " [ät] ": "@",
        "[dot]": ".", "(dot)": ".", "{dot}": ".",
    }
    for old, new in replacements.items():
        text = text.replace(old, new).replace(old.upper(), new)
    text = re.sub(r"\s+(?:at|aet|ät)\s+", "@", text, flags=re.I)
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
        local, _, domain = email.partition("@")
        if not local or not domain or domain in GENERIC_EMAIL_DOMAINS and local in BAD_EMAIL_PREFIXES:
            continue
        if local in BAD_EMAIL_PREFIXES or any(local.startswith(item) for item in BAD_EMAIL_PREFIXES):
            continue
        seen.add(email)
        output.append(email)
    return output


def _email_score(email: str, website_domain: str = "", person: str = "", trusted_site: bool = False) -> int:
    local, _, email_domain = email.lower().partition("@")
    if not local or not email_domain:
        return -999
    score = 0
    domain = root_domain("https://" + email_domain)
    website_root = root_domain(website_domain) or website_domain.lower().removeprefix("www.")
    if website_root:
        if domain == website_root or email_domain == website_root:
            score += 70
        elif trusted_site:
            score += 5
        else:
            return -999
    person_tokens = [t for t in normalize(person).split() if len(t) >= 2 and t not in {"herr", "frau", "dr", "prof"}]
    if person_tokens:
        last = person_tokens[-1]
        first = person_tokens[0]
        local_norm = normalize(local).replace(" ", "")
        if last and last in local_norm:
            score += 55
            if first and (first in local_norm or local_norm.startswith(first[:1] + last)):
                score += 20
    for prefix, points in EMAIL_PREFIX_SCORES.items():
        if local == prefix or local.startswith(prefix + ".") or local.startswith(prefix + "-"):
            score += points
    if "." in local and not any(char.isdigit() for char in local):
        score += 20
    if local.startswith("info") or local.startswith("kontakt"):
        score -= 8
    return score


def choose_email(
    site_emails: Iterable[str],
    website_domain: str,
    person: str = "",
    fallback_emails: Iterable[str] | None = None,
) -> str:
    candidates: list[tuple[int, str]] = []
    for email in site_emails:
        candidates.append((_email_score(email, website_domain, person, trusted_site=True), email))
    for email in fallback_emails or []:
        candidates.append((_email_score(email, website_domain, person, trusted_site=False), email))
    candidates = [item for item in candidates if item[0] > -900]
    if not candidates:
        return ""
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1] if candidates[0][0] >= 0 else ""


def _looks_like_date(value: str) -> bool:
    text = clean_text(value)
    patterns = [
        r"^\d{1,2}[./-]\d{1,2}[./-](?:19|20)?\d{2}$",
        r"^(?:19|20)\d{2}[./-]\d{1,2}[./-]\d{1,2}$",
        r"^\d{1,2}\.\d{1,2}\.\d{2,4}$",
    ]
    return any(re.fullmatch(pattern, text) for pattern in patterns)


def valid_phone(value: str) -> bool:
    value = clean_text(value).strip(" .,:;-/")
    if not value or _looks_like_date(value):
        return False
    digits = re.sub(r"\D", "", value)
    if digits.startswith("0049"):
        digits = "49" + digits[4:]
    if not 9 <= len(digits) <= 15:
        return False
    # Jahreszahlen/Datumsfragmente und offensichtlich fortlaufende IDs vermeiden.
    if re.fullmatch(r"(?:19|20)\d{6,}", digits):
        return False
    return True


def extract_phones(html_text: str, page_text: str = "") -> list[str]:
    soup = BeautifulSoup(html_text or "", "html.parser")
    values: list[str] = []
    # tel:-Links sind die verlaesslichste Quelle.
    for anchor in soup.select('a[href^="tel:"]'):
        raw = unquote(anchor.get("href", "")[4:])
        if raw:
            values.append(raw)
    text = page_text or ""
    labeled = re.compile(
        r"(?i)(?:telefon|tel\.?|fon|phone|mobil|mobile|zentrale|durchwahl)\s*[:\-]?\s*"
        r"((?:\+49|0049|0)[\d\s()/.-]{7,24})"
    )
    for match in labeled.finditer(text):
        values.append(match.group(1))
    # +49/0049 ist auch ohne Label hinreichend eindeutig.
    values.extend(re.findall(r"(?:\+49|0049)[\d\s()/.-]{7,22}", text))

    output: list[str] = []
    seen_digits: set[str] = set()
    for value in values:
        value = re.sub(r"\s+", " ", clean_text(value)).strip(" .,:;-/")
        if not valid_phone(value):
            continue
        digits = re.sub(r"\D", "", value)
        if digits.startswith("0049"):
            digits = "49" + digits[4:]
        if digits in seen_digits:
            continue
        seen_digits.add(digits)
        output.append(value)
    return output


def _titlecase_word(word: str) -> bool:
    word = word.strip(".,;:()[]{}")
    if not word:
        return False
    if normalize(word) in NAME_CONNECTORS:
        return True
    if normalize(word) in TITLE_TOKENS:
        return True
    # Muss mit Grossbuchstaben beginnen; der Rest darf Bindestrich/Apostroph enthalten.
    return bool(re.fullmatch(r"[A-ZÄÖÜ][A-Za-zÄÖÜäöüß'’.-]{1,30}", word))


def valid_person_name(name: str) -> bool:
    name = clean_text(name).strip(" ,;:-")
    if not name or any(ch in name for ch in "!?=<>@/\\"):
        return False
    raw_parts = name.split()
    if not 2 <= len(raw_parts) <= 5:
        return False
    normalized_parts = [normalize(part) for part in raw_parts]
    if any(part in PERSON_BAD_TOKENS for part in normalized_parts if part):
        return False
    meaningful = [p for p in raw_parts if normalize(p) not in TITLE_TOKENS | NAME_CONNECTORS]
    if not 2 <= len(meaningful) <= 3:
        # Vier direkt aufeinanderfolgende Namen sind oft zwei Personen, z.B. "Max Mustermann Erika Beispiel".
        return False
    if not all(_titlecase_word(part) for part in raw_parts):
        return False
    # Mindestens Vor- und Nachname muessen wie Namen aussehen.
    if sum(1 for part in meaningful if re.match(r"^[A-ZÄÖÜ]", part)) < 2:
        return False
    return True


def _role_score(role: str) -> int:
    role_norm = normalize(role)
    return max([points for key, points in ROLE_SCORES.items() if normalize(key) in role_norm] or [0])


def _name_candidates(text: str) -> list[str]:
    # Bewusst case-sensitiv. Das verhindert Satzfragmente wie "Ihre Stellenanzeige landet direkt".
    token = r"[A-ZÄÖÜ][A-Za-zÄÖÜäöüß'’.-]{1,30}"
    connector = r"(?:von|van|de|der|den|zu|zur|zum|da|di)"
    title = r"(?:(?:Herr|Frau|Dr\.?|Prof\.?)\s+)?"
    pattern = rf"{title}{token}(?:\s+(?:{connector}\s+)?{token}){{1,2}}"
    output: list[str] = []
    for match in re.finditer(pattern, text):
        # Keine Teiltreffer aus vier aneinandergereihten Namen erzeugen.
        # Beispiel aus dem fehlerhaften Bestand: "Martin Dempf Sven Hesselbach".
        before = text[:match.start()].rstrip()
        after = text[match.end():].lstrip()
        if before and re.search(r"[A-ZÄÖÜ][A-Za-zÄÖÜäöüß'’.-]{1,30}$", before):
            continue
        if after and re.match(r"[A-ZÄÖÜ][A-Za-zÄÖÜäöüß'’.-]{1,30}(?:\s|$)", after):
            continue
        output.append(match.group(0))
    return output


def extract_people(page_text: str) -> list[tuple[str, str, int]]:
    if not page_text:
        return []
    raw_lines = [clean_text(line) for line in re.split(r"[\r\n]+|\s{3,}", str(page_text))]
    raw_lines = [line for line in raw_lines if line]
    # Pro Person nur die strukturell plausibelste Rollen-Zuordnung behalten.
    best_by_name: dict[str, tuple[str, str, int, int]] = {}

    for index, line in enumerate(raw_lines):
        role_match = re.search(ROLE_PATTERN, line, re.I)
        if not role_match:
            continue
        role = clean_text(role_match.group(0))
        windows: list[tuple[str, int]] = [(line, 30)]
        if index + 1 < len(raw_lines) and not re.search(ROLE_PATTERN, raw_lines[index + 1], re.I):
            windows.append((raw_lines[index + 1], 20))  # Rolle -> Name
        if index > 0 and not re.search(ROLE_PATTERN, raw_lines[index - 1], re.I):
            windows.append((raw_lines[index - 1], 15))  # Name -> Rolle

        for candidate_line, structure_score in windows:
            cleaned_line = re.sub(ROLE_PATTERN, " ", candidate_line, flags=re.I)
            for name in _name_candidates(cleaned_line):
                name = clean_text(name).strip(" ,;:-")
                if not valid_person_name(name):
                    continue
                key = name.lower()
                role_score = _role_score(role)
                ranking = structure_score * 10 + role_score
                previous = best_by_name.get(key)
                if previous is None or ranking > previous[3]:
                    best_by_name[key] = (name, role, role_score, ranking)

    output = [(name, role, role_score) for name, role, role_score, _ in best_by_name.values()]
    output.sort(key=lambda item: item[2], reverse=True)
    return output

def extract_employee_hint(text: str) -> str:
    values: list[int] = []
    for pattern in (
        r"(?:über|mehr als|rund|ca\.?|circa)?\s*(\d{2,5})\s+(?:Mitarbeitende|Mitarbeiter(?:innen)?|Beschäftigte)",
        r"Team\s+(?:von|mit)\s+(\d{2,5})",
    ):
        for match in re.finditer(pattern, clean_text(text), re.I):
            try:
                values.append(int(match.group(1)))
            except ValueError:
                pass
    return str(max(values)) if values else ""


def extract_location_hint(text: str) -> str:
    values: list[int] = []
    for pattern in (r"(\d{1,3})\s+Standorte", r"an\s+(\d{1,3})\s+Standorten", r"(\d{1,3})\s+Niederlassungen"):
        for match in re.finditer(pattern, clean_text(text), re.I):
            try:
                values.append(int(match.group(1)))
            except ValueError:
                pass
    return str(max(values)) if values else ""


def extract_jobposting_titles(html_text: str) -> list[str]:
    soup = BeautifulSoup(html_text or "", "html.parser")
    titles: list[str] = []

    def walk(value: Any):
        if isinstance(value, dict):
            t = value.get("@type")
            if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
                title = clean_text(value.get("title", ""))
                if title:
                    titles.append(title)
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)

    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text(" ")
        if not raw.strip():
            continue
        try:
            walk(json.loads(raw))
        except Exception:
            continue
    return list(dict.fromkeys(titles))


def career_signal_from_text(text: str, career_page: str = "") -> str:
    low = normalize(text[:50000])
    if any(term in low for term in ("offene stellen", "stellenangebote", "jetzt bewerben", "bewerben sie sich", "join our team")):
        return "Aktueller Personalbedarf auf eigener Karrierequelle erkennbar"
    if career_page:
        return "Karrierebereich vorhanden, konkrete Vakanz noch nicht strukturiert bestaetigt"
    return "Kein oeffentlicher Personalbedarf auf Firmenquelle bestaetigt"


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
    career_signal: str = ""
    career_job_count: int = 0
    career_job_titles: str = ""
    ats_detected: str = ""
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
            "career_signal": self.career_signal,
            "career_job_count": self.career_job_count,
            "career_job_titles": self.career_job_titles,
            "ats_detected": self.ats_detected,
            "pages_crawled": self.pages_crawled,
            "candidate_count": self.candidate_count,
            "errors": self.errors,
        }


def research_company(
    *,
    company: str,
    city: str = "",
    source_urls: Iterable[str] | None = None,
    source_text: str = "",
    serpapi_key: str = "",
    max_pages: int = 20,
) -> dict[str, Any]:
    result = ResearchResult()
    session = _session()
    source_emails = extract_emails("", source_text)
    source_phones = extract_phones("", source_text)
    source_people = extract_people(source_text)

    website, candidates, errors = discover_official_website(
        company=company,
        city=city,
        source_urls=source_urls,
        serpapi_key=serpapi_key,
        session=session,
    )
    result.candidate_count = len(candidates)
    result.errors.extend(errors[:8])
    result.website = website

    if not website:
        # Ohne verifizierte Firmenwebsite nur streng extrahierte Angaben aus dem eigentlichen Jobkontext verwenden.
        result.phone = source_phones[0] if source_phones else ""
        if source_people:
            result.person, result.role, _ = source_people[0]
        result.email = choose_email([], "", result.person, source_emails)
        result.status = "teilweise" if (result.email or result.phone or result.person) else "nicht gefunden"
        result.notes = "Keine sicher passende Firmenwebsite gefunden. Nur streng validierte Kontaktdaten aus der Stellenquelle wurden uebernommen."
        if errors:
            result.notes += " " + " | ".join(errors[:2])
        return result.as_dict()

    first, error = _safe_get(session, website, timeout=20)
    if error or not first:
        result.status = "teilweise"
        result.notes = f"Firmenwebsite erkannt, Abruf aber blockiert oder nicht erreichbar: {error}."
        return result.as_dict()

    website = homepage_from_url(first.url)
    result.website = website
    page_urls = collect_internal_pages(website, first.text, max_pages=max_pages)
    career_links = extract_career_links(website, first.text, limit=10)
    internal_career_links = [url for url in career_links if _same_site(url, website)]
    external_career_links = [url for url in career_links if not _same_site(url, website)]
    for url in internal_career_links:
        if url not in page_urls:
            page_urls.insert(1, url)
    page_urls = page_urls[:max_pages]
    if career_links:
        result.career_page = career_links[0]

    ats_hosts = sorted({
        (urlparse(url).hostname or "").lower()
        for url in career_links
        if any((urlparse(url).hostname or "").lower().endswith(host) for host in ATS_HOSTS)
    })
    if ats_hosts:
        result.ats_detected = ", ".join(ats_hosts[:3])

    site_emails: list[str] = []
    site_phones: list[str] = []
    site_people: list[tuple[str, str, int]] = []
    all_texts: list[str] = []
    career_job_titles: list[str] = []
    visited: set[str] = set()

    for page_url in page_urls:
        if page_url in visited:
            continue
        visited.add(page_url)
        response = first if page_url.rstrip("/") == website.rstrip("/") else None
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
        site_emails.extend(extract_emails(response.text, page_text))
        site_phones.extend(extract_phones(response.text, page_text))
        site_people.extend(extract_people(page_text))
        for title in extract_jobposting_titles(response.text):
            if title.lower() not in {value.lower() for value in career_job_titles}:
                career_job_titles.append(title)
        low_url = normalize(response.url)
        if not result.contact_page and any(term in low_url for term in ("kontakt", "contact")):
            result.contact_page = response.url
        if not result.imprint_page and any(term in low_url for term in ("impressum", "imprint")):
            result.imprint_page = response.url
        if not result.career_page and any(term in low_url for term in ("karriere", "career", "jobs", "stellen")):
            result.career_page = response.url

    for career_url in external_career_links[:4]:
        response, error = _safe_get(session, career_url, timeout=18)
        if error or not response:
            continue
        page_text = BeautifulSoup(response.text, "html.parser").get_text("\n")
        clean_page = clean_text(page_text)
        if clean_page:
            all_texts.append(clean_page[:20000])
        # Externe ATS-Seiten duerfen Jobs liefern, aber keine Ansprechpartner/E-Mails fuer die Firma ueberschreiben.
        for title in extract_jobposting_titles(response.text):
            if title.lower() not in {value.lower() for value in career_job_titles}:
                career_job_titles.append(title)

    combined_text = " ".join(all_texts)
    result.text = combined_text[:50000]

    # Firmenwebsite hat Vorrang; Stellenquelle nur als Fallback.
    unique_site_phones = list(dict.fromkeys(site_phones))
    result.phone = unique_site_phones[0] if unique_site_phones else (source_phones[0] if source_phones else "")

    unique_people: dict[tuple[str, str], tuple[str, str, int]] = {}
    for person in site_people:
        unique_people[(person[0].lower(), person[1].lower())] = person
    people = list(unique_people.values())
    people.sort(key=lambda item: item[2], reverse=True)
    if people:
        result.person, result.role, _ = people[0]
    elif source_people:
        result.person, result.role, _ = source_people[0]

    result.email = choose_email(
        list(dict.fromkeys(site_emails)),
        root_domain(website),
        result.person,
        source_emails,
    )

    result.employee_hint = extract_employee_hint(combined_text)
    result.location_hint = extract_location_hint(combined_text)
    result.career_job_count = len(career_job_titles)
    result.career_job_titles = " | ".join(career_job_titles[:20])
    result.career_signal = career_signal_from_text(combined_text, result.career_page)
    if result.career_job_count:
        result.career_signal = f"{result.career_job_count} konkrete Stellen auf Firmen- oder ATS-Quelle erkannt"

    if result.website and result.pages_crawled >= 2:
        result.status = "vollständig" if (result.email or result.phone or result.person or result.career_job_count) else "teilweise"
    elif result.website:
        result.status = "teilweise"
    else:
        result.status = "nicht gefunden"

    found = []
    if result.website:
        found.append("Website")
    if result.career_page:
        found.append("Karriere")
    if result.person:
        found.append("Ansprechpartner")
    if result.email:
        found.append("E-Mail")
    if result.phone:
        found.append("Telefon")
    if result.career_job_count:
        found.append(f"{result.career_job_count} Jobs")
    result.notes = (
        "Strenge Recherche: " + ", ".join(found)
        if found else
        "Firmenwebsite geprueft, aber keine belastbaren Kontakt- oder Karrieredaten gefunden."
    )
    return result.as_dict()
