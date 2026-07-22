from __future__ import annotations

import hashlib
import json
import re
from typing import Any

try:
    from openai import OpenAI
except Exception:
    OpenAI = None


ASSET_KEYS = [
    "erstmail_betreff",
    "erstmail",
    "call_opener",
    "discovery_fragen",
    "challenger_reframe",
    "follow_up_1",
    "follow_up_2",
]


def openai_available() -> bool:
    return OpenAI is not None


def _clean_single(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _clean_multiline(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    output: list[str] = []
    previous_blank = False
    for line in lines:
        if not line:
            if output and not previous_blank:
                output.append("")
            previous_blank = True
            continue
        output.append(line)
        previous_blank = False
    return "\n".join(output).strip()


def _no_customer_hyphens(text: str) -> str:
    # Kundentexte sollen keine Gedankenstriche oder Bindestriche enthalten.
    return re.sub(r"\s*[–—-]\s*", " ", text).replace("  ", " ").strip()


def _salutation(person: str) -> str:
    person = _clean_single(person)
    return f"Guten Tag {person}," if person else "Guten Tag,"


def _job_titles(jobs: list[dict]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for job in jobs:
        title = _clean_single(job.get("title", ""))
        if title and title.lower() not in seen:
            seen.add(title.lower())
            result.append(title)
    return result


def _job_family(titles: list[str]) -> str:
    text = " ".join(titles).lower()
    families = [
        ("Therapie", ("physio", "ergo", "logo", "therap")),
        ("Pflege und Medizin", ("pflege", "medizin", "mfa", "arzt", "ärzt")),
        ("Steuer und Finanzen", ("steuer", "bilanz", "buchhalt", "controller", "lohn")),
        ("Elektro und Technik", ("elektr", "mechatron", "servicetechn", "automation")),
        ("Bau und Engineering", ("bauleit", "ingenieur", "architekt", "konstruk")),
        ("IT", ("software", "developer", "devops", "systemadmin", "it support")),
        ("Vertrieb", ("vertrieb", "sales", "account manager")),
        ("Produktion und Metall", ("schweiß", "cnc", "zerspan", "industriemechan", "produktion")),
        ("Logistik", ("logistik", "lager", "fahrer", "disponent")),
    ]
    for family, keywords in families:
        if any(keyword in text for keyword in keywords):
            return family
    return "Fachkräfte"


def _fallback_assets(
    company: str,
    jobs: list[dict],
    benefits: list[str],
    person: str,
    research: dict[str, Any],
) -> dict[str, str]:
    titles = _job_titles(jobs)
    title_one = titles[0] if titles else "Ihre offenen Positionen"
    title_list = ", ".join(titles[:2]) if titles else "passenden Fachkräften"
    count = len(jobs)
    family = _job_family(titles)
    salutation = _salutation(person)
    variant = int(hashlib.sha1(company.encode("utf-8")).hexdigest()[:2], 16) % 4

    benefit_phrase = ""
    if benefits:
        benefit_phrase = ", ".join(benefits[:3])

    openings = [
        f"ich bin auf Ihre aktuelle Suche nach {title_list} aufmerksam geworden.",
        f"Sie suchen aktuell {title_list}. Gerade bei diesen Profilen entscheidet häufig nicht nur die Sichtbarkeit der Anzeige, sondern ob die richtigen Personen tatsächlich erreicht werden.",
        f"bei Ihrer aktuellen Suche nach {title_list} stellt sich für mich eine einfache Frage: Kommen über Ihre bisherigen Kanäle genug passende Bewerbungen an?",
        f"Ihre offenen Positionen im Bereich {family} sind mir aufgefallen. Mich würde interessieren, wie planbar die Besetzung für Sie aktuell funktioniert.",
    ]
    opening = openings[variant]
    if benefit_phrase:
        opening += f" Mit {benefit_phrase} bringen Sie bereits konkrete Argumente für einen Wechsel mit."

    if count >= 3:
        question = "Geht es bei Ihnen gerade um einzelne Vakanzen oder ist die planbare Besetzung mehrerer Positionen das eigentliche Thema?"
    else:
        question = "Erreichen Sie aktuell genügend passende Fachkräfte oder bleibt die Besetzung trotz Ihrer bisherigen Maßnahmen schwierig?"

    mail = f"""{salutation}

bei {company} ist mir die aktuelle Suche nach {title_list} aufgefallen. {opening}

{question}

Ich würde Ihnen gern kurz zeigen, wie sich Ihr bestehendes Recruiting sinnvoll über XING ergänzen lässt. Ist ein Austausch von zehn Minuten grundsätzlich interessant?

Viele Grüße
Berkant Devrim
Account Executive | XING"""

    opener = (
        f"Guten Tag, Berkant Devrim von XING. Ich komme direkt zum Punkt. "
        f"Bei {company} suchen Sie aktuell {title_list}. Ich vermute, dass die Besetzung nicht vollständig planbar läuft, sonst wäre die Suche vermutlich nicht mehr offen. Liege ich damit falsch?"
    )

    discovery = "\n".join([
        f"1. Welche der offenen Positionen beschäftigt Sie aktuell am meisten?",
        "2. Was macht genau diese Besetzung derzeit schwierig?",
        "3. Welche Auswirkungen hat die offene Position auf Ihr Unternehmen oder Ihren Arbeitsalltag?",
        "4. Welche Recruiting Kanäle nutzen Sie aktuell und welche Rolle spielt jeder davon?",
        "5. Wie viele Bewerbungen kommen darüber an und wie viele davon sind wirklich passend?",
        "6. Handelt es sich um einen Einzelfall oder möchten Sie dieses Jahr weitere Positionen besetzen?",
        "7. Woran würden Sie erkennen, dass sich eine zusätzliche Recruiting Lösung für Sie gelohnt hat?",
        "8. Wie laufen solche Entscheidungen bei Ihnen normalerweise ab?",
    ])

    if count >= 3:
        challenger = (
            "Viele Unternehmen lösen einzelne Vakanzen nacheinander. Die eigentliche Herausforderung ist jedoch, "
            "den gesamten Personalbedarf planbar abzudecken, bevor bei jeder neuen Stelle wieder von vorne begonnen wird. "
            "Wie ist Ihr Recruiting heute darauf vorbereitet?"
        )
    elif benefits:
        challenger = (
            "Gute Rahmenbedingungen allein lösen die Besetzung noch nicht. Entscheidend ist, ob genau die passenden "
            "Fachkräfte diese Argumente sehen und sich angesprochen fühlen. Wie gut gelingt Ihnen das aktuell?"
        )
    else:
        challenger = (
            "Viele Unternehmen erreichen die aktiv Suchenden bereits über klassische Stellenbörsen. Die größere Lücke "
            "entsteht häufig bei Fachkräften, die nicht aktiv suchen, aber für einen passenden Wechsel offen wären. "
            "Wie decken Sie diese Zielgruppe heute ab?"
        )

    follow1 = f"""{salutation}

ich greife meine Frage zur aktuellen Suche bei {company} nach {title_list} noch einmal auf.

Kommen über Ihre bisherigen Kanäle genügend passende Bewerbungen an oder lohnt sich ein kurzer Blick auf eine zusätzliche Zielgruppe über XING?

Viele Grüße
Berkant Devrim"""

    follow2 = f"""{salutation}

ist die Suche bei {company} nach {title_one} inzwischen erfolgreich abgeschlossen, hake ich das Thema gerne ab.

Falls die Position noch offen ist, können wir in zehn Minuten prüfen, ob XING für das gesuchte Profil sinnvoll ist.

Viele Grüße
Berkant Devrim"""

    result = {
        "erstmail_betreff": f"{company}: {title_one}"[:70],
        "erstmail": mail,
        "call_opener": opener,
        "discovery_fragen": discovery,
        "challenger_reframe": challenger,
        "follow_up_1": follow1,
        "follow_up_2": follow2,
        "ai_status": "Fallback genutzt",
    }
    for key in ASSET_KEYS:
        result[key] = _no_customer_hyphens(_clean_multiline(result[key]))
    return result


def _extract_json_object(raw: str) -> dict[str, Any]:
    raw = str(raw or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.S)
        if not match:
            raise ValueError("Kein JSON Objekt in der KI Antwort gefunden.")
        return json.loads(match.group(0))


def _response_text(response: Any) -> str:
    direct = getattr(response, "output_text", "")
    if direct:
        return direct
    chunks: list[str] = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", "")
            if text:
                chunks.append(text)
    return "\n".join(chunks)


def create_sales_assets(
    *,
    company: str,
    jobs: list[dict],
    benefits: list[str],
    person: str,
    research: dict[str, Any] | None,
    api_key: str,
    model: str = "gpt-5-mini",
) -> dict[str, str]:
    research = research or {}
    fallback = _fallback_assets(company, jobs, benefits, person, research)
    if OpenAI is None:
        fallback["ai_status"] = "Fallback: OpenAI Paket fehlt"
        return fallback
    if not api_key:
        fallback["ai_status"] = "Fallback: OpenAI Key fehlt"
        return fallback

    titles = _job_titles(jobs)
    cities = []
    for job in jobs:
        city = _clean_single(job.get("city", ""))
        if city and city not in cities:
            cities.append(city)
    descriptions = "\n".join(
        _clean_single(job.get("description", ""))[:1800]
        for job in jobs[:5]
        if job.get("description")
    )
    website_text = _clean_single(research.get("text", ""))[:6000]

    prompt = f"""
Du erstellst für Berkant Devrim, Account Executive bei XING, Vertriebsunterlagen für einen Cold Call.
Nutze ausschließlich die unten gelieferten Fakten. Erfinde keinerlei Preise, Rabatte, Laufzeiten, Aktionen,
Reichweiten, Produktfunktionen, Benchmarks, Ergebnisse, Unternehmensdaten oder Ansprechpartner.
Wenn wenig Fakten vorhanden sind, formuliere zurückhaltend statt etwas zu ergänzen.

Stil:
Kurz, menschlich, professionell, konkret und ohne Werbeton.
Keine unnötige Einleitung, kein Schleimen, keine künstliche Verknappung.
Verwende in Kundentexten keine Bindestriche oder Gedankenstriche.
Keine Anrede Frau oder Herr, wenn das Geschlecht nicht eindeutig geliefert wurde.
Die Ansprache ist ausschließlich für Kaltakquise.

Sales Cockpit Logik:
Opener und Frame, Discovery, Recruiting Setup, Basket Size, Challenger Reframe,
Kaufkriterien, XING als logische Konsequenz, Take Control und Abschluss.
Die Mail selbst bleibt trotzdem sehr kurz und versucht nicht, das ganze Gespräch vorwegzunehmen.

Fakten:
Unternehmen: {company}
Ansprechpartner: {person or "nicht sicher bekannt"}
Rolle des Ansprechpartners: {_clean_single(research.get("role", "")) or "nicht sicher bekannt"}
Offene Rollen: {", ".join(titles[:6]) or "nicht eindeutig"}
Anzahl gefundener Stellen: {len(jobs)}
Orte: {", ".join(cities[:6]) or "nicht eindeutig"}
Erkannte Benefits: {", ".join(benefits[:10]) or "keine eindeutig erkannt"}
Website: {_clean_single(research.get("website", "")) or "nicht gefunden"}
Informationen aus Stellenanzeigen: {descriptions or "keine belastbaren Informationen"}
Informationen von der Website: {website_text or "keine belastbaren Informationen"}

Gib ausschließlich ein valides JSON Objekt mit genau diesen Schlüsseln zurück:
erstmail_betreff
erstmail
call_opener
discovery_fragen
challenger_reframe
follow_up_1
follow_up_2

Vorgaben:
Der Betreff hat höchstens sieben Wörter und nennt einen konkreten Anlass.
Die Erstmail hat höchstens 100 Wörter, nennt genau einen belegten Anlass und endet mit einer einfachen Frage.
Der Call Opener hat höchstens 50 Wörter und setzt einen klaren Frame statt sofort ein Produkt zu erklären.
Die Discovery Fragen bestehen aus acht nummerierten Fragen in logischer Reihenfolge.
Der Challenger Reframe besteht aus höchstens 55 Wörtern und passt konkret zur erkannten Situation.
Follow Up 1 und Follow Up 2 haben jeweils höchstens 70 Wörter.
Keine Markdown Formatierung.
"""

    try:
        client = OpenAI(api_key=api_key, timeout=45.0, max_retries=1)
        response = client.responses.create(model=model, input=prompt)
        data = _extract_json_object(_response_text(response))
        result: dict[str, str] = {}
        for key in ASSET_KEYS:
            value = _clean_multiline(data.get(key, ""))
            result[key] = _no_customer_hyphens(value) if value else fallback[key]
        result["ai_status"] = f"KI erstellt: {model}"
        return result
    except Exception as exc:
        fallback["ai_status"] = f"Fallback nach KI Fehler: {str(exc)[:180]}"
        return fallback
