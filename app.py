from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd
import streamlit as st

from pipeline import (
    COLUMNS,
    STATUSES,
    ai_candidate_indices,
    apply_crm_status,
    build_discovery_leads,
    clean_text,
    enrich_lead,
    generate_lead_assets,
    migrate_frame,
    normalize_company,
    research_candidate_indices,
    upsert_leads,
)
from sales_ai import openai_available
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

st.markdown(
    """
    <style>
    html, body, [class*="css"], [data-testid="stAppViewContainer"] {
        font-family: Arial, sans-serif !important;
        font-size: 11.5pt;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


DEFAULT_SEARCH_TERMS = [
    "Physiotherapeut",
    "Ergotherapeut",
    "Logopäde",
    "Pflegefachkraft",
    "Medizinische Fachangestellte",
    "Steuerfachangestellte",
    "Steuerfachwirt",
    "Bilanzbuchhalter",
    "Elektroniker",
    "Mechatroniker",
    "Anlagenmechaniker",
    "Servicetechniker",
    "Industriemechaniker",
    "Schweißer",
    "Bauleiter",
    "Projektingenieur",
    "Konstrukteur",
    "Softwareentwickler",
    "Systemadministrator",
    "DevOps Engineer",
    "Vertriebsmitarbeiter",
    "Account Manager",
    "Controller",
    "Berufskraftfahrer",
    "Disponent",
]

DEFAULT_REGIONS = [
    ("Münster", 120),
    ("Osnabrück", 120),
    ("Dortmund", 120),
    ("Bielefeld", 120),
    ("Düsseldorf", 100),
    ("Köln", 100),
    ("Hannover", 120),
    ("Bremen", 120),
]

LOG_COLUMNS = [
    "timestamp",
    "scan_id",
    "stage",
    "status",
    "processed_terms",
    "processed_items",
    "found_jobs",
    "new_leads",
    "updated_leads",
    "message",
]

COMPANY_ALIASES = [
    "account name",
    "account",
    "firmenname",
    "firma",
    "unternehmen",
    "unternehmensname",
    "company",
    "company name",
    "name des accounts",
    "kunde",
    "kundenname",
    "arbeitgeber",
]

STATE_ALIASES = [
    "bundesland",
    "bundeslaender",
    "bundesländer",
    "region",
    "state",
    "gebiet",
    "land",
]


def _secret_text(name: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(name, default) or default).strip()
    except Exception:
        return str(default).strip()


def _google_config_signature() -> str:
    try:
        account = st.secrets.get("gcp_service_account", {})
        client_email = str(account.get("client_email", "")).strip() if account else ""
    except Exception:
        client_email = ""
    return "|".join(
        [
            _secret_text("spreadsheet_id"),
            _secret_text("spreadsheet_name"),
            client_email,
        ]
    )


def _google_call(func, *args, **kwargs):
    delays = (0, 3, 8, 20)
    last_error = None
    for delay in delays:
        if delay:
            time.sleep(delay)
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            last_error = exc
            message = str(exc).lower()
            temporary = any(
                marker in message
                for marker in ("429", "quota exceeded", "resource_exhausted", "503")
            )
            if not temporary:
                raise
    raise last_error


def _column_letter(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _safe_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column in frame.columns:
        return frame[column].astype(str)
    return pd.Series([""] * len(frame), index=frame.index, dtype=str)


def _value(row: pd.Series, column: str, default: str = "") -> str:
    value = row.get(column, default)
    if value is None or pd.isna(value):
        return default
    return str(value)


class Storage:
    def __init__(self):
        self.mode = "local"
        self.error = ""
        self.ws = None
        self.exclusion_ws = None
        self.log_ws = None
        self.book_title = ""
        self.book_id = ""
        self.book_url = ""
        self.row_map: dict[str, int] = {}
        self.next_row = 2
        self.local_path = "leads_local.csv"
        self.local_exclusion_path = "crm_ausschluss_local.csv"
        self.local_log_path = "scan_log_local.csv"

        spreadsheet_id = _secret_text("spreadsheet_id")
        spreadsheet_name = _secret_text("spreadsheet_name")
        try:
            service_account = dict(st.secrets.get("gcp_service_account", {}))
        except Exception:
            service_account = {}

        configured = bool(
            gspread
            and Credentials
            and service_account
            and (spreadsheet_id or spreadsheet_name)
        )
        if not configured:
            return

        try:
            credentials = Credentials.from_service_account_info(
                service_account,
                scopes=[
                    "https://www.googleapis.com/auth/spreadsheets",
                    "https://www.googleapis.com/auth/drive",
                ],
            )
            client = gspread.authorize(credentials)
            if spreadsheet_id:
                book = _google_call(client.open_by_key, spreadsheet_id)
            else:
                book = _google_call(client.open, spreadsheet_name)

            self.book_title = book.title
            self.book_id = book.id
            self.book_url = f"https://docs.google.com/spreadsheets/d/{book.id}/edit"
            worksheets = {sheet.title: sheet for sheet in _google_call(book.worksheets)}
            self.ws = self._lead_sheet(book, worksheets, 12000, max(70, len(COLUMNS) + 5))

            existing_exclusion = (
                worksheets.get("Ausgeschlossene Unternehmen")
                or worksheets.get("CRM_Ausschluss")
                or worksheets.get("CRM Ausschluss")
            )
            if existing_exclusion is None:
                existing_exclusion = self._sheet(
                    book,
                    worksheets,
                    "Ausgeschlossene Unternehmen",
                    12000,
                    5,
                )
            self.exclusion_ws = existing_exclusion
            self.log_ws = self._sheet(
                book,
                worksheets,
                "Scan_Log",
                12000,
                len(LOG_COLUMNS) + 2,
            )
            self.mode = "google"
        except Exception as exc:
            self.mode = "google_error"
            self.error = str(exc)

    @staticmethod
    def _lead_sheet(book, worksheets: dict[str, Any], rows: int, cols: int):
        if "Leads" in worksheets:
            return worksheets["Leads"]

        default_sheet = worksheets.get("Tabelle1") or worksheets.get("Sheet1")
        if default_sheet is not None:
            try:
                values = _google_call(default_sheet.get_all_values)
                is_empty = not values or not any(
                    any(str(cell).strip() for cell in row) for row in values
                )
                if is_empty:
                    old_title = default_sheet.title
                    _google_call(default_sheet.update_title, "Leads")
                    worksheets.pop(old_title, None)
                    worksheets["Leads"] = default_sheet
                    return default_sheet
            except Exception:
                pass

        return Storage._sheet(book, worksheets, "Leads", rows, cols)

    @staticmethod
    def _sheet(book, worksheets: dict[str, Any], title: str, rows: int, cols: int):
        if title in worksheets:
            return worksheets[title]
        sheet = _google_call(book.add_worksheet, title=title, rows=rows, cols=cols)
        try:
            _google_call(sheet.freeze, rows=1)
        except Exception:
            pass
        worksheets[title] = sheet
        return sheet

    @staticmethod
    def _records(values: list[list[str]]) -> list[dict[str, str]]:
        if not values:
            return []
        header = values[0]
        records: list[dict[str, str]] = []
        for row in values[1:]:
            padded = row + [""] * max(0, len(header) - len(row))
            records.append(dict(zip(header, padded[: len(header)])))
        return records

    def load(self) -> pd.DataFrame:
        if self.mode == "google_error":
            raise RuntimeError(self.error or "Google Sheets ist nicht verbunden.")
        if self.mode == "local":
            try:
                return migrate_frame(pd.read_csv(self.local_path, dtype=str).fillna(""))
            except FileNotFoundError:
                return migrate_frame(pd.DataFrame())

        values = _google_call(self.ws.get_all_values)
        if not values:
            _google_call(self.ws.update, [COLUMNS])
            self.row_map = {}
            self.next_row = 2
            return migrate_frame(pd.DataFrame())

        header = values[0]
        frame = migrate_frame(pd.DataFrame(self._records(values)))
        if header != COLUMNS:
            self.save(frame)
            return frame

        self.row_map = {}
        for index, record in enumerate(self._records(values), start=2):
            lead = clean_text(record.get("lead_id", ""))
            if lead:
                self.row_map[lead] = index
        self.next_row = max([1] + list(self.row_map.values())) + 1
        return frame

    def save(self, frame: pd.DataFrame) -> None:
        frame = migrate_frame(frame)
        if self.mode == "google_error":
            raise RuntimeError(self.error or "Google Sheets ist nicht verbunden.")
        if self.mode == "local":
            frame.to_csv(self.local_path, index=False)
            return

        _google_call(self.ws.clear)
        _google_call(self.ws.update, [COLUMNS] + frame.astype(str).values.tolist())
        self.row_map = {
            row["lead_id"]: index
            for index, (_, row) in enumerate(frame.iterrows(), start=2)
            if row["lead_id"]
        }
        self.next_row = len(frame) + 2

    def upsert_rows(self, rows: pd.DataFrame, full_frame: pd.DataFrame) -> None:
        rows = migrate_frame(rows)
        full_frame = migrate_frame(full_frame)
        if rows.empty:
            return
        if self.mode != "google":
            self.save(full_frame)
            return

        end_column = _column_letter(len(COLUMNS))
        updates: list[dict[str, Any]] = []
        append_values: list[list[str]] = []
        append_ids: list[str] = []

        for _, row in rows.iterrows():
            values = [str(row[column] or "") for column in COLUMNS]
            lead = row["lead_id"]
            if lead in self.row_map:
                sheet_row = self.row_map[lead]
                updates.append(
                    {
                        "range": f"A{sheet_row}:{end_column}{sheet_row}",
                        "values": [values],
                    }
                )
            else:
                append_values.append(values)
                append_ids.append(lead)

        try:
            for start in range(0, len(updates), 100):
                _google_call(self.ws.batch_update, updates[start : start + 100])
            if append_values:
                _google_call(self.ws.append_rows, append_values, value_input_option="RAW")
                for lead in append_ids:
                    self.row_map[lead] = self.next_row
                    self.next_row += 1
        except Exception:
            self.save(full_frame)

    def load_exclusions(self) -> set[str]:
        if self.mode == "google_error":
            raise RuntimeError(self.error or "Google Sheets ist nicht verbunden.")
        if self.mode == "local":
            try:
                frame = pd.read_csv(self.local_exclusion_path, dtype=str).fillna("")
                return {
                    normalize_company(value)
                    for value in frame.get("firma", [])
                    if value
                }
            except FileNotFoundError:
                return set()

        values = _google_call(self.exclusion_ws.get_all_records)
        return {
            normalize_company(row.get("firma", ""))
            for row in values
            if row.get("firma")
        }

    def save_exclusions(self, companies: set[str]) -> None:
        rows = sorted(
            {
                normalize_company(company)
                for company in companies
                if normalize_company(company)
            }
        )
        if self.mode == "google_error":
            raise RuntimeError(self.error or "Google Sheets ist nicht verbunden.")
        if self.mode == "local":
            pd.DataFrame({"firma": rows}).to_csv(
                self.local_exclusion_path,
                index=False,
            )
            return
        _google_call(self.exclusion_ws.clear)
        _google_call(self.exclusion_ws.update, [["firma"]] + [[company] for company in rows])

    def load_logs(self) -> pd.DataFrame:
        if self.mode == "google_error":
            raise RuntimeError(self.error or "Google Sheets ist nicht verbunden.")
        if self.mode == "local":
            try:
                frame = pd.read_csv(self.local_log_path, dtype=str).fillna("")
            except FileNotFoundError:
                frame = pd.DataFrame(columns=LOG_COLUMNS)
            return frame.reindex(columns=LOG_COLUMNS).fillna("")

        values = _google_call(self.log_ws.get_all_values)
        if not values:
            _google_call(self.log_ws.update, [LOG_COLUMNS])
            return pd.DataFrame(columns=LOG_COLUMNS)
        frame = pd.DataFrame(self._records(values))
        for column in LOG_COLUMNS:
            if column not in frame.columns:
                frame[column] = ""
        return frame.reindex(columns=LOG_COLUMNS).fillna("")

    def append_log(self, record: dict[str, Any]) -> None:
        row = [clean_text(record.get(column, "")) for column in LOG_COLUMNS]
        if self.mode == "google_error":
            raise RuntimeError(self.error or "Google Sheets ist nicht verbunden.")
        if self.mode == "local":
            current = self.load_logs()
            current.loc[len(current)] = row
            current.to_csv(self.local_log_path, index=False)
            return
        _google_call(self.log_ws.append_row, row, value_input_option="RAW")


@st.cache_resource(show_spinner=False)
def get_storage(config_signature: str) -> Storage:
    _ = config_signature
    return Storage()


storage = get_storage(_google_config_signature())


def persist_full(frame: pd.DataFrame) -> None:
    frame = migrate_frame(frame)
    storage.save(frame)
    st.session_state["xing_frame_cache"] = frame.copy()


def persist_rows(rows: pd.DataFrame, frame: pd.DataFrame) -> None:
    rows = migrate_frame(rows)
    frame = migrate_frame(frame)
    storage.upsert_rows(rows, frame)
    st.session_state["xing_frame_cache"] = frame.copy()


def persist_exclusions(companies: set[str]) -> None:
    normalized = {
        normalize_company(company)
        for company in companies
        if normalize_company(company)
    }
    storage.save_exclusions(normalized)
    st.session_state["xing_exclusions_cache"] = set(normalized)


def append_log(**kwargs) -> None:
    record = {column: "" for column in LOG_COLUMNS}
    record.update(kwargs)
    record["timestamp"] = record.get("timestamp") or datetime.now(
        timezone.utc
    ).isoformat(timespec="seconds")
    storage.append_log(record)
    logs = st.session_state.get(
        "xing_logs_cache",
        pd.DataFrame(columns=LOG_COLUMNS),
    ).copy()
    logs.loc[len(logs)] = [record.get(column, "") for column in LOG_COLUMNS]
    st.session_state["xing_logs_cache"] = logs


def _read_csv_bytes(raw: bytes) -> pd.DataFrame:
    for encoding in ("utf8", "utf8 sig", "latin1"):
        python_encoding = {
            "utf8": "utf-8",
            "utf8 sig": "utf-8-sig",
            "latin1": "latin1",
        }[encoding]
        try:
            return pd.read_csv(
                pd.io.common.BytesIO(raw),
                dtype=str,
                sep=None,
                engine="python",
                encoding=python_encoding,
            ).fillna("")
        except Exception:
            continue
    raise ValueError("Die CSV Datei konnte nicht gelesen werden.")


def read_company_file(uploaded_file):
    name = uploaded_file.name.lower()
    if name.endswith(".xlsx"):
        frame = pd.read_excel(uploaded_file, dtype=str).fillna("")
    elif name.endswith(".csv"):
        frame = _read_csv_bytes(uploaded_file.getvalue())
    else:
        raise ValueError("Bitte eine CSV oder XLSX Datei hochladen.")

    if frame.empty:
        raise ValueError("Die Datei enthält keine Daten.")

    normalized_columns = {
        normalize_company(column): column for column in frame.columns
    }

    company_column = next(
        (
            original
            for normalized, original in normalized_columns.items()
            if any(alias in normalized for alias in COMPANY_ALIASES)
        ),
        None,
    )

    if company_column is None and len(frame.columns) == 1:
        company_column = frame.columns[0]

    if not company_column:
        raise ValueError(
            "Keine Unternehmensspalte erkannt. Nutze zum Beispiel Firma, Unternehmen oder Account Name."
        )

    state_column = next(
        (
            original
            for normalized, original in normalized_columns.items()
            if any(alias in normalized for alias in STATE_ALIASES)
        ),
        None,
    )

    original_names = [
        clean_text(value)
        for value in frame[company_column].astype(str)
        if clean_text(value)
    ]
    companies = {
        normalize_company(value)
        for value in original_names
        if normalize_company(value)
    }

    if not companies:
        raise ValueError("In der erkannten Unternehmensspalte stehen keine Firmennamen.")

    preview_columns = [company_column]
    if state_column and state_column != company_column:
        preview_columns.append(state_column)
    preview = frame[preview_columns].head(12).copy()

    return {
        "companies": companies,
        "company_column": company_column,
        "state_column": state_column,
        "row_count": len(frame),
        "preview": preview,
    }


def import_exclusion_file(uploaded_file, current_exclusions: set[str]) -> int:
    result = read_company_file(uploaded_file)
    new_companies = result["companies"] - current_exclusions
    persist_exclusions(current_exclusions | result["companies"])
    return len(new_companies)


def parse_regions(text: str) -> list[tuple[str, int]]:
    regions: list[tuple[str, int]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        city, radius = line.rsplit(",", 1)
        city = city.strip()
        radius_value = int(radius.strip())
        if not city or radius_value <= 0:
            raise ValueError
        regions.append((city, radius_value))
    if not regions:
        raise ValueError
    return regions


def next_term_batch(terms: list[str], batch_size: int, logs: pd.DataFrame) -> list[str]:
    if not terms:
        return []
    start = 0
    if not logs.empty:
        search_logs = logs[
            (logs["stage"] == "Suche")
            & (logs["status"].isin(["checkpoint", "fertig"]))
            & (logs["processed_terms"] != "")
        ]
        if not search_logs.empty:
            last_terms = [
                term.strip()
                for term in search_logs.iloc[-1]["processed_terms"].split("|")
                if term.strip()
            ]
            if last_terms and last_terms[-1] in terms:
                start = (terms.index(last_terms[-1]) + 1) % len(terms)
    rotated = terms[start:] + terms[:start]
    return rotated[: min(batch_size, len(terms))]


def latest_scan_id(frame: pd.DataFrame) -> str:
    if frame.empty:
        return ""
    scan_ids = [
        str(value)
        for value in _safe_series(frame, "scan_id").unique().tolist()
        if re.fullmatch(r"\d{8}T\d{6}Z", str(value or ""))
    ]
    return max(scan_ids) if scan_ids else ""


def exclusion_upload_block(
    title: str,
    key_prefix: str,
    current_exclusions: set[str],
) -> set[str]:
    st.markdown(f"#### {title}")
    st.caption(
        "Lade eine CSV oder XLSX Datei hoch. Die Unternehmensspalte wird automatisch erkannt. "
        "Eine Bundeslandspalte darf zusätzlich enthalten sein."
    )
    uploaded = st.file_uploader(
        "Datei mit ausgeschlossenen Unternehmen",
        type=["csv", "xlsx"],
        key=f"{key_prefix}_upload",
    )
    if uploaded is None:
        return current_exclusions

    try:
        result = read_company_file(uploaded)
        state_text = (
            f" Bundeslandspalte erkannt: {result['state_column']}."
            if result["state_column"]
            else " Keine Bundeslandspalte erforderlich."
        )
        st.info(
            f"Unternehmensspalte erkannt: {result['company_column']}. "
            f"Zeilen: {result['row_count']}.{state_text}"
        )
        st.dataframe(result["preview"], use_container_width=True, hide_index=True)
        if st.button(
            "Unternehmen ausschließen",
            type="primary",
            key=f"{key_prefix}_save",
        ):
            new_count = len(result["companies"] - current_exclusions)
            merged = current_exclusions | result["companies"]
            persist_exclusions(merged)
            st.success(
                f"{new_count} neue Unternehmen gespeichert. Insgesamt sind {len(merged)} Unternehmen ausgeschlossen."
            )
            st.rerun()
    except Exception as exc:
        st.error(str(exc))

    return current_exclusions


openai_api_key = _secret_text("openai_api_key")
openai_model = _secret_text("openai_model", "gpt-5-mini") or "gpt-5-mini"
serpapi_key = _secret_text("serpapi_key")
adzuna_app_id = _secret_text("adzuna_app_id")
adzuna_api_key = _secret_text("adzuna_api_key")

st.sidebar.title("XING Daily Leads")
page = st.sidebar.radio(
    "Bereich",
    [
        "Daily Leads",
        "Follow ups",
        "Alle Leads",
        "Ausgeschlossene Unternehmen",
    ],
)

st.sidebar.markdown("### Systemcheck")
if storage.mode == "google":
    storage_label = "Google Sheets"
elif storage.mode == "google_error":
    storage_label = "Google Sheets Fehler"
else:
    storage_label = "lokaler Testmodus"
st.sidebar.write(f"Speicher: {storage_label}")

if storage.mode == "local" and (
    "gcp_service_account" in st.secrets
    or _secret_text("spreadsheet_id")
    or _secret_text("spreadsheet_name")
):
    st.sidebar.warning(
        "Google Sheets ist nur teilweise konfiguriert. Benötigt werden "
        "gcp_service_account und spreadsheet_id oder spreadsheet_name."
    )

if storage.mode == "google":
    st.sidebar.caption(f"Verbunden mit: {storage.book_title}")
    if storage.book_url:
        st.sidebar.link_button("Verbundenes Google Sheet öffnen", storage.book_url)

st.sidebar.write(f"OpenAI Paket: {'bereit' if openai_available() else 'fehlt'}")
st.sidebar.write(f"OpenAI Key: {'hinterlegt' if openai_api_key else 'fehlt'}")
st.sidebar.write(f"SerpApi: {'hinterlegt' if serpapi_key else 'nicht hinterlegt'}")
st.sidebar.write(
    f"Adzuna: {'bereit' if adzuna_app_id and adzuna_api_key else 'Zugangsdaten fehlen'}"
)

if storage.mode == "google_error":
    st.error(
        "Google Sheets ist konfiguriert, konnte aber nicht verbunden werden. "
        f"Fehler: {storage.error}"
    )
    st.stop()

if st.sidebar.button("Daten aus Google Sheets neu laden"):
    st.session_state.pop("xing_frame_cache", None)
    st.session_state.pop("xing_exclusions_cache", None)
    st.session_state.pop("xing_logs_cache", None)
    st.rerun()

if "xing_frame_cache" not in st.session_state:
    st.session_state["xing_frame_cache"] = storage.load()
if "xing_exclusions_cache" not in st.session_state:
    st.session_state["xing_exclusions_cache"] = storage.load_exclusions()
if "xing_logs_cache" not in st.session_state:
    st.session_state["xing_logs_cache"] = storage.load_logs()

frame = migrate_frame(st.session_state["xing_frame_cache"].copy())
exclusions = set(st.session_state["xing_exclusions_cache"])
logs = st.session_state["xing_logs_cache"].copy()

if not frame.empty:
    legacy_mask = _safe_series(frame, "first_seen_scan").str.strip().eq("")
    if legacy_mask.any():
        frame.loc[legacy_mask, "first_seen_scan"] = "legacy"
        empty_scan = legacy_mask & _safe_series(frame, "scan_id").str.strip().eq("")
        frame.loc[empty_scan, "scan_id"] = "legacy"
        persist_full(frame)


if page == "Daily Leads":
    st.title("Daily Leads")
    st.caption(
        "Drei getrennte Schritte. Jeder fertige Teil wird sofort gespeichert."
    )

    research_pending = (
        len(research_candidate_indices(frame, max(1, len(frame))))
        if not frame.empty
        else 0
    )
    ai_pending = (
        len(ai_candidate_indices(frame, max(1, len(frame))))
        if not frame.empty
        else 0
    )
    ready_mask = (
        ((_safe_series(frame, "email") != "") | (_safe_series(frame, "telefon") != ""))
        & (_safe_series(frame, "call_opener") != "")
        & (_safe_series(frame, "erstmail") != "")
        if not frame.empty
        else pd.Series(dtype=bool)
    )

    metric_columns = st.columns(4)
    metric_columns[0].metric("Gespeicherte Firmen", len(frame))
    metric_columns[1].metric("Recherche offen", research_pending)
    metric_columns[2].metric("Texte offen", ai_pending)
    metric_columns[3].metric(
        "Verkaufsbereit",
        int(ready_mask.sum()) if not frame.empty else 0,
    )

    with st.expander(
        "Schritt 1: Stellen finden und Firmen sofort speichern",
        expanded=frame.empty,
    ):
        st.write(
            "Dieser Schritt sucht Stellen und speichert jede fertige Suchrunde sofort. "
            "Website Recherche und OpenAI starten erst in den nächsten Schritten."
        )
        terms_text = st.text_area(
            "Suchbegriffe, eine Zeile je Begriff",
            "\n".join(DEFAULT_SEARCH_TERMS),
            key="terms_v5",
        )
        regions_text = st.text_area(
            "Regionen im Format Ort,Umkreis",
            "\n".join(f"{city},{radius}" for city, radius in DEFAULT_REGIONS),
            key="regions_v5",
        )

        source_columns = st.columns(4)
        use_adzuna = source_columns[0].checkbox(
            "Adzuna",
            value=bool(adzuna_app_id and adzuna_api_key),
            key="source_adzuna_v5",
        )
        use_ba = source_columns[1].checkbox(
            "Bundesagentur",
            value=True,
            key="source_ba_v5",
        )
        use_google = source_columns[2].checkbox(
            "Google Jobs",
            value=False,
            key="source_google_v5",
        )
        use_careers = source_columns[3].checkbox(
            "Karriereseiten",
            value=False,
            key="source_careers_v5",
        )

        career_urls_text = st.text_area(
            "Optionale Karriereseiten oder ATS Boards, eine URL je Zeile",
            placeholder=(
                "https://firma.jobs.personio.de\n"
                "https://boards.greenhouse.io/firma\n"
                "https://jobs.lever.co/firma\n"
                "https://firma.de/karriere"
            ),
            key="career_urls_v5",
        )

        settings_columns = st.columns(3)
        days = settings_columns[0].number_input(
            "Veröffentlicht seit Tagen",
            1,
            30,
            14,
            key="days_v5",
        )
        max_pages = settings_columns[1].number_input(
            "Seiten je Suche",
            1,
            3,
            1,
            key="pages_v5",
        )
        term_batch_size = settings_columns[2].number_input(
            "Suchbegriffe pro Klick",
            1,
            5,
            2,
            key="term_batch_v5",
        )

        all_terms = [line.strip() for line in terms_text.splitlines() if line.strip()]
        upcoming_terms = next_term_batch(all_terms, int(term_batch_size), logs)
        st.info(
            "Nächste Suchrunde: "
            + (", ".join(upcoming_terms) if upcoming_terms else "keine Begriffe")
        )
        st.caption(
            "Die Bundesagentur läuft im Schnellmodus. Kontakte werden anschließend in Schritt 2 recherchiert."
        )

        exclusions = exclusion_upload_block(
            "Ausgeschlossene Unternehmen",
            "daily_exclusions_v5",
            exclusions,
        )

        if st.button("Schritt 1 starten", type="primary", key="start_discovery_v5"):
            try:
                regions = parse_regions(regions_text)
            except Exception:
                st.error("Mindestens eine Region hat nicht das Format Ort,Umkreis.")
                st.stop()

            sources: list[str] = []
            if use_adzuna:
                sources.append("Adzuna")
            if use_ba:
                sources.append("Bundesagentur")
            if use_google:
                sources.append("Google Jobs")
            if use_careers:
                sources.append("Karriereseiten")

            if not sources:
                st.error("Aktiviere mindestens eine Quelle.")
                st.stop()
            if use_adzuna and (not adzuna_app_id or not adzuna_api_key):
                st.error("Adzuna ist aktiviert, aber die Zugangsdaten fehlen.")
                st.stop()
            if use_google and not serpapi_key:
                st.error("Google Jobs ist aktiviert, aber der SerpApi Key fehlt.")
                st.stop()

            scan_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            terms_to_run = next_term_batch(all_terms, int(term_batch_size), logs)
            career_urls = [
                line.strip()
                for line in career_urls_text.splitlines()
                if line.strip()
            ]
            append_log(
                scan_id=scan_id,
                stage="Suche",
                status="gestartet",
                processed_terms=" | ".join(terms_to_run),
                message="Suchrunde gestartet. Ergebnisse werden nach jedem Begriff gespeichert.",
            )

            progress = st.progress(0, text="Suchrunde startet.")
            total_jobs = 0
            total_inserted = 0
            total_updated = 0
            details: list[str] = []
            completed_terms: list[str] = []

            try:
                for position, term in enumerate(terms_to_run, start=1):
                    progress.progress(
                        (position - 1) / max(1, len(terms_to_run)),
                        text=f"Suche {position} von {len(terms_to_run)}: {term}",
                    )
                    term_sources = list(sources)
                    term_career_urls = career_urls
                    if position > 1 and "Karriereseiten" in term_sources:
                        term_sources.remove("Karriereseiten")
                        term_career_urls = []

                    parsed_jobs, scan_diagnostics = scan_jobs(
                        terms=[term],
                        regions=regions,
                        days=int(days),
                        max_pages=int(max_pages),
                        sources=term_sources,
                        career_urls=term_career_urls,
                        serpapi_key=serpapi_key,
                        adzuna_app_id=adzuna_app_id,
                        adzuna_api_key=adzuna_api_key,
                        ba_fetch_details=False,
                    )
                    fresh, discovery_diagnostics = build_discovery_leads(
                        parsed_jobs=parsed_jobs,
                        exclusions=exclusions,
                        existing=frame,
                        scan_id=scan_id,
                    )
                    frame, inserted, updated, changed_ids = upsert_leads(
                        frame,
                        fresh,
                        scan_id,
                    )
                    frame = apply_crm_status(frame, exclusions)
                    changed_rows = frame[
                        _safe_series(frame, "lead_id").isin(changed_ids)
                    ].copy()
                    persist_rows(changed_rows, frame)

                    total_jobs += len(parsed_jobs)
                    total_inserted += inserted
                    total_updated += updated
                    completed_terms.append(term)
                    details.append(
                        f"{term}: {len(parsed_jobs)} priorisierte Stellen, {inserted} neue Firmen, {updated} aktualisiert."
                    )
                    details.extend(
                        f"{term}: {message}"
                        for message in scan_diagnostics + discovery_diagnostics
                    )
                    append_log(
                        scan_id=scan_id,
                        stage="Suche",
                        status="checkpoint",
                        processed_terms=" | ".join(completed_terms),
                        processed_items=str(position),
                        found_jobs=str(total_jobs),
                        new_leads=str(total_inserted),
                        updated_leads=str(total_updated),
                        message=f"{term} gespeichert.",
                    )

                progress.progress(1.0, text="Suchrunde abgeschlossen und gespeichert.")
                append_log(
                    scan_id=scan_id,
                    stage="Suche",
                    status="fertig",
                    processed_terms=" | ".join(completed_terms),
                    processed_items=str(len(completed_terms)),
                    found_jobs=str(total_jobs),
                    new_leads=str(total_inserted),
                    updated_leads=str(total_updated),
                    message="Suchrunde vollständig abgeschlossen.",
                )
                st.session_state["last_pipeline_details"] = details
                st.success(
                    f"Gespeichert: {total_inserted} neue Firmen, {total_updated} aktualisiert, {total_jobs} priorisierte Stellen."
                )
            except Exception as exc:
                append_log(
                    scan_id=scan_id,
                    stage="Suche",
                    status="fehler",
                    processed_terms=" | ".join(completed_terms),
                    processed_items=str(len(completed_terms)),
                    found_jobs=str(total_jobs),
                    new_leads=str(total_inserted),
                    updated_leads=str(total_updated),
                    message=clean_text(exc),
                )
                st.session_state["last_pipeline_details"] = details + [
                    f"Abbruch: {clean_text(exc)}"
                ]
                st.error(
                    "Die Suchrunde wurde abgebrochen. Bereits fertige Begriffe sind gespeichert. "
                    f"Fehler: {clean_text(exc)}"
                )
            finally:
                progress.empty()

    research_all = (
        research_candidate_indices(frame, max(1, len(frame)))
        if not frame.empty
        else []
    )
    with st.expander(
        f"Schritt 2: Website, Ansprechpartner, Mail und Telefon recherchieren ({len(research_all)} offen)"
    ):
        st.write("Dieser Schritt bearbeitet bereits gespeicherte Firmen in kleinen Paketen.")
        research_limit = st.number_input(
            "Firmen pro Recherchepaket",
            1,
            20,
            5,
            key="research_limit_v5",
        )
        if st.button(
            "Schritt 2 starten",
            disabled=not research_all,
            key="start_research_v5",
        ):
            indices = research_candidate_indices(frame, int(research_limit))
            run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            append_log(
                scan_id=run_id,
                stage="Recherche",
                status="gestartet",
                processed_items=str(len(indices)),
                message="Recherchepaket gestartet. Jede Firma wird einzeln gespeichert.",
            )
            progress = st.progress(0, text="Recherche startet.")
            details: list[str] = []
            websites = 0
            contacts = 0

            for position, index in enumerate(indices, start=1):
                company = _value(frame.loc[index], "firma")
                progress.progress(
                    (position - 1) / max(1, len(indices)),
                    text=f"Recherche {position} von {len(indices)}: {company}",
                )
                updated, diagnostics = enrich_lead(
                    frame.loc[index].to_dict(),
                    serpapi_key=serpapi_key,
                )
                for column in COLUMNS:
                    frame.loc[index, column] = updated.get(
                        column,
                        frame.loc[index, column],
                    )
                persist_rows(frame.loc[[index]], frame)
                if _value(frame.loc[index], "website"):
                    websites += 1
                if _value(frame.loc[index], "email") or _value(
                    frame.loc[index], "telefon"
                ):
                    contacts += 1
                details.extend(diagnostics)

            progress.empty()
            append_log(
                scan_id=run_id,
                stage="Recherche",
                status="fertig",
                processed_items=str(len(indices)),
                message=f"Websites {websites}, direkte Kontakte {contacts}.",
            )
            st.session_state["last_pipeline_details"] = details
            st.success(
                f"Recherche abgeschlossen: {len(indices)} Firmen, {websites} Websites, {contacts} direkte Kontakte."
            )

    ai_all = (
        ai_candidate_indices(frame, max(1, len(frame)))
        if not frame.empty
        else []
    )
    with st.expander(
        f"Schritt 3: Individuelle Sales Texte erzeugen ({len(ai_all)} offen)"
    ):
        st.write(
            "OpenAI wird erst für bereits gespeicherte und möglichst recherchierte Firmen genutzt."
        )
        ai_limit = st.number_input(
            "Firmen pro Textpaket",
            1,
            30,
            10,
            key="ai_limit_v5",
        )
        if st.button(
            "Schritt 3 starten",
            disabled=not ai_all,
            key="start_ai_v5",
        ):
            indices = ai_candidate_indices(frame, int(ai_limit))
            run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            append_log(
                scan_id=run_id,
                stage="Texte",
                status="gestartet",
                processed_items=str(len(indices)),
                message="Textpaket gestartet. Jede Firma wird einzeln gespeichert.",
            )
            progress = st.progress(0, text="Texte werden erzeugt.")
            details: list[str] = []
            ai_created = 0

            for position, index in enumerate(indices, start=1):
                company = _value(frame.loc[index], "firma")
                progress.progress(
                    (position - 1) / max(1, len(indices)),
                    text=f"Text {position} von {len(indices)}: {company}",
                )
                updated, diagnostics = generate_lead_assets(
                    frame.loc[index].to_dict(),
                    api_key=openai_api_key,
                    model=openai_model,
                )
                for column in COLUMNS:
                    frame.loc[index, column] = updated.get(
                        column,
                        frame.loc[index, column],
                    )
                persist_rows(frame.loc[[index]], frame)
                if _value(frame.loc[index], "ai_status").startswith("KI erstellt"):
                    ai_created += 1
                details.extend(diagnostics)

            progress.empty()
            append_log(
                scan_id=run_id,
                stage="Texte",
                status="fertig",
                processed_items=str(len(indices)),
                message=f"KI Texte {ai_created}, Fallbacks {len(indices) - ai_created}.",
            )
            st.session_state["last_pipeline_details"] = details
            st.success(
                f"Textpaket abgeschlossen: {ai_created} KI Texte, {len(indices) - ai_created} Fallbacks."
            )

    with st.expander("Technische Details und Scan Verlauf", expanded=False):
        details = st.session_state.get("last_pipeline_details", [])
        if details:
            for message in details[-80:]:
                st.write(f"• {message}")
        else:
            st.caption("In dieser Browser Sitzung gibt es noch keine technischen Details.")
        current_logs = st.session_state.get(
            "xing_logs_cache",
            pd.DataFrame(columns=LOG_COLUMNS),
        )
        if not current_logs.empty:
            st.dataframe(
                current_logs.tail(30),
                use_container_width=True,
                hide_index=True,
            )

    if frame.empty:
        st.info("Noch keine Leads vorhanden. Starte Schritt 1.")
    else:
        latest_scan = latest_scan_id(frame)
        display_frame = (
            frame[_safe_series(frame, "scan_id") == latest_scan].copy()
            if latest_scan
            else frame.copy()
        )
        display_frame = display_frame[
            ~_safe_series(display_frame, "status").isin(
                ["In Salesforce übernommen", "Ausschließen"]
            )
            & (_safe_series(display_frame, "crm_status") != "Bereits in Salesforce")
        ].copy()
        display_frame["score_num"] = pd.to_numeric(
            _safe_series(display_frame, "lead_score"),
            errors="coerce",
        ).fillna(0)
        display_frame = display_frame.sort_values("score_num", ascending=False).head(250)

        st.markdown("### Offene Leads")
        if display_frame.empty:
            st.info("In dieser Ansicht gibt es aktuell keine Leads.")
        else:
            for index, row in display_frame.iterrows():
                with st.container(border=True):
                    header_columns = st.columns([5, 2, 2])
                    header_columns[0].subheader(_value(row, "firma"))
                    score = pd.to_numeric(
                        pd.Series([_value(row, "lead_score", "0")]),
                        errors="coerce",
                    ).fillna(0).iloc[0]
                    header_columns[1].metric(
                        _value(row, "hot_status", "Lead"),
                        int(score),
                    )
                    header_columns[2].write(
                        _value(row, "veroeffentlicht_am", "Datum offen")
                    )

                    st.write(
                        f"**Stellenschwerpunkte:** {_value(row, 'offene_stellen', 'nicht erfasst')}"
                    )
                    st.write(
                        f"**Warum interessant:** {_value(row, 'warum_hot', 'noch keine belastbare Begründung')}"
                    )
                    if _value(row, "benefits"):
                        st.write(f"**Benefits:** {_value(row, 'benefits')}")

                    contact_columns = st.columns(3)
                    contact_columns[0].write(
                        f"**Ansprechpartner:** {_value(row, 'ansprechpartner', 'nicht sicher gefunden')}"
                    )
                    contact_columns[1].write(
                        f"**E Mail:** {_value(row, 'email', 'nicht gefunden')}"
                    )
                    contact_columns[2].write(
                        f"**Telefon:** {_value(row, 'telefon', 'nicht gefunden')}"
                    )

                    link_columns = st.columns(5)
                    for position, column, label in [
                        (0, "website", "Website"),
                        (1, "kontaktseite", "Kontakt"),
                        (2, "impressum", "Impressum"),
                        (3, "karriereseite", "Karriere"),
                        (4, "stellenlink", "Stelle"),
                    ]:
                        link = _value(row, column)
                        if link:
                            link_columns[position].link_button(label, link)

                    tabs = st.tabs(["Call", "Erstmail", "Follow ups", "Bearbeiten"])
                    with tabs[0]:
                        call_value = st.text_area(
                            "Call Opener",
                            _value(row, "call_opener"),
                            height=120,
                            key=f"call_{_value(row, 'lead_id')}",
                        )
                        discovery_value = st.text_area(
                            "Discovery Fragen",
                            _value(row, "discovery_fragen"),
                            height=230,
                            key=f"disc_{_value(row, 'lead_id')}",
                        )
                        challenger_value = st.text_area(
                            "Challenger Reframe",
                            _value(row, "challenger_reframe"),
                            height=130,
                            key=f"challenger_{_value(row, 'lead_id')}",
                        )
                    with tabs[1]:
                        subject_value = st.text_input(
                            "Betreff",
                            _value(row, "erstmail_betreff"),
                            key=f"subject_{_value(row, 'lead_id')}",
                        )
                        mail_value = st.text_area(
                            "Mail",
                            _value(row, "erstmail"),
                            height=300,
                            key=f"mail_{_value(row, 'lead_id')}",
                        )
                    with tabs[2]:
                        follow1_value = st.text_area(
                            "Follow up 1",
                            _value(row, "follow_up_1"),
                            height=220,
                            key=f"follow1_{_value(row, 'lead_id')}",
                        )
                        follow2_value = st.text_area(
                            "Follow up 2",
                            _value(row, "follow_up_2"),
                            height=220,
                            key=f"follow2_{_value(row, 'lead_id')}",
                        )
                    with tabs[3]:
                        current_status = _value(row, "status")
                        status_options = list(STATUSES)
                        status_index = (
                            status_options.index(current_status)
                            if current_status in status_options
                            else 0
                        )
                        status_value = st.selectbox(
                            "Status",
                            status_options,
                            index=status_index,
                            key=f"status_{_value(row, 'lead_id')}",
                        )
                        parsed_due = pd.to_datetime(
                            _value(row, "wiedervorlage"),
                            errors="coerce",
                        )
                        due_default = (
                            parsed_due.date()
                            if not pd.isna(parsed_due)
                            else date.today() + timedelta(days=2)
                        )
                        due_value = st.date_input(
                            "Wiedervorlage",
                            value=due_default,
                            key=f"due_{_value(row, 'lead_id')}",
                        )
                        note_value = st.text_area(
                            "Arbeitsnotiz",
                            _value(row, "notiz"),
                            key=f"note_{_value(row, 'lead_id')}",
                        )
                        lock_value = st.checkbox(
                            "Meine Textänderungen bei künftigen Läufen beibehalten",
                            value=_value(row, "text_locked") == "ja",
                            key=f"lock_{_value(row, 'lead_id')}",
                        )
                        if st.button(
                            "Änderungen speichern",
                            key=f"save_{_value(row, 'lead_id')}",
                        ):
                            updates = {
                                "call_opener": call_value,
                                "discovery_fragen": discovery_value,
                                "challenger_reframe": challenger_value,
                                "erstmail_betreff": subject_value,
                                "erstmail": mail_value,
                                "follow_up_1": follow1_value,
                                "follow_up_2": follow2_value,
                                "status": status_value,
                                "wiedervorlage": due_value.isoformat(),
                                "notiz": note_value,
                                "text_locked": "ja" if lock_value else "",
                            }
                            for column, new_value in updates.items():
                                if column in frame.columns:
                                    frame.loc[index, column] = new_value
                            persist_rows(frame.loc[[index]], frame)
                            st.success("Gespeichert.")


elif page == "Follow ups":
    st.title("Follow ups")
    today = date.today().isoformat()
    due_frame = frame[
        (_safe_series(frame, "wiedervorlage") != "")
        & (_safe_series(frame, "wiedervorlage") <= today)
        & ~_safe_series(frame, "status").isin(
            ["In Salesforce übernommen", "Ausschließen"]
        )
    ].copy()

    if due_frame.empty:
        st.success("Keine Follow ups fällig.")
    else:
        for index, row in due_frame.iterrows():
            with st.container(border=True):
                st.subheader(_value(row, "firma"))
                st.write(
                    f"**Fällig:** {_value(row, 'wiedervorlage')} · **Status:** {_value(row, 'status')}"
                )
                st.write(
                    f"**Kontakt:** {_value(row, 'ansprechpartner')} · {_value(row, 'email')} · {_value(row, 'telefon')}"
                )
                st.text_area(
                    "Follow up",
                    _value(row, "follow_up_1"),
                    height=240,
                    key=f"due_mail_{_value(row, 'lead_id')}",
                )
                action_columns = st.columns(2)
                if action_columns[0].button(
                    "In Salesforce übernommen",
                    key=f"sf_{_value(row, 'lead_id')}",
                ):
                    frame.loc[index, "status"] = "In Salesforce übernommen"
                    persist_rows(frame.loc[[index]], frame)
                    st.rerun()
                if action_columns[1].button(
                    "Noch drei Tage",
                    key=f"plus3_{_value(row, 'lead_id')}",
                ):
                    frame.loc[index, "wiedervorlage"] = (
                        date.today() + timedelta(days=3)
                    ).isoformat()
                    persist_rows(frame.loc[[index]], frame)
                    st.rerun()


elif page == "Alle Leads":
    st.title("Alle Leads")
    search = st.text_input("Suche")
    filtered = frame.copy()
    if search:
        mask = filtered.astype(str).apply(
            lambda column: column.str.contains(search, case=False, na=False)
        ).any(axis=1)
        filtered = filtered[mask]

    preferred_columns = [
        "hot_status",
        "lead_score",
        "firma",
        "pipeline_stage",
        "crm_status",
        "anzahl_stellen",
        "offene_stellen",
        "orte",
        "ansprechpartner",
        "rolle",
        "email",
        "telefon",
        "website",
        "research_status",
        "ai_status",
        "status",
        "wiedervorlage",
        "first_seen",
        "zuletzt_gefunden",
        "times_seen",
    ]
    visible_columns = [
        column for column in preferred_columns if column in filtered.columns
    ]
    table = filtered[visible_columns].copy()
    if "lead_score" in table.columns:
        table["lead_score"] = pd.to_numeric(
            table["lead_score"],
            errors="coerce",
        ).fillna(0).astype(int)

    column_config = {}
    if "website" in table.columns:
        column_config["website"] = st.column_config.LinkColumn("Website")
    if "lead_score" in table.columns:
        column_config["lead_score"] = st.column_config.NumberColumn(
            "Score",
            format="%d",
        )

    st.dataframe(
        table,
        use_container_width=True,
        hide_index=True,
        column_config=column_config,
    )

    export_csv = filtered.reindex(columns=COLUMNS).to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "Gefilterte Tabelle als CSV herunterladen",
        export_csv,
        file_name=f"xing_sales_leads_{date.today().isoformat()}.csv",
        mime="text/csv",
    )


elif page == "Ausgeschlossene Unternehmen":
    st.title("Ausgeschlossene Unternehmen")
    st.caption(
        "Diese Unternehmen werden bei neuen Suchläufen nicht mehr als Leads angelegt."
    )

    exclusions = exclusion_upload_block(
        "Datei importieren",
        "exclusion_page_v5",
        exclusions,
    )

    st.markdown("#### Manuell ergänzen")
    manual_company = st.text_input(
        "Unternehmensname",
        key="manual_exclusion_company_v5",
    )
    if st.button("Unternehmen hinzufügen", key="manual_exclusion_add_v5"):
        normalized = normalize_company(manual_company)
        if not normalized:
            st.error("Bitte einen Unternehmensnamen eingeben.")
        elif normalized in exclusions:
            st.info("Dieses Unternehmen ist bereits ausgeschlossen.")
        else:
            persist_exclusions(exclusions | {normalized})
            st.success("Unternehmen wurde ausgeschlossen.")
            st.rerun()

    st.markdown(f"#### Gespeichert: {len(exclusions)} Unternehmen")
    exclusion_frame = pd.DataFrame({"Unternehmen": sorted(exclusions)})
    st.dataframe(exclusion_frame, use_container_width=True, hide_index=True)

    export_exclusions = exclusion_frame.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "Ausschlussliste als CSV herunterladen",
        export_exclusions,
        file_name="ausgeschlossene_unternehmen.csv",
        mime="text/csv",
    )

    with st.expander("Ein Unternehmen wieder zulassen"):
        if exclusions:
            selected_company = st.selectbox(
                "Unternehmen auswählen",
                sorted(exclusions),
                key="remove_exclusion_select_v5",
            )
            if st.button(
                "Aus Ausschlussliste entfernen",
                key="remove_exclusion_button_v5",
            ):
                persist_exclusions(exclusions - {selected_company})
                st.success("Unternehmen ist bei neuen Suchläufen wieder zugelassen.")
                st.rerun()
        else:
            st.info("Es sind keine Unternehmen ausgeschlossen.")