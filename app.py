
import base64
import hashlib
import re
import time
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
import streamlit as st
import tldextract
from bs4 import BeautifulSoup

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

# ============================================================
# KONFIGURATION
# ============================================================

API_BASE = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service"
API_HEADERS = {
    "X-API-Key": "jobboerse-jobsuche",
    "User-Agent": "Mozilla/5.0 (compatible; XING-Daily-Leads/1.0)",
}

DEFAULT_SEARCH_TERMS = [
    # Gesundheit & Therapie
    "Physiotherapeut",
    "Ergotherapeut",
    "Logopäde",
    "Pflegefachkraft",
    "Medizinische Fachangestellte",

    # Handwerk & Technik
    "Elektroniker",
    "Mechatroniker",
    "Anlagenmechaniker",
    "Schweißer",
    "Industriemechaniker",
    "Servicetechniker",

    # Bau & Engineering
    "Bauleiter",
    "Architekt",
    "Projektingenieur",
    "Elektroingenieur",
    "Konstrukteur",

    # IT
    "Softwareentwickler",
    "Systemadministrator",
    "IT Support",
    "DevOps Engineer",

    # Vertrieb & kaufmännisch
    "Vertriebsmitarbeiter",
    "Account Manager",
    "Sachbearbeiter",
    "Buchhalter",
    "Controller",

    # Steuer & Recht
    "Steuerfachangestellte",
    "Steuerfachwirt",
    "Bilanzbuchhalter",

    # Logistik
    "Berufskraftfahrer",
    "Disponent",
    "Fachkraft Lagerlogistik",
]

DEFAULT_REGIONS = [
    ("Münster", 100),
    ("Osnabrück", 100),
    ("Dortmund", 100),
    ("Bielefeld", 100),
]

LARGE_COMPANY_WORDS = [
    "deutsche bahn", "db ", "siemens", "bosch", "amazon", "lidl",
    "aldi", "rewe", "edeka", "thyssenkrupp", "telekom", "vodafone",
    "bundeswehr", "universitätsklinikum", "uniklinik", "stadt ",
    "landkreis", "ministerium", "sparkasse", "volksbank",
]

AGENCY_WORDS = [
    "zeitarbeit", "personalvermittlung", "personaldienstleistung",
    "personaldienstleister", "arbeitnehmerüberlassung", "staffing",
    "recruiting agency", "personalservice", "personal services",
    "professionals gmbh", "experts gmbh", "workforce", "work4",
    "randstad", "adecco", "manpower", "persona service", "tempton",
    "office people", "pluss personal", "persona data", "avitea",
    "piening", "meteor personaldienste", "actief personalmanagement",
    "persona service", "expertum", "dis ag", "dpl professionals",
]

BENEFIT_PATTERNS = {
    "Homeoffice": [r"\bhomeoffice\b", r"\bremote\b", r"mobiles arbeiten"],
    "Flexible Arbeitszeiten": [r"flexible arbeitszeit", r"gleitzeit"],
    "4-Tage-Woche": [r"4[\s-]*tage[\s-]*woche", r"vier[\s-]*tage[\s-]*woche"],
    "30+ Tage Urlaub": [r"\b3[0-9]\s*(tage|urlaubstage)"],
    "JobRad": [r"\bjobrad\b", r"dienstfahrrad", r"bikeleasing"],
    "Jobticket": [r"\bjobticket\b", r"deutschlandticket"],
    "Weiterbildung": [r"weiterbildung", r"fortbildung"],
    "Betriebliche Altersvorsorge": [r"altersvorsorge", r"\bbav\b"],
    "Bonus / Prämien": [r"\bbonus\b", r"prämie", r"sonderzahlung"],
    "Keine Wochenendarbeit": [r"keine wochenend", r"montag bis freitag"],
    "Keine Überstunden": [r"keine überstunden", r"überstundenausgleich"],
    "Unbefristet": [r"unbefristet"],
    "Digitale Arbeitsweise": [r"digitale kanzlei", r"datev unternehmen online"],
    "Familiäres Team": [r"familiär", r"teamzusammenhalt"],
}

STATUSES = [
    "Neu",
    "Mail vorbereitet",
    "Follow-up fällig",
    "Für morgen",
    "In Salesforce übernommen",
    "Ausschließen",
]

COLUMNS = [
    "lead_id", "firma", "hot_status", "lead_score", "warum_hot",
    "offene_stellen", "anzahl_stellen", "orte", "veroeffentlicht_am",
    "zuletzt_gefunden", "benefits", "ansprechpartner", "rolle",
    "email", "telefon", "website", "kontaktseite", "stellenlink",
    "crm_status", "erstmail_betreff", "erstmail", "call_opener", "discovery_fragen",
    "follow_up_1", "follow_up_2", "status", "wiedervorlage", "notiz",
]

MANUAL_COLUMNS = ["status", "wiedervorlage", "notiz"]


# ============================================================
# DATENHILFEN
# ============================================================

def clean_text(value):
    if value is None:
        return ""
    value = BeautifulSoup(str(value), "html.parser").get_text(" ")
    return re.sub(r"\s+", " ", value).strip()


def normalize_company(name):
    name = clean_text(name).lower()
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    patterns = [
        r"\bgmbh\s*&\s*co\.?\s*kg\b", r"\bgmbh\b", r"\bmbh\b",
        r"\bag\b", r"\bkg\b", r"\bohg\b", r"\bpartg\s*mbb\b",
        r"\bpartg\b", r"\be\.?\s*k\.?\b",
        r"\bsteuerberatungsgesellschaft\b",
    ]
    for pattern in patterns:
        name = re.sub(pattern, " ", name)
    name = re.sub(r"[^a-z0-9]+", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def lead_id(company):
    return hashlib.sha1(normalize_company(company).encode("utf-8")).hexdigest()[:14]


def safe_get(url, params=None, timeout=15):
    try:
        response = requests.get(
            url,
            params=params,
            headers=API_HEADERS,
            timeout=timeout,
            allow_redirects=True,
        )
        response.raise_for_status()
        return response
    except requests.RequestException:
        return None


def first_value(data, keys):
    for key in keys:
        value = data.get(key)
        if value not in (None, "", [], {}):
            return value
    return ""


def nested(data, *keys):
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return ""
        current = current.get(key, "")
    return current or ""


def unique(values):
    result, seen = [], set()
    for value in values:
        value = clean_text(value)
        if value and value.lower() not in seen:
            seen.add(value.lower())
            result.append(value)
    return result


def detect_benefits(text):
    text = clean_text(text).lower()
    return [
        benefit for benefit, patterns in BENEFIT_PATTERNS.items()
        if any(re.search(pattern, text, re.I) for pattern in patterns)
    ]


def likely_large_or_agency(company):
    low = f" {company.lower()} "
    if any(word in low for word in AGENCY_WORDS):
        return "Vermittler"
    if any(word in low for word in LARGE_COMPANY_WORDS):
        return "Großunternehmen"
    return ""


# ============================================================
# SPEICHERUNG: GOOGLE SHEETS ODER LOKALER TESTMODUS
# ============================================================

class Storage:
    def __init__(self):
        self.mode = "local"
        self.ws = None
        self.exclusion_ws = None
        self.local_path = "leads_local.csv"
        self.local_exclusion_path = "crm_ausschluss_local.csv"

        if gspread and "gcp_service_account" in st.secrets and "spreadsheet_name" in st.secrets:
            try:
                creds = Credentials.from_service_account_info(
                    dict(st.secrets["gcp_service_account"]),
                    scopes=[
                        "https://www.googleapis.com/auth/spreadsheets",
                        "https://www.googleapis.com/auth/drive",
                    ],
                )
                client = gspread.authorize(creds)
                book = client.open(st.secrets["spreadsheet_name"])
                self.ws = self._sheet(book, "Leads", 5000, 40)
                self.exclusion_ws = self._sheet(book, "CRM_Ausschluss", 5000, 5)
                self.mode = "google"
            except Exception as exc:
                st.sidebar.warning(f"Google Sheets nicht verbunden: {exc}")

    @staticmethod
    def _sheet(book, title, rows, cols):
        names = [ws.title for ws in book.worksheets()]
        if title in names:
            return book.worksheet(title)
        return book.add_worksheet(title=title, rows=rows, cols=cols)

    def load(self):
        if self.mode == "google":
            values = self.ws.get_all_records()
            return pd.DataFrame(values, columns=COLUMNS) if values else pd.DataFrame(columns=COLUMNS)
        try:
            return pd.read_csv(self.local_path, dtype=str).fillna("")
        except FileNotFoundError:
            return pd.DataFrame(columns=COLUMNS)

    def save(self, df):
        df = df.reindex(columns=COLUMNS).fillna("")
        if self.mode == "google":
            self.ws.clear()
            self.ws.update([COLUMNS] + df.astype(str).values.tolist())
            self.ws.freeze(rows=1)
        else:
            df.to_csv(self.local_path, index=False)

    def load_exclusions(self):
        if self.mode == "google":
            values = self.exclusion_ws.get_all_records()
            if not values:
                return set()
            return {
                normalize_company(row.get("firma", ""))
                for row in values
                if row.get("firma")
            }
        try:
            df = pd.read_csv(self.local_exclusion_path, dtype=str).fillna("")
            return {normalize_company(v) for v in df.get("firma", [])}
        except FileNotFoundError:
            return set()

    def save_exclusions(self, companies):
        rows = sorted({c for c in companies if c})
        if self.mode == "google":
            self.exclusion_ws.clear()
            self.exclusion_ws.update([["firma"]] + [[c] for c in rows])
            self.exclusion_ws.freeze(rows=1)
        else:
            pd.DataFrame({"firma": rows}).to_csv(self.local_exclusion_path, index=False)


storage = Storage()


def read_company_file(uploaded_file):
    """Liest Salesforce-Exporte aus CSV oder XLSX und erkennt die Firmenspalte."""
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
        "company", "name des accounts", "kunde", "kundenname"
    ]
    normalized_columns = {normalize_company(col): col for col in frame.columns}
    company_col = next(
        (original for normalized, original in normalized_columns.items()
         if any(alias in normalized for alias in aliases)),
        None,
    )
    if not company_col:
        raise ValueError(
            "Keine Firmenspalte erkannt. Benenne sie z. B. 'Account Name', 'Firma' oder 'Unternehmen'."
        )
    companies = {
        normalize_company(value)
        for value in frame[company_col].astype(str)
        if normalize_company(value)
    }
    return companies, company_col, len(frame)


def apply_crm_status(frame, exclusions):
    if frame.empty:
        return frame
    frame = frame.copy()
    normalized = frame["firma"].map(normalize_company)
    frame["crm_status"] = normalized.map(
        lambda value: "Bereits in Salesforce" if value in exclusions else "Neu"
    )
    return frame


# ============================================================
# BA-JOBFINDER
# ============================================================

def fetch_search(term, city, radius, days, max_pages):
    jobs = []
    for page in range(1, max_pages + 1):
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
        response = safe_get(f"{API_BASE}/pc/v6/jobs", params=params)
        if not response:
            break
        payload = response.json()
        batch = payload.get("stellenangebote") or payload.get("jobs") or []
        if not batch:
            break
        for item in batch:
            item["_term"] = term
            jobs.append(item)
        if len(batch) < 25:
            break
        time.sleep(0.1)
    return jobs


def fetch_details(reference):
    if not reference:
        return {}
    encoded = base64.b64encode(reference.encode("utf-8")).decode("utf-8")
    response = safe_get(f"{API_BASE}/pc/v4/jobdetails/{encoded}")
    return response.json() if response else {}


def parse_job(raw):
    reference = clean_text(first_value(raw, ["referenznummer", "refnr", "refNr"]))
    details = fetch_details(reference)

    company = clean_text(
        first_value(raw, ["arbeitgeber", "arbeitgeberName", "firma"])
        or first_value(details, ["arbeitgeber", "arbeitgeberName", "firmenname"])
    )
    title = clean_text(
        first_value(raw, ["titel", "stellenangebotsTitel", "beruf"])
        or first_value(details, ["stellenangebotsTitel", "titel"])
    )
    description = clean_text(
        first_value(details, [
            "stellenangebotsBeschreibung", "stellenbeschreibung", "beschreibung"
        ])
    )
    city = clean_text(
        nested(raw, "arbeitsort", "ort")
        or nested(details, "arbeitsort", "ort")
        or first_value(raw, ["arbeitsort", "ort"])
    )
    published = clean_text(
        first_value(raw, [
            "veroeffentlichungsdatum", "veroeffentlichtAm",
            "modifikationsTimestamp",
        ])
    )[:10]
    external_url = clean_text(
        first_value(raw, ["externeUrl", "externeURL", "url"])
        or first_value(details, ["externeUrl", "externeURL", "url"])
    )
    ba_link = (
        f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{reference}"
        if reference else ""
    )
    email = clean_text(
        first_value(details, ["email", "eMail", "kontaktEmail"])
        or nested(details, "hauptkontakt", "email")
    )
    phone = clean_text(
        first_value(details, ["telefon", "telefonnummer", "kontaktTelefon"])
        or nested(details, "hauptkontakt", "telefon")
    )
    contact = clean_text(
        first_value(details, ["ansprechpartner", "kontaktName"])
        or nested(details, "hauptkontakt", "name")
    )

    return {
        "reference": reference,
        "company": company,
        "title": title,
        "description": description,
        "city": city,
        "published": published,
        "external_url": external_url,
        "job_link": external_url or ba_link,
        "email": email,
        "phone": phone,
        "contact": contact,
        "term": raw.get("_term", ""),
    }


# ============================================================
# WEBSITE-RECHERCHE
# ============================================================


BLOCKED_JOB_DOMAINS = {
    "adzuna.de", "adzuna.com", "indeed.com", "indeed.de", "stepstone.de",
    "linkedin.com", "xing.com", "arbeitsagentur.de", "meinestadt.de",
    "stellenanzeigen.de", "jobware.de", "kimeta.de", "jooble.org",
    "glassdoor.de", "monster.de", "talent.com", "jobrapido.com",
}

def homepage_from_url(url):
    if not url:
        return ""
    parsed = urlparse(url if "://" in url else "https://" + url)
    return f"{parsed.scheme or 'https'}://{parsed.netloc}" if parsed.netloc else ""


def root_domain(url):
    parsed = urlparse(url if "://" in url else "https://" + url)
    ext = tldextract.extract(parsed.netloc)
    return f"{ext.domain}.{ext.suffix}" if ext.domain and ext.suffix else ""


def is_blocked_job_url(url):
    domain = root_domain(url).lower()
    return any(domain == blocked or domain.endswith("." + blocked) for blocked in BLOCKED_JOB_DOMAINS)


def company_tokens(company):
    stop = {
        "gmbh", "ag", "kg", "mbh", "co", "und", "der", "die", "das",
        "gruppe", "group", "holding", "gesellschaft", "service", "services"
    }
    return [
        token for token in normalize_company(company).split()
        if len(token) >= 3 and token not in stop
    ]


def website_matches_company(url, company):
    domain = root_domain(url).split(".")[0].replace("-", " ")
    tokens = company_tokens(company)
    return bool(tokens) and any(token in domain for token in tokens[:4])


def extract_emails(text):
    return unique(re.findall(
        r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}",
        text or "",
        re.I,
    ))


def choose_email(emails, domain):
    bad = ("noreply@", "no-reply@", "datenschutz@", "privacy@")
    emails = [e for e in emails if not e.lower().startswith(bad)]
    same = [e for e in emails if domain and e.lower().endswith("@" + domain.lower())]
    pool = same or emails
    if not pool:
        return ""
    preferred = (
        "personal@", "karriere@", "bewerbung@", "recruiting@", "jobs@",
        "info@", "kontakt@", "office@"
    )
    for prefix in preferred:
        match = next((e for e in pool if e.lower().startswith(prefix)), "")
        if match:
            return match
    return pool[0]


def extract_phone(text):
    matches = re.findall(r"(?:\+49|0)[\d\s()/.\-]{7,}", text or "")
    for match in matches:
        cleaned = clean_text(match).strip(" .-/")
        digits = re.sub(r"\D", "", cleaned)
        if 8 <= len(digits) <= 16:
            return cleaned
    return ""


def find_person(text):
    text = clean_text(text)
    role_words = (
        r"Geschäftsführer(?:in)?|Inhaber(?:in)?|Personalleiter(?:in)?|"
        r"Personalreferent(?:in)?|Recruiter(?:in)?|Recruiting|HR(?: Manager)?|"
        r"Talent Acquisition|Praxisinhaber(?:in)?|Kanzleiinhaber(?:in)?"
    )
    patterns = [
        rf"(?:Ansprechpartner(?:in)?|Kontakt(?:person)?)\s*:?\s*"
        rf"([A-ZÄÖÜ][a-zäöüß\-]+(?:\s+[A-ZÄÖÜ][a-zäöüß\-]+){{1,2}})"
        rf"(?:\s*[,|–-]\s*({role_words}))?",
        rf"([A-ZÄÖÜ][a-zäöüß\-]+(?:\s+[A-ZÄÖÜ][a-zäöüß\-]+){{1,2}})"
        rf"\s*(?:–|-|\||,)\s*({role_words})",
        rf"({role_words})\s*:?\s*"
        rf"([A-ZÄÖÜ][a-zäöüß\-]+(?:\s+[A-ZÄÖÜ][a-zäöüß\-]+){{1,2}})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            groups = [g for g in match.groups() if g]
            if groups:
                if re.search(role_words, groups[0], re.I):
                    return groups[1] if len(groups) > 1 else "", groups[0]
                return groups[0], groups[1] if len(groups) > 1 else ""
    return "", ""


def discover_official_website(company, city="", serpapi_key=""):
    """
    Sucht die echte Firmenwebsite. SerpApi wird bevorzugt, danach DuckDuckGo.
    Jobbörsen werden konsequent verworfen.
    """
    query = f'"{company}" {city} offizielle Website Kontakt'.strip()
    candidates = []

    if serpapi_key:
        response = safe_get(
            "https://serpapi.com/search.json",
            params={"engine": "google", "q": query, "hl": "de", "gl": "de", "api_key": serpapi_key},
            timeout=25,
        )
        if response:
            try:
                for item in response.json().get("organic_results", [])[:10]:
                    link = item.get("link", "")
                    if link:
                        candidates.append(link)
            except ValueError:
                pass

    if not candidates:
        response = safe_get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            timeout=20,
        )
        if response:
            soup = BeautifulSoup(response.text, "html.parser")
            for anchor in soup.select("a.result__a, a.result-link"):
                href = anchor.get("href", "")
                if href:
                    candidates.append(href)

    cleaned = []
    for url in candidates:
        if not url.startswith("http") or is_blocked_job_url(url):
            continue
        homepage = homepage_from_url(url)
        if homepage and homepage not in cleaned:
            cleaned.append(homepage)

    # Erst exakte Domain-Nähe, danach erstes seriöses Ergebnis.
    for url in cleaned:
        if website_matches_company(url, company):
            return url
    return cleaned[0] if cleaned else ""


def collect_internal_pages(homepage, html):
    soup = BeautifulSoup(html, "html.parser")
    wanted = ("kontakt", "impressum", "karriere", "jobs", "team", "uber-uns", "ueber-uns", "unternehmen")
    pages = [homepage]
    for anchor in soup.find_all("a", href=True):
        href = urljoin(homepage, anchor["href"])
        if root_domain(href) != root_domain(homepage):
            continue
        low = href.lower()
        if any(term in low for term in wanted) and href not in pages:
            pages.append(href)
    # Fallbacks
    for suffix in ("/kontakt", "/impressum", "/karriere", "/jobs", "/team", "/ueber-uns"):
        url = urljoin(homepage, suffix)
        if url not in pages:
            pages.append(url)
    return pages[:10]


def research_site(company, city="", source_url="", serpapi_key=""):
    result = {
        "website": "", "contact_page": "", "email": "",
        "phone": "", "person": "", "role": "", "text": "",
    }

    # Ein Adzuna-/Jobbörsen-Link darf niemals als Firmenwebsite verwendet werden.
    homepage = ""
    if source_url and not is_blocked_job_url(source_url):
        candidate = homepage_from_url(source_url)
        if website_matches_company(candidate, company):
            homepage = candidate

    if not homepage:
        homepage = discover_official_website(company, city, serpapi_key)

    if not homepage or is_blocked_job_url(homepage):
        return result

    first = safe_get(homepage, timeout=20)
    if not first or "text/html" not in first.headers.get("content-type", ""):
        return result

    final_homepage = homepage_from_url(first.url)
    if is_blocked_job_url(final_homepage):
        return result

    candidates = collect_internal_pages(final_homepage, first.text)
    all_text, all_emails = [], []
    phone = person = role = contact_page = ""

    for url in candidates:
        response = first if url == homepage else safe_get(url, timeout=15)
        if not response or "text/html" not in response.headers.get("content-type", ""):
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()
        page_text = clean_text(soup.get_text(" "))
        all_text.append(page_text[:30000])
        all_emails.extend(extract_emails(response.text))
        all_emails.extend(extract_emails(page_text))
        if not phone:
            phone = extract_phone(page_text)
        if not person:
            person, role = find_person(page_text)
        if not contact_page and any(x in response.url.lower() for x in ("kontakt", "impressum", "karriere", "jobs")):
            contact_page = response.url

    domain = root_domain(final_homepage)
    result.update({
        "website": final_homepage,
        "contact_page": contact_page,
        "email": choose_email(unique(all_emails), domain),
        "phone": phone,
        "person": person,
        "role": role,
        "text": " ".join(all_text),
    })
    return result


# ============================================================
# SCORING + TEXTE
# ============================================================

def _job_family(title):
    """Ordnet Jobtitel grob einer Berufsgruppe zu."""
    value = normalize_company(title)
    families = {
        "Steuer & Finanzen": [
            "steuerfach", "bilanzbuch", "finanzbuch", "buchhalter",
            "controller", "lohn", "tax",
        ],
        "Therapie": [
            "physio", "ergotherapeut", "logop", "therapeut",
        ],
        "Pflege & Medizin": [
            "pflege", "medizinische fachang", "arzt", "ärzt", "mfa",
            "gesundheits", "kranken",
        ],
        "Elektro & Technik": [
            "elektroniker", "elektriker", "mechatron", "servicetechn",
            "sps", "automation",
        ],
        "Metall & Produktion": [
            "schlosser", "schwei", "industriemechan", "zerspan",
            "cnc", "monteur", "vorrichter", "metall",
        ],
        "Bau & Engineering": [
            "bauleiter", "architekt", "ingenieur", "konstrukteur",
            "projektleiter", "tiefbau", "hochbau",
        ],
        "IT": [
            "software", "entwickler", "developer", "devops",
            "systemadministrator", "it support", "informatik",
        ],
        "Vertrieb": [
            "vertrieb", "sales", "account manager", "business development",
        ],
        "Logistik": [
            "lager", "logistik", "stapler", "fahrer", "disponent",
            "verlader", "berufskraft",
        ],
        "Verwaltung": [
            "sachbearbeiter", "assistenz", "office", "personalreferent",
            "kaufmann", "kauffrau",
        ],
    }
    for family, keywords in families.items():
        if any(keyword in value for keyword in keywords):
            return family
    return "Sonstige"


def _agency_signal(company, jobs, research):
    combined = normalize_company(
        " ".join([
            company,
            research.get("website", ""),
            research.get("text", "")[:15000],
            " ".join(j.get("description", "")[:2500] for j in jobs),
        ])
    )
    hits = [word for word in AGENCY_WORDS if normalize_company(word) in combined]
    return len(hits) >= 1, hits[:3]


def score_lead(company, jobs, research, benefits):
    """
    V3-Scoring: Nicht die reine Stellenmenge zählt, sondern Qualität,
    Zielgruppen-Fokus, Kontaktierbarkeit und Direktkunden-Wahrscheinlichkeit.
    """
    score, reasons, penalties = 20, [], []
    count = len(jobs)
    titles = unique([j.get("title", "") for j in jobs if j.get("title")])
    families = [_job_family(title) for title in titles]
    family_counts = {}
    for family in families:
        family_counts[family] = family_counts.get(family, 0) + 1

    dominant_family = max(family_counts, key=family_counts.get) if family_counts else "Sonstige"
    dominant_share = (
        family_counts.get(dominant_family, 0) / max(1, len(families))
    )
    family_diversity = len(set(families))

    # Sinnvoller Recruiting-Druck: 2–8 Stellen sind für Direktkunden oft ideal.
    if 2 <= count <= 5:
        score += 22
        reasons.append(f"{count} konkrete Stellen")
    elif 6 <= count <= 10:
        score += 18
        reasons.append(f"{count} offene Stellen")
    elif count == 1:
        score += 10
        reasons.append("frische Einzelstelle")
    elif count > 10:
        score += 8
        penalties.append("sehr viele Ausschreibungen")

    # Ähnliche Profile sind wertvoller als ein komplett gemischtes Jobportfolio.
    if len(titles) >= 2 and dominant_share >= 0.65:
        score += 20
        reasons.append(f"klarer Schwerpunkt: {dominant_family}")
    elif family_diversity <= 2:
        score += 12
        reasons.append("zusammenhängende Zielprofile")
    elif family_diversity >= 5:
        score -= 22
        penalties.append(f"{family_diversity} stark gemischte Berufsgruppen")

    # Für XING besonders interessante Zielgruppen.
    priority_bonus = {
        "Therapie": 18,
        "Steuer & Finanzen": 17,
        "Pflege & Medizin": 15,
        "Elektro & Technik": 13,
        "Bau & Engineering": 12,
        "IT": 12,
        "Metall & Produktion": 9,
        "Vertrieb": 8,
        "Logistik": 5,
        "Verwaltung": 4,
        "Sonstige": 0,
    }
    bonus = priority_bonus.get(dominant_family, 0)
    if bonus:
        score += bonus
        reasons.append(f"passende Zielgruppe: {dominant_family}")

    email = research.get("email") or next(
        (j.get("email", "") for j in jobs if j.get("email")), ""
    )
    person = research.get("person") or next(
        (j.get("contact", "") for j in jobs if j.get("contact")), ""
    )
    phone = research.get("phone") or next(
        (j.get("phone", "") for j in jobs if j.get("phone")), ""
    )

    if person:
        score += 13
        reasons.append("Ansprechpartner vorhanden")
    if email:
        score += 9
        reasons.append("E-Mail vorhanden")
    if phone:
        score += 8
        reasons.append("Telefon vorhanden")

    if len(benefits) >= 4:
        score += 12
        reasons.append("starke Benefits")
    elif len(benefits) >= 2:
        score += 7
        reasons.append("mehrere Benefits")

    is_agency, agency_hits = _agency_signal(company, jobs, research)
    if is_agency:
        score -= 55
        penalties.append("wahrscheinlich Personaldienstleister")

    # Extrem viele, völlig unterschiedliche Ausschreibungen sind ein starkes Warnsignal.
    if count >= 20 and family_diversity >= 4:
        score -= 25
        penalties.append("Massenanzeigen aus vielen Bereichen")

    score = max(0, min(int(score), 100))
    status = "HOT" if score >= 75 else "WARM" if score >= 55 else "COLD"

    explanation = reasons[:5]
    if penalties:
        explanation.extend(f"Abzug: {item}" for item in penalties[:3])
    return status, score, ", ".join(explanation)


def greeting(person):
    if not person:
        return "Guten Tag,"
    return f"Guten Tag Herr/Frau {person.split()[-1]},"


def create_texts(company, jobs, benefits, person):
    titles = unique([j["title"] for j in jobs])
    title_short = titles[0] if titles else "Fachkräften"
    title_list = ", ".join(titles[:2])

    if benefits:
        opening = (
            f"bei Ihrer aktuellen Personalsuche ist mir aufgefallen, dass Sie mit "
            f"{', '.join(benefits[:3])} bereits einiges bieten."
        )
    else:
        opening = f"ich bin auf Ihre aktuelle Suche nach {title_list} aufmerksam geworden."

    mail = f"""{greeting(person)}

{opening}

Läuft die Besetzung aktuell so, wie Sie es sich vorgestellt haben?

Ich möchte Ihnen an dieser Stelle nichts pauschal anbieten. Mich würde zunächst interessieren, welche Position aktuell am meisten drückt, was Sie bereits versuchen und wo es dabei noch hakt.

Falls das Thema relevant ist, reichen dafür 10 bis 15 Minuten.

Viele Grüße

Berkant Devrim
Account Executive | XING"""

    opener = (
        f"Guten Tag, Berkant Devrim von XING. Ich komme direkt zum Punkt: "
        f"Ich habe gesehen, dass Sie aktuell {title_list} suchen. "
        "Läuft die Besetzung so, wie Sie es sich vorgestellt haben?"
    )

    questions = "\n".join([
        "1. Welche Position drückt aktuell am meisten?",
        "2. Seit wann suchen Sie bereits konkret?",
        "3. Welche Kanäle nutzen Sie bisher?",
        "4. Fehlt es eher an Bewerbungen oder an passender Qualität?",
        "5. Was passiert intern, wenn die Stelle länger offen bleibt?",
        "6. Bis wann müsste die Position idealerweise besetzt sein?",
    ])

    follow1 = f"""Guten Tag,

ich wollte meine kurze Frage zur aktuellen Personalsuche bei {company} noch einmal aufgreifen.

Mich interessiert nicht, ob grundsätzlich Bewerbungen eingehen, sondern ob Sie die passenden Fachkräfte aktuell zuverlässig erreichen.

Falls die Besetzung noch offen ist, können wir uns dazu gerne 10 Minuten austauschen.

Viele Grüße
Berkant Devrim"""

    follow2 = f"""Guten Tag,

ich melde mich ein letztes Mal wegen Ihrer aktuellen Suche nach {title_list}.

Sollte das Thema inzwischen gelöst sein, hake ich es gerne ab. Falls die Position weiterhin offen ist, würde mich interessieren, woran die Besetzung momentan konkret scheitert.

Viele Grüße
Berkant Devrim"""

    return {
        "erstmail_betreff": f"Kurze Frage zu Ihrer Suche nach {title_short}",
        "erstmail": mail,
        "call_opener": opener,
        "discovery_fragen": questions,
        "follow_up_1": follow1,
        "follow_up_2": follow2,
    }


def build_leads(parsed_jobs, exclusions, max_research, serpapi_key=''):
    groups = defaultdict(list)
    for job in parsed_jobs:
        key = normalize_company(job["company"])
        if key and key not in exclusions:
            groups[key].append(job)

    rows = []
    for idx, jobs in enumerate(groups.values()):
        company = jobs[0]["company"]
        classification = likely_large_or_agency(company)
        if classification:
            continue

        start_url = next((j["external_url"] for j in jobs if j["external_url"]), "")
        city = next((j["city"] for j in jobs if j["city"]), "")
        research = research_site(
            company=company,
            city=city,
            source_url=start_url,
            serpapi_key=serpapi_key,
        ) if idx < max_research else {
            "website": "", "contact_page": "",
            "email": "", "phone": "", "person": "", "role": "", "text": "",
        }

        benefits = unique(
            detect_benefits(" ".join(j["description"] for j in jobs))
            + detect_benefits(research.get("text", ""))
        )
        hot, score, reason = score_lead(company, jobs, research, benefits)
        texts = create_texts(company, jobs, benefits, research.get("person", ""))

        family_summary = {}
        for job in jobs:
            family = _job_family(job.get("title", ""))
            family_summary[family] = family_summary.get(family, 0) + 1
        grouped_jobs = ", ".join(
            f"{amount}× {family}"
            for family, amount in sorted(
                family_summary.items(), key=lambda item: item[1], reverse=True
            )[:4]
        )

        row = {
            "lead_id": lead_id(company),
            "firma": company,
            "hot_status": hot,
            "lead_score": score,
            "warum_hot": reason,
            "offene_stellen": grouped_jobs or " | ".join(unique([j["title"] for j in jobs])[:5]),
            "anzahl_stellen": len(jobs),
            "orte": " | ".join(unique([j["city"] for j in jobs])),
            "veroeffentlicht_am": max([j["published"] for j in jobs if j["published"]] or [""]),
            "zuletzt_gefunden": date.today().isoformat(),
            "benefits": " | ".join(benefits),
            "ansprechpartner": research.get("person") or next((j["contact"] for j in jobs if j["contact"]), ""),
            "rolle": research.get("role", ""),
            "email": research.get("email") or next((j["email"] for j in jobs if j["email"]), ""),
            "telefon": research.get("phone") or next((j["phone"] for j in jobs if j["phone"]), ""),
            "website": research.get("website", ""),
            "kontaktseite": research.get("contact_page", ""),
            "stellenlink": next((j["job_link"] for j in jobs if j["job_link"]), ""),
            "crm_status": "Neu / nicht abgeglichen",
            **texts,
            "status": "Neu",
            "wiedervorlage": (date.today() + timedelta(days=1)).isoformat(),
            "notiz": "",
        }
        rows.append(row)

    return pd.DataFrame(rows, columns=COLUMNS)


def upsert(existing, fresh):
    if existing.empty:
        return fresh.copy(), len(fresh), 0

    existing = existing.reindex(columns=COLUMNS).fillna("")
    fresh = fresh.reindex(columns=COLUMNS).fillna("")
    existing_map = {row["lead_id"]: row.to_dict() for _, row in existing.iterrows()}

    inserted = updated = 0
    for _, row in fresh.iterrows():
        item = row.to_dict()
        lid = item["lead_id"]
        if lid in existing_map:
            old = existing_map[lid]
            for col in MANUAL_COLUMNS:
                if old.get(col, ""):
                    item[col] = old[col]
            existing_map[lid] = item
            updated += 1
        else:
            existing_map[lid] = item
            inserted += 1

    merged = pd.DataFrame(existing_map.values(), columns=COLUMNS)
    merged["lead_score_num"] = pd.to_numeric(merged["lead_score"], errors="coerce").fillna(0)
    merged = merged.sort_values(
        ["lead_score_num", "firma"],
        ascending=[False, True],
    ).drop(columns=["lead_score_num"])
    return merged, inserted, updated


# ============================================================
# UI
# ============================================================

st.sidebar.title("XING Daily Leads")
page = st.sidebar.radio(
    "Bereich",
    ["Daily Leads", "Follow-ups", "Alle Leads", "Salesforce-Abgleich", "CRM-Ausschluss"],
)

st.sidebar.caption(
    "Speicher: Google Sheets" if storage.mode == "google"
    else "Speicher: lokaler Testmodus"
)

df = storage.load().reindex(columns=COLUMNS).fillna("")
exclusions = storage.load_exclusions()

if page == "Daily Leads":
    st.title("Daily Leads")
    st.caption("Frische, eher kleine Direktkunden – vorrecherchiert und priorisiert.")

    with st.expander("Neue Leads suchen", expanded=df.empty):
        terms = st.text_area(
            "Suchbegriffe – eine Zeile je Begriff",
            "\n".join(DEFAULT_SEARCH_TERMS),
        )
        regions_text = st.text_area(
            "Regionen – Format: Ort,Umkreis",
            "\n".join(f"{city},{radius}" for city, radius in DEFAULT_REGIONS),
        )
        st.markdown("#### Quellen")
        source_cols = st.columns(4)
        use_adzuna = source_cols[0].checkbox(
            "Adzuna",
            value=True,
            help="Automatische Jobsuche in Deutschland über deine hinterlegten Adzuna-Zugangsdaten.",
        )
        use_ba = source_cols[1].checkbox(
            "Bundesagentur",
            value=False,
            help="Optionale Zusatzquelle. Ist standardmäßig ausgeschaltet.",
        )
        use_google = source_cols[2].checkbox(
            "Google Jobs",
            value=("serpapi_key" in st.secrets),
            help="Benötigt zusätzlich einen SerpApi-Key in den Streamlit-Secrets.",
        )
        use_careers = source_cols[3].checkbox(
            "Karriereseiten / ATS",
            value=True,
        )

        career_urls_text = st.text_area(
            "Karriereseiten oder ATS-Boards – eine URL je Zeile",
            placeholder=(
                "https://firma.jobs.personio.de\n"
                "https://boards.greenhouse.io/firma\n"
                "https://jobs.lever.co/firma\n"
                "https://firma.de/karriere"
            ),
            help="Personio, Greenhouse, Lever und JobPosting-Daten werden automatisch erkannt.",
        )

        col1, col2, col3 = st.columns(3)
        days = col1.number_input("Veröffentlicht seit Tagen", 1, 30, 7)
        max_pages = col2.number_input("Seiten pro BA-Suche", 1, 10, 1)
        max_research = col3.number_input("Websites recherchieren", 0, 100, 15)

        uploaded = st.file_uploader(
            "Optional: Salesforce-CSV hochladen – Firmen werden künftig ausgeschlossen",
            type=["csv"],
        )

        if uploaded is not None:
            try:
                crm = pd.read_csv(uploaded, dtype=str).fillna("")
                company_col = st.selectbox("Spalte mit Firmennamen", crm.columns.tolist())
                if st.button("CRM-Firmen übernehmen"):
                    new_exclusions = set(exclusions)
                    new_exclusions.update(normalize_company(v) for v in crm[company_col] if v)
                    storage.save_exclusions(new_exclusions)
                    st.success(f"{len(new_exclusions)} CRM-Firmen gespeichert.")
                    st.rerun()
            except Exception as exc:
                st.error(f"CSV konnte nicht gelesen werden: {exc}")

        if st.button("Jetzt frische Leads laden", type="primary"):
            search_terms = [x.strip() for x in terms.splitlines() if x.strip()]
            regions = []
            for line in regions_text.splitlines():
                if not line.strip():
                    continue
                city, radius = line.rsplit(",", 1)
                regions.append((city.strip(), int(radius.strip())))

            active_sources = []
            if use_adzuna:
                active_sources.append("Adzuna")
            if use_ba:
                active_sources.append("Bundesagentur")
            if use_google:
                active_sources.append("Google Jobs")
            if use_careers:
                active_sources.append("Karriereseiten")

            if not active_sources:
                st.error("Bitte mindestens eine Quelle aktivieren.")
                st.stop()

            career_urls = [
                line.strip() for line in career_urls_text.splitlines()
                if line.strip()
            ]
            serpapi_key = str(st.secrets.get("serpapi_key", ""))
            adzuna_app_id = str(st.secrets.get("adzuna_app_id", ""))
            adzuna_api_key = str(st.secrets.get("adzuna_api_key", ""))

            if use_adzuna and (not adzuna_app_id or not adzuna_api_key):
                st.error(
                    "Adzuna ist aktiviert, aber die Zugangsdaten fehlen. "
                    "Prüfe in Streamlit unter Settings → Secrets die Einträge "
                    "adzuna_app_id und adzuna_api_key."
                )
                st.stop()

            progress = st.progress(0, text="Mehrquellen-Suche läuft …")
            parsed, diagnostics = scan_jobs(
                terms=search_terms,
                regions=regions,
                days=int(days),
                max_pages=int(max_pages),
                sources=active_sources,
                career_urls=career_urls,
                serpapi_key=serpapi_key,
                adzuna_app_id=adzuna_app_id,
                adzuna_api_key=adzuna_api_key,
            )
            progress.progress(0.75, text="Firmen werden gruppiert und recherchiert …")

            fresh = build_leads(parsed, exclusions, int(max_research), serpapi_key)
            merged, inserted, updated = upsert(df, fresh)
            storage.save(merged)
            df = apply_crm_status(storage.load(), exclusions)
            storage.save(df)
            progress.empty()

            st.success(
                f"{inserted} neue Firmen, {updated} bestehende Firmen aktualisiert."
            )
            st.write(f"Gefundene eindeutige Stellen: {len(parsed)}")
            st.write(f"Erstellte Firmen-Leads: {len(fresh)}")
            st.write(f"Gespeicherte Leads insgesamt: {len(merged)}")

            with st.expander("Technische Details"):
                for message in diagnostics:
                    st.write(f"• {message}")

            if fresh.empty:
                st.warning(
                    "Keine Firmen-Leads entstanden. Öffne die technischen Details direkt hier."
                )
            else:
                st.session_state["last_scan_ok"] = True
                st.info("Die Leads stehen direkt weiter unten auf dieser Seite.")

    if df.empty:
        st.info("Noch keine Leads vorhanden. Starte oben die erste Suche.")
    else:
        new_df = df[
            df["status"].isin(["Neu", "Für morgen", "Mail vorbereitet"])
            & (df["crm_status"] != "Bereits in Salesforce")
        ].copy()
        new_df["lead_score"] = pd.to_numeric(new_df["lead_score"], errors="coerce").fillna(0)
        new_df = new_df.sort_values("lead_score", ascending=False)

        hot_count = int((new_df["lead_score"] >= 75).sum())
        warm_count = int(((new_df["lead_score"] >= 55) & (new_df["lead_score"] < 75)).sum())
        observe_count = int((new_df["lead_score"] < 55).sum())
        contactable_count = int(
            ((new_df["email"] != "") | (new_df["telefon"] != "")).sum()
        )

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Heute anrufen", hot_count)
        c2.metric("Diese Woche", warm_count)
        c3.metric("Beobachten", observe_count)
        c4.metric("Kontaktierbar", contactable_count)

        view_mode = st.radio(
            "Arbeitsmodus",
            ["Heute wirklich anrufen", "HOT + WARM", "Alle neuen Leads"],
            horizontal=True,
        )
        if view_mode == "Heute wirklich anrufen":
            display_df = new_df[new_df["lead_score"] >= 75].head(30)
        elif view_mode == "HOT + WARM":
            display_df = new_df[new_df["lead_score"] >= 55].head(100)
        else:
            display_df = new_df.head(250)

        st.caption(
            f"{len(display_df)} Firmen werden angezeigt. "
            "Personaldienstleister und stark gemischte Massenanzeigen erhalten deutliche Abzüge."
        )

        for idx, row in display_df.iterrows():
            with st.container(border=True):
                top1, top2, top3 = st.columns([5, 2, 2])
                top1.subheader(row["firma"])
                top2.metric(row["hot_status"], int(float(row["lead_score"] or 0)))
                top3.write(row["veroeffentlicht_am"] or "Datum offen")

                st.write(f"**Stellenschwerpunkte:** {row['offene_stellen']}")
                st.write(f"**Warum interessant:** {row['warum_hot']}")
                if row["benefits"]:
                    st.write(f"**Benefits:** {row['benefits']}")

                a, b, c = st.columns(3)
                a.write(f"**Ansprechpartner:** {row['ansprechpartner'] or 'nicht sicher gefunden'}")
                b.write(f"**E-Mail:** {row['email'] or 'nicht gefunden'}")
                c.write(f"**Telefon:** {row['telefon'] or 'nicht gefunden'}")

                link_cols = st.columns(3)
                if row["website"]:
                    link_cols[0].link_button("Website", row["website"])
                if row["stellenlink"]:
                    link_cols[1].link_button("Stelle öffnen", row["stellenlink"])
                if row["kontaktseite"]:
                    link_cols[2].link_button("Kontaktseite", row["kontaktseite"])

                tabs = st.tabs(["Call", "Erstmail", "Follow-ups", "Bearbeiten"])
                with tabs[0]:
                    st.text_area("Call-Opener", row["call_opener"], height=120, key=f"call_{row['lead_id']}")
                    st.text_area("Discovery-Fragen", row["discovery_fragen"], height=190, key=f"disc_{row['lead_id']}")
                with tabs[1]:
                    st.text_input("Betreff", row["erstmail_betreff"], key=f"subj_{row['lead_id']}")
                    st.text_area("Mail", row["erstmail"], height=300, key=f"mail_{row['lead_id']}")
                with tabs[2]:
                    st.text_area("Follow-up 1", row["follow_up_1"], height=240, key=f"f1_{row['lead_id']}")
                    st.text_area("Follow-up 2", row["follow_up_2"], height=240, key=f"f2_{row['lead_id']}")
                with tabs[3]:
                    status = st.selectbox(
                        "Status", STATUSES,
                        index=STATUSES.index(row["status"]) if row["status"] in STATUSES else 0,
                        key=f"status_{row['lead_id']}",
                    )
                    due = st.date_input(
                        "Wiedervorlage",
                        value=pd.to_datetime(row["wiedervorlage"], errors="coerce").date()
                        if row["wiedervorlage"] else date.today() + timedelta(days=2),
                        key=f"due_{row['lead_id']}",
                    )
                    note = st.text_area("Kurze Arbeitsnotiz", row["notiz"], key=f"note_{row['lead_id']}")
                    if st.button("Speichern", key=f"save_{row['lead_id']}"):
                        df.loc[idx, "status"] = status
                        df.loc[idx, "wiedervorlage"] = due.isoformat()
                        df.loc[idx, "notiz"] = note
                        storage.save(df)
                        st.success("Gespeichert.")
                        st.rerun()

elif page == "Follow-ups":
    st.title("Follow-ups")
    today = date.today().isoformat()
    due_df = df[
        (df["wiedervorlage"] != "")
        & (df["wiedervorlage"] <= today)
        & (~df["status"].isin(["In Salesforce übernommen", "Ausschließen"]))
    ].copy()

    if due_df.empty:
        st.success("Keine Follow-ups fällig.")
    else:
        for idx, row in due_df.iterrows():
            with st.container(border=True):
                st.subheader(row["firma"])
                st.write(f"**Fällig:** {row['wiedervorlage']} · **Status:** {row['status']}")
                st.write(f"**Kontakt:** {row['ansprechpartner']} · {row['email']} · {row['telefon']}")
                st.text_area("Follow-up", row["follow_up_1"], height=240, key=f"due_mail_{row['lead_id']}")
                col1, col2 = st.columns(2)
                if col1.button("In Salesforce übernommen", key=f"sf_{row['lead_id']}"):
                    df.loc[idx, "status"] = "In Salesforce übernommen"
                    storage.save(df)
                    st.rerun()
                if col2.button("Noch 3 Tage", key=f"plus3_{row['lead_id']}"):
                    df.loc[idx, "wiedervorlage"] = (date.today() + timedelta(days=3)).isoformat()
                    storage.save(df)
                    st.rerun()

elif page == "Alle Leads":
    st.title("Alle Leads")
    search = st.text_input("Suche")
    filtered = df.copy()
    if search:
        mask = filtered.astype(str).apply(
            lambda col: col.str.contains(search, case=False, na=False)
        ).any(axis=1)
        filtered = filtered[mask]

    st.dataframe(
        filtered[[
            "hot_status", "lead_score", "firma", "crm_status",
            "anzahl_stellen", "offene_stellen", "orte",
            "ansprechpartner", "rolle", "email", "telefon",
            "website", "kontaktseite", "status",
            "wiedervorlage", "zuletzt_gefunden",
        ]],
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

elif page == "Salesforce-Abgleich":
    st.title("Salesforce-Abgleich")
    st.write(
        "Lade einen Salesforce-Account-Export als CSV oder XLSX hoch. "
        "Bereits vorhandene Firmen werden dauerhaft in die Ausschlussliste übernommen "
        "und bei neuen Scans nicht mehr als neue Leads angelegt."
    )
    crm_file = st.file_uploader(
        "Salesforce-Export hochladen",
        type=["csv", "xlsx"],
        key="salesforce_export",
    )
    if crm_file is not None:
        try:
            crm_companies, detected_column, row_count = read_company_file(crm_file)
            matches = {
                normalize_company(company)
                for company in df.get("firma", [])
                if normalize_company(company) in crm_companies
            }
            c1, c2, c3 = st.columns(3)
            c1.metric("Zeilen im Export", row_count)
            c2.metric("Eindeutige Firmen", len(crm_companies))
            c3.metric("Treffer in Leadliste", len(matches))
            st.info(f"Erkannte Firmenspalte: {detected_column}")
            if st.button("Salesforce-Firmen dauerhaft abgleichen"):
                combined = set(exclusions) | crm_companies
                storage.save_exclusions(combined)
                df = apply_crm_status(df, combined)
                storage.save(df)
                st.success(
                    f"{len(crm_companies)} Salesforce-Firmen gespeichert. "
                    f"{len(matches)} vorhandene Leads wurden als Bestand erkannt."
                )
                st.rerun()
        except Exception as exc:
            st.error(str(exc))

elif page == "CRM-Ausschluss":
    st.title("CRM-Ausschluss")
    st.caption("Diese Firmen werden bei neuen Suchläufen nicht mehr als Leads angelegt.")

    manual = st.text_area("Firmen hinzufügen – eine Zeile je Firma")
    if st.button("Firmen speichern"):
        new_items = {normalize_company(v) for v in manual.splitlines() if v.strip()}
        storage.save_exclusions(set(exclusions) | new_items)
        st.success("Ausschlussliste aktualisiert.")
        st.rerun()

    st.write(f"**Aktuell gespeichert:** {len(exclusions)} Firmen")
    if exclusions:
        st.dataframe(pd.DataFrame({"Firma normalisiert": sorted(exclusions)}), hide_index=True)
