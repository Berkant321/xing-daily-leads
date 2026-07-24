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

EXTRA_ASSET_KEYS = [
    "personalization_evidence",
    "mail_variant",
]

REQUIRED_MAIL_PHRASES = (
    "XING Kampagne",
    "nicht nur darum",
    "gezielt",
    "direkt ansprechen",
    "drehen Sie den Spieß um",
    "vormittags oder nachmittags",
)


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
    # Kundentexte enthalten keine Gedankenstriche oder Bindestriche.
    text = re.sub(r"\s*[–—]\s*", " ", text)
    text = re.sub(r"(?<!\w)-(?!\w)", " ", text)
    return re.sub(r" {2,}", " ", text).strip()


def _salutation(person: str) -> str:
    person = _clean_single(person).strip(" ,")
    if not person:
        return "Guten Tag,"
    match = re.match(r"^(Frau|Herr)\s+(.+)$", person, re.I)
    if match:
        title = "Frau" if match.group(1).lower() == "frau" else "Herr"
        name = match.group(2).strip()
        parts = name.split()
        surname = " ".join(parts[-2:]) if parts and parts[-2].lower() in {"von", "van", "de"} else parts[-1]
        return f"Guten Tag {title} {surname},"
    return f"Guten Tag {person},"


def _job_titles(jobs: list[dict]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for job in jobs:
        title = _clean_single(job.get("title", ""))
        if title and title.lower() not in seen and title.lower() not in {"offene positionen", "offene stellen"}:
            seen.add(title.lower())
            result.append(title)
    return result


def _natural_join(values: list[str], limit: int = 3) -> str:
    values = [value for value in values[:limit] if value]
    if not values:
        return "passenden Fachkräften"
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} und {values[1]}"
    return f"{', '.join(values[:-1])} sowie {values[-1]}"


def _job_family(titles: list[str]) -> str:
    text = " ".join(titles).lower()
    families = [
        ("Therapie", ("physio", "ergo", "logo", "therap")),
        ("Pflege und Medizin", ("pflege", "medizin", "mfa", "arzt", "zahn")),
        ("Steuer und Finanzen", ("steuer", "bilanz", "buchhalt", "controller", "lohn", "finanz")),
        ("Recht", ("rechtsanw", "jurist", "legal", "notar")),
        ("Elektro und Technik", ("elektr", "mechatron", "servicetechn", "automation", "instand")),
        ("Bau und Engineering", ("bauleit", "ingenieur", "architekt", "konstruk", "tga", "kalkulat")),
        ("IT", ("software", "developer", "devops", "systemadmin", "it support", "data")),
        ("Vertrieb und Marketing", ("vertrieb", "sales", "account manager", "marketing", "business development")),
        ("Produktion und Metall", ("schweiß", "cnc", "zerspan", "industriemechan", "produktion", "maschinen")),
        ("Logistik", ("logistik", "lager", "fahrer", "disponent", "spedition")),
        ("Pharma und Forschung", ("pharma", "labor", "chemie", "regulatory", "clinical", "apothe")),
        ("Verwaltung und Personal", ("sachbear", "assistenz", "personal", "recruit", "office", "kaufm")),
    ]
    for family, keywords in families:
        if any(keyword in text for keyword in keywords):
            return family
    return "Fachkräfte"


def _benefit_sentence(benefits: list[str], family: str, cities: list[str]) -> tuple[str, str]:
    usable = [_clean_single(value) for value in benefits if _clean_single(value)]
    benefit_phrases = {
        "Homeoffice": "Homeoffice",
        "Flexible Arbeitszeiten": "flexiblen Arbeitszeiten",
        "4 Tage Woche": "einer 4 Tage Woche",
        "30 oder mehr Tage Urlaub": "30 oder mehr Tagen Urlaub",
        "JobRad": "einem JobRad",
        "Jobticket": "einem Jobticket",
        "Weiterbildung": "guten Weiterbildungsmöglichkeiten",
        "Betriebliche Altersvorsorge": "betrieblicher Altersvorsorge",
        "Bonus oder Prämien": "zusätzlichen Bonusmöglichkeiten",
        "Keine Wochenendarbeit": "Arbeitszeiten ohne Wochenendarbeit",
        "Keine Überstunden": "verlässlichen Arbeitszeiten ohne Überstunden",
        "Unbefristet": "unbefristeten Verträgen",
        "Digitale Arbeitsweise": "einer digitalen Arbeitsweise",
        "Familiäres Team": "einem familiären Team",
    }
    if usable:
        grammar_ready = [benefit_phrases.get(value, value) for value in usable]
        chosen = _natural_join(grammar_ready, limit=3)
        return (
            f"Mit {chosen} bieten Sie dabei bereits Rahmenbedingungen, die für wechselbereite Fachkräfte interessant sein können.",
            "erkannte Benefits: " + ", ".join(usable[:3]),
        )
    if cities:
        return (
            f"Damit sprechen Sie in {cities[0]} eine Zielgruppe an, die über klassische Stellenportale häufig nur teilweise erreichbar ist.",
            f"aktuelle Suche in {cities[0]}",
        )
    return (
        f"Gerade im Bereich {family} sind viele passende Fachkräfte nicht aktiv auf Stellenportalen unterwegs.",
        f"aktuelle Suche im Bereich {family}",
    )


def _fallback_assets(
    company: str,
    jobs: list[dict],
    benefits: list[str],
    person: str,
    research: dict[str, Any],
) -> dict[str, str]:
    titles = _job_titles(jobs)
    title_phrase = _natural_join(titles, limit=3)
    title_one = titles[0] if titles else "Ihre offenen Positionen"
    family = _job_family(titles)
    cities: list[str] = []
    for job in jobs:
        city = _clean_single(job.get("city", ""))
        if city and city not in cities:
            cities.append(city)
    salutation = _salutation(person)
    context_sentence, evidence = _benefit_sentence(benefits, family, cities)

    mail = f"""{salutation}

Sie suchen aktuell {title_phrase}. {context_sentence}

Deshalb möchte ich Sie zu unserer aktuellen XING Kampagne einladen.

Dabei geht es nicht nur darum, die offenen Positionen zu veröffentlichen und auf Bewerbungen zu warten. Sie können passende Fachkräfte gezielt identifizieren und direkt ansprechen, auch wenn diese aktuell nicht aktiv nach einer neuen Aufgabe suchen.

So drehen Sie den Spieß um und entscheiden selbst, welche Kandidatinnen und Kandidaten Sie für {company} kennenlernen möchten.

Passt Ihnen ein kurzer Austausch kommende Woche eher vormittags oder nachmittags?

Beste Grüße
Berkant Devrim
Senior Account Executive
XING"""

    opener = (
        f"Guten Tag, Berkant Devrim von XING. Ich komme direkt zum Punkt. "
        f"Bei {company} suchen Sie aktuell {title_phrase}. Mich interessiert, ob über Ihre bisherigen Kanäle "
        "genügend passende Bewerbungen ankommen oder ob die Besetzung weiterhin schwer planbar ist."
    )

    discovery = "\n".join([
        f"1. Welche der offenen Positionen hat für Sie aktuell die höchste Priorität?",
        "2. Seit wann suchen Sie für diese Position?",
        "3. Wie viele passende Bewerbungen sind bisher tatsächlich angekommen?",
        "4. Welche Kanäle nutzen Sie aktuell und was funktioniert davon zuverlässig?",
        "5. Woran scheitert die Besetzung bisher am häufigsten?",
        "6. Welche Auswirkungen hat die offene Position auf Team, Umsatz oder Arbeitsbelastung?",
        "7. Welche weiteren Einstellungen planen Sie in den kommenden zwölf Monaten?",
        "8. Wer entscheidet bei Ihnen über eine zusätzliche Recruiting Lösung und nach welchen Kriterien?",
    ])

    challenger = (
        "Viele Unternehmen erreichen über klassische Stellenportale vor allem aktiv Suchende. "
        "Die größere Lücke entsteht bei passenden Fachkräften, die nicht suchen, aber für ein überzeugendes Angebot offen wären. "
        "Genau diese Zielgruppe entscheidet häufig darüber, ob eine Besetzung planbar wird."
    )

    follow1 = f"""{salutation}

ich greife meine Einladung für {company} noch einmal auf.

Die entscheidende Frage ist, ob Sie bei Ihrer aktuellen Suche ausschließlich auf aktiv Bewerbende angewiesen bleiben möchten oder passende Fachkräfte zusätzlich selbst auswählen und ansprechen wollen.

Passt ein kurzer Austausch eher vormittags oder nachmittags?

Beste Grüße
Berkant Devrim"""

    follow2 = f"""{salutation}

ist die Suche nach {title_one} inzwischen erfolgreich abgeschlossen, hake ich das Thema gerne ab.

Falls die Position noch offen ist, können wir in einem kurzen Austausch prüfen, welche passenden Fachkräfte Sie über XING gezielt erreichen können.

Beste Grüße
Berkant Devrim"""

    result = {
        "erstmail_betreff": f"Exklusive Einladung | {company}",
        "erstmail": mail,
        "call_opener": opener,
        "discovery_fragen": discovery,
        "challenger_reframe": challenger,
        "follow_up_1": follow1,
        "follow_up_2": follow2,
        "personalization_evidence": evidence,
        "mail_variant": "Exklusive Einladung V1",
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


def _valid_campaign_mail(mail: str, company: str) -> bool:
    text = _clean_multiline(mail)
    words = len(re.findall(r"\b\w+\b", text))
    if not 105 <= words <= 195:
        return False
    if company.lower() not in text.lower():
        return False
    return all(phrase.lower() in text.lower() for phrase in REQUIRED_MAIL_PHRASES)


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
    cities: list[str] = []
    for job in jobs:
        city = _clean_single(job.get("city", ""))
        if city and city not in cities:
            cities.append(city)
    descriptions = "\n".join(
        f"{_clean_single(job.get('title', ''))}: {_clean_single(job.get('description', ''))[:2200]}"
        for job in jobs[:8]
        if job.get("description")
    )[:12000]
    website_text = _clean_single(research.get("text", ""))[:12000]
    exact_subject = f"Exklusive Einladung | {company}"
    deterministic_variant = int(hashlib.sha1(company.encode("utf-8")).hexdigest()[:2], 16) % 2 + 1

    prompt = f"""
Du schreibst für Berkant Devrim, Senior Account Executive bei XING, eine maßgeschneiderte Kaltakquise.
Nutze ausschließlich die gelieferten Fakten. Erfinde keine Benefits, Unternehmensmerkmale, Kennzahlen, Preise, Rabatte, Ergebnisse, Ansprechpartner oder Produktfunktionen.

Verbindlicher Stil der Erstmail:
1. Der Betreff lautet exakt: {exact_subject}
2. Beginne mit einer korrekten persönlichen Anrede. Wenn Frau oder Herr nicht sicher geliefert wurde, erfinde keine geschlechtliche Anrede.
3. Der erste Absatz nennt die aktuelle Personalsuche und genau ein belegtes, individuelles Merkmal des Unternehmens oder der Stellen. Kein Lob und keine Schleimerei.
4. Danach steht als eigener Absatz exakt sinngemäß: Deshalb möchte ich Sie zu unserer aktuellen XING Kampagne einladen.
5. Erkläre, dass es nicht nur darum geht, Stellen zu veröffentlichen und auf Bewerbungen zu warten. Passende Fachkräfte sollen gezielt identifiziert und direkt angesprochen werden können.
6. Nutze ausdrücklich den Gedanken: So drehen Sie den Spieß um und entscheiden selbst, welche Fachkräfte Sie kennenlernen möchten.
7. Die Abschlussfrage lautet: Passt Ihnen ein kurzer Austausch kommende Woche eher vormittags oder nachmittags?
8. Signatur: Beste Grüße, Berkant Devrim, Senior Account Executive, XING.
9. Die Erstmail umfasst 120 bis 175 Wörter.
10. Keine Bindestriche, keine Gedankenstriche, keine Produktliste, keine Preise, keine unbelegten XING Kennzahlen, keine künstliche Verknappung.
11. Ruhig, direkt, professionell und menschlich. Kein Werbeton.

Call und Gespräch:
Der Call Opener setzt einen klaren Frame und fragt nach der tatsächlichen Besetzbarkeit.
Die acht Discovery Fragen folgen dieser Logik: Priorität, Suchdauer, Bewerbungseingang, Qualität, bisherige Kanäle, geschäftliche Auswirkung, künftiger Bedarf, Entscheidung.
Der Challenger Reframe erklärt knapp die Lücke zwischen aktiv Suchenden und wechselbereiten Fachkräften.
Die Follow ups bleiben freundlich, konkret und enthalten keinen neuen unbelegten Fakt.

Fakten:
Unternehmen: {company}
Ansprechpartner: {person or 'nicht sicher bekannt'}
Rolle des Ansprechpartners: {_clean_single(research.get('role', '')) or 'nicht sicher bekannt'}
Offene Rollen: {', '.join(titles[:8]) or 'nicht eindeutig'}
Anzahl gefundener Stellen: {len(jobs)}
Orte: {', '.join(cities[:8]) or 'nicht eindeutig'}
Erkannte Benefits: {', '.join(benefits[:12]) or 'keine eindeutig erkannt'}
Website: {_clean_single(research.get('website', '')) or 'nicht gefunden'}
Informationen aus Stellenanzeigen: {descriptions or 'keine belastbaren Informationen'}
Informationen von der Website: {website_text or 'keine belastbaren Informationen'}

Gib ausschließlich ein valides JSON Objekt mit genau diesen Schlüsseln zurück:
erstmail_betreff
erstmail
call_opener
discovery_fragen
challenger_reframe
follow_up_1
follow_up_2
personalization_evidence
mail_variant

personalization_evidence nennt in höchstens 25 Wörtern den konkreten belegten Fakt, auf dem der erste Absatz basiert.
mail_variant lautet Exklusive Einladung V{deterministic_variant}.
Keine Markdown Formatierung.
"""

    try:
        client = OpenAI(api_key=api_key, timeout=60.0, max_retries=1)
        response = client.responses.create(model=model, input=prompt)
        data = _extract_json_object(_response_text(response))
        result: dict[str, str] = {}
        for key in ASSET_KEYS:
            value = _clean_multiline(data.get(key, ""))
            result[key] = _no_customer_hyphens(value) if value else fallback[key]
        result["erstmail_betreff"] = exact_subject
        if not _valid_campaign_mail(result["erstmail"], company):
            result["erstmail"] = fallback["erstmail"]
            mail_source = "Mailstruktur durch Fallback gesichert"
        else:
            mail_source = "KI Mail geprüft"
        result["personalization_evidence"] = _clean_single(
            data.get("personalization_evidence", "")
        )[:300] or fallback["personalization_evidence"]
        result["mail_variant"] = _clean_single(data.get("mail_variant", "")) or fallback["mail_variant"]
        result["ai_status"] = f"KI erstellt: {model}, {mail_source}"
        return result
    except Exception as exc:
        fallback["ai_status"] = f"Fallback nach KI Fehler: {str(exc)[:180]}"
        return fallback
