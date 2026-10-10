from __future__ import annotations

import pandas as pd
import streamlit as st

from account_intelligence import account_briefing_text, company_profile, portfolio_snapshot


def _demo_leads() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "firma": "Muster Nord GmbH",
                "claim_score": 82,
                "need_score": 74,
                "verified_open_jobs": 3,
                "email": "recruiting@musternord.de",
                "telefon": "+49 40 555010",
                "website": "https://musternord.de",
                "job_titles": "Servicetechniker | Elektroniker | Mechatroniker",
                "verified_job_titles": "Servicetechniker | Elektroniker",
            },
            {
                "firma": "DemoWerk Holding",
                "claim_score": 64,
                "need_score": 58,
                "verified_open_jobs": 1,
                "email": "hr@demowerk.de",
                "telefon": "+49 711 1100",
                "website": "https://demowerk.de",
                "job_titles": "Systemadministrator | IT Support",
                "verified_job_titles": "Systemadministrator",
            },
            {
                "firma": "Wissen Plus GmbH",
                "claim_score": 90,
                "need_score": 88,
                "verified_open_jobs": 5,
                "email": "career@wissenplus.de",
                "telefon": "+49 30 7000",
                "website": "https://wissenplus.de",
                "job_titles": "Physiotherapeut | Ergotherapeut | Logopäde",
                "verified_job_titles": "Physiotherapeut | Ergotherapeut",
            },
        ]
    )


def _demo_jobs() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"firma": "Muster Nord GmbH", "position": "Servicetechniker", "ort": "Hamburg"},
            {"firma": "Muster Nord GmbH", "position": "Elektroniker", "ort": "Hamburg"},
            {"firma": "Muster Nord GmbH", "position": "Mechatroniker", "ort": "Bremen"},
            {"firma": "DemoWerk Holding", "position": "Systemadministrator", "ort": "Stuttgart"},
            {"firma": "Wissen Plus GmbH", "position": "Physiotherapeut", "ort": "Berlin"},
            {"firma": "Wissen Plus GmbH", "position": "Ergotherapeut", "ort": "Berlin"},
            {"firma": "Wissen Plus GmbH", "position": "Logopäde", "ort": "Leipzig"},
        ]
    )


def _demo_evidence() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"firma": "Muster Nord GmbH", "claim": "Erweiterung von Service-Standorten in Norddeutschland", "source": "Website"},
            {"firma": "DemoWerk Holding", "claim": "IT-Modernisierung und Cloud-Umzug", "source": "Presse"},
            {"firma": "Wissen Plus GmbH", "claim": "Expansion im Gesundheitsbereich und neue Standorte", "source": "Website"},
        ]
    )


st.set_page_config(page_title="KAM Portfolio Intelligence", page_icon="📊", layout="wide")

st.title("KAM Portfolio Intelligence")
st.caption("Lässt jeden Account mit Markt-, Hiring- und Wachstumsdaten in einer verständlichen Portfolio-Übersicht sichtbar werden.")

if "portfolio" not in st.session_state:
    st.session_state.portfolio = {
        "leads": _demo_leads(),
        "jobs": _demo_jobs(),
        "evidence": _demo_evidence(),
    }

leads = st.session_state.portfolio["leads"]
jobs = st.session_state.portfolio["jobs"]
evidence = st.session_state.portfolio["evidence"]

snapshot = portfolio_snapshot(leads, jobs, evidence, limit=20)

st.subheader("Portfolio-Übersicht")
if snapshot.empty:
    st.info("Noch keine Firmen im Portfolio geladen.")
else:
    st.dataframe(snapshot, use_container_width=True, hide_index=True)

companies = sorted({str(value).strip() for value in leads["firma"].dropna().tolist() if str(value).strip()})
if not companies:
    st.warning("Keine Firmen im Lead-Set gefunden.")
    st.stop()

selected = st.selectbox("Unternehmen ansehen", companies)
profile = company_profile(leads, jobs, evidence, selected)

left, right = st.columns(2)
with left:
    st.markdown("### Score & Priorität")
    st.metric("Portfolio Score", profile["score"])
    st.metric("Priorität", profile["priority"])
    st.metric("Dokumentierte Stellen", profile["job_count"])
    st.metric("Verifizierte Jobs", profile["verified_jobs"])

with right:
    st.markdown("### Signale")
    for item in profile["signals"]:
        st.write("• " + item)

st.markdown("### Hauptrollen & Standorte")
role_col, city_col = st.columns(2)
with role_col:
    st.write("**Rollen:** " + (", ".join(profile["job_titles"]) if profile["job_titles"] else "Keine klaren Rollen erkannt"))
with city_col:
    st.write("**Standorte:** " + (", ".join(profile["cities"]) if profile["cities"] else "Noch unklar"))

st.markdown("### Account Briefing")
st.write(account_briefing_text(profile))

st.markdown("### Risiken")
for risk in profile["risks"]:
    st.warning(risk)

st.markdown("### Nächste Schritte")
for item in profile["recommendations"]:
    st.write("→ " + item)

st.download_button(
    "Briefing als TXT",
    account_briefing_text(profile).encode("utf-8"),
    file_name=f"{selected.lower().replace(' ', '_')}_briefing.txt",
    mime="text/plain",
)
