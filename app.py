
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
    "arbeitnehmerüberlassung", "randstad", "adecco", "manpower",
    "persona service", "tempton", "office people", "pluss personal",
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
    "erstmail_betreff", "erstmail", "call_opener", "discovery_fragen",
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

def homepage_from_url(url):
    if not url:
        return ""
    parsed = urlparse(url if "://" in url else "https://" + url)
    return f"{parsed.scheme or 'https'}://{parsed.netloc}" if parsed.netloc else ""


def root_domain(url):
    parsed = urlparse(url if "://" in url else "https://" + url)
    ext = tldextract.extract(parsed.netloc)
    return f"{ext.domain}.{ext.suffix}" if ext.domain and ext.suffix else ""


def extract_emails(text):
    return unique(re.findall(
        r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}",
        text or "",
        re.I,
    ))


def choose_email(emails, domain):
    same = [e for e in emails if domain and e.lower().endswith("@" + domain.lower())]
    pool = same or emails
    if not pool:
        return ""
    generic = ("info@", "kontakt@", "office@", "bewerbung@", "karriere@", "personal@")
    personal = [e for e in pool if not e.lower().startswith(generic)]
    return personal[0] if personal else pool[0]


def extract_phone(text):
    matches = re.findall(r"(?:\+49|0)[\d\s()/.\-]{7,}", text or "")
    return clean_text(matches[0]) if matches else ""


def find_person(text):
    text = clean_text(text)
    patterns = [
        r"(?:Ansprechpartner(?:in)?|Kontakt)\s*:?\s*([A-ZÄÖÜ][a-zäöüß\-]+(?:\s+[A-ZÄÖÜ][a-zäöüß\-]+){1,2})",
        r"([A-ZÄÖÜ][a-zäöüß\-]+(?:\s+[A-ZÄÖÜ][a-zäöüß\-]+){1,2})\s*(?:–|-|\|)\s*(Geschäftsführer(?:in)?|Inhaber(?:in)?|Partner(?:in)?|Personal|HR|Recruiting)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1), match.group(2) if match.lastindex and match.lastindex > 1 else ""
    return "", ""


def research_site(start_url):
    result = {
        "website": "", "contact_page": "", "email": "",
        "phone": "", "person": "", "role": "", "text": "",
    }
    homepage = homepage_from_url(start_url)
    if not homepage:
        return result

    candidates = [
        homepage,
        urljoin(homepage, "/kontakt"),
        urljoin(homepage, "/impressum"),
        urljoin(homepage, "/karriere"),
        urljoin(homepage, "/team"),
        urljoin(homepage, "/ueber-uns"),
    ]

    all_text, all_emails = [], []
    phone = person = role = contact_page = ""

    for url in candidates:
        response = safe_get(url)
        if not response or "text/html" not in response.headers.get("content-type", ""):
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = clean_text(soup.get_text(" "))
        all_text.append(text[:25000])
        all_emails.extend(extract_emails(response.text))
        all_emails.extend(extract_emails(text))
        if not phone:
            phone = extract_phone(text)
        if not person:
            person, role = find_person(text)
        if not contact_page and any(x in response.url.lower() for x in ("kontakt", "impressum", "karriere")):
            contact_page = response.url

    domain = root_domain(homepage)
    result.update({
        "website": homepage,
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

def score_lead(jobs, research, benefits):
    score, reasons = 0, []
    count = len(jobs)

    if count >= 3:
        score += 32
        reasons.append(f"{count} offene Stellen")
    elif count == 2:
        score += 24
        reasons.append("2 offene Stellen")
    else:
        score += 14
        reasons.append("frische offene Stelle")

    if research.get("email") or any(j["email"] for j in jobs):
        score += 14
        reasons.append("E-Mail vorhanden")
    if research.get("person") or any(j["contact"] for j in jobs):
        score += 14
        reasons.append("Ansprechpartner vorhanden")
    if research.get("phone") or any(j["phone"] for j in jobs):
        score += 8
        reasons.append("Telefon vorhanden")
    if len(benefits) >= 4:
        score += 16
        reasons.append("starke Benefits")
    elif len(benefits) >= 2:
        score += 9
        reasons.append("mehrere Benefits")
    if len({j["title"] for j in jobs}) >= 2:
        score += 8
        reasons.append("mehrere Zielprofile")

    score = min(score, 100)
    status = "HOT" if score >= 65 else "WARM" if score >= 42 else "COLD"
    return status, score, ", ".join(reasons)


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


def build_leads(parsed_jobs, exclusions, max_research):
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
        research = research_site(start_url) if idx < max_research else {
            "website": homepage_from_url(start_url), "contact_page": "",
            "email": "", "phone": "", "person": "", "role": "", "text": "",
        }

        benefits = unique(
            detect_benefits(" ".join(j["description"] for j in jobs))
            + detect_benefits(research.get("text", ""))
        )
        hot, score, reason = score_lead(jobs, research, benefits)
        texts = create_texts(company, jobs, benefits, research.get("person", ""))

        row = {
            "lead_id": lead_id(company),
            "firma": company,
            "hot_status": hot,
            "lead_score": score,
            "warum_hot": reason,
            "offene_stellen": " | ".join(unique([j["title"] for j in jobs])),
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
    ["Daily Leads", "Follow-ups", "Alle Leads", "CRM-Ausschluss"],
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
        col1, col2, col3 = st.columns(3)
        days = col1.number_input("Veröffentlicht seit Tagen", 1, 14, 2)
        max_pages = col2.number_input("Seiten pro Suche", 1, 20, 5)
        max_research = col3.number_input("Websites recherchieren", 0, 100, 25)

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

            progress = st.progress(0, text="Suche läuft …")
            raw_jobs = []
            total = max(1, len(search_terms) * len(regions))
            step = 0
            for term in search_terms:
                for city, radius in regions:
                    raw_jobs.extend(fetch_search(term, city, radius, days, max_pages))
                    step += 1
                    progress.progress(step / total, text=f"{term} · {city}")

            seen, parsed = set(), []
            for raw in raw_jobs:
                reference = clean_text(first_value(raw, ["referenznummer", "refnr", "refNr"]))
                if reference and reference in seen:
                    continue
                if reference:
                    seen.add(reference)
                job = parse_job(raw)
                if job["company"]:
                    parsed.append(job)

            fresh = build_leads(parsed, exclusions, int(max_research))
            merged, inserted, updated = upsert(df, fresh)
            storage.save(merged)
            progress.empty()
            st.success(f"{inserted} neue Firmen, {updated} bestehende Firmen aktualisiert.")
            st.rerun()

    if df.empty:
        st.info("Noch keine Leads vorhanden. Starte oben die erste Suche.")
    else:
        new_df = df[df["status"].isin(["Neu", "Für morgen", "Mail vorbereitet"])].copy()
        new_df["lead_score"] = pd.to_numeric(new_df["lead_score"], errors="coerce").fillna(0)
        new_df = new_df.sort_values("lead_score", ascending=False)

        c1, c2, c3 = st.columns(3)
        c1.metric("Neue Leads", len(new_df))
        c2.metric("HOT", int((new_df["hot_status"] == "HOT").sum()))
        c3.metric("Mit E-Mail", int((new_df["email"] != "").sum()))

        for idx, row in new_df.iterrows():
            with st.container(border=True):
                top1, top2, top3 = st.columns([5, 2, 2])
                top1.subheader(row["firma"])
                top2.metric(row["hot_status"], int(float(row["lead_score"] or 0)))
                top3.write(row["veroeffentlicht_am"] or "Datum offen")

                st.write(f"**Stellen:** {row['offene_stellen']}")
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
            "hot_status", "lead_score", "firma", "offene_stellen",
            "ansprechpartner", "email", "telefon", "status",
            "wiedervorlage", "zuletzt_gefunden",
        ]],
        use_container_width=True,
        hide_index=True,
    )

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
