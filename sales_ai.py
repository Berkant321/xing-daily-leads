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

TESTPILOT_CAMPAIGN = "Testpilot Therapie 500"
MONDAY_WAVE_CAMPAIGN = "Montagswelle 500 | Testpilot Fachkräfte"
DIAMOND_RADAR_CAMPAIGN = "Diamanten Radar | kleine Direktkunden"
TESTPILOT_REQUIRED_PHRASES = (
    "zwei Monate",
    "zwölf Monate",
    "Stellenanzeige",
    "TalentManager",
    "direkt ansprechen",
    "Position noch offen",
)
MONDAY_REQUIRED_PHRASES = (
    "zwei Monate",
    "zwölf Monate",
    "Stellenanzeige",
    "TalentManager",
    "direkt ansprechen",
    "Klingt",
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
        surname = " ".join(parts[-2:]) if len(parts) >= 2 and parts[-2].lower() in {"von", "van", "de"} else parts[-1]
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



def _testpilot_assets(
    company: str,
    jobs: list[dict],
    benefits: list[str],
    person: str,
    research: dict[str, Any],
) -> dict[str, str]:
    titles = _job_titles(jobs)
    title_phrase = _natural_join(titles, limit=3)
    title_one = titles[0] if titles else "Ihre offene Position"
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

Genau deshalb möchte ich Sie als Testpilot zu unserer aktuellen XING Kampagne einladen.

Statt sich direkt für zwölf Monate festzulegen, können Sie eine XING Stellenanzeige und den TalentManager zwei Monate im eigenen Recruiting testen. Die Anzeige sorgt für Sichtbarkeit und eingehende Bewerbungen. Parallel können Sie passende Fachkräfte selbst auswählen und direkt ansprechen, auch wenn diese aktuell nicht aktiv suchen.

So warten Sie nicht nur darauf, wer sich bewirbt, sondern entscheiden selbst, wen Sie für {company} kennenlernen möchten.

Ist die Position noch offen?

Beste Grüße
Berkant Devrim
Senior Account Executive
XING"""

    opener = (
        f"Guten Tag, Berkant Devrim von XING. Ich komme direkt zum Punkt. "
        f"Bei {company} suchen Sie aktuell {title_phrase}. Wir öffnen gerade einen Testlauf, "
        "bei dem Stellenanzeige und TalentManager zwei Monate statt direkt zwölf Monate genutzt werden können. "
        "Wie lösen Sie die Suche aktuell und wo fehlt Ihnen noch die passende Resonanz?"
    )

    discovery = "\n".join([
        "1. Welche therapeutische Position hat aktuell die höchste Priorität?",
        "2. Seit wann ist die Stelle offen?",
        "3. Wie viele fachlich passende Bewerbungen sind bisher angekommen?",
        "4. Über welche Kanäle suchen Sie aktuell?",
        "5. Erreichen Sie dort nur aktiv Suchende oder auch wechselbereite Fachkräfte?",
        "6. Welche Folgen hat die offene Stelle für Auslastung, Termine und Team?",
        "7. Welche weiteren Einstellungen planen Sie in den kommenden zwölf Monaten?",
        "8. Was müsste ein zweimonatiger Testlauf zeigen, damit Sie ihn als sinnvoll bewerten?",
    ])

    challenger = (
        "Eine einzelne Anzeige erreicht vor allem Menschen, die gerade aktiv suchen. "
        "Die größere Reserve liegt bei Therapeutinnen und Therapeuten, die beschäftigt sind, "
        "aber für bessere Bedingungen offen wären. Der Testlauf verbindet beide Wege, ohne direkt zwölf Monate festzulegen."
    )

    follow1 = f"""{salutation}

ich greife meine Einladung für {company} noch einmal auf.

Der Testlauf verbindet eine XING Stellenanzeige mit dem TalentManager für zwei Monate. Sie gewinnen Bewerbungen und können parallel passende Fachkräfte selbst auswählen und direkt ansprechen, statt sich sofort für zwölf Monate festzulegen.

Ist {title_one} weiterhin offen?

Beste Grüße
Berkant Devrim"""

    follow2 = f"""{salutation}

ist die Position inzwischen besetzt, hake ich das Thema gerne ab.

Falls die Suche noch offen ist, können Sie Stellenanzeige und TalentManager zwei Monate im eigenen Recruiting testen und danach auf Grundlage Ihrer Ergebnisse entscheiden.

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
        "mail_variant": "Testpilot Therapie V1",
        "ai_status": "Fallback genutzt",
    }
    for key in ASSET_KEYS:
        result[key] = _no_customer_hyphens(_clean_multiline(result[key]))
    return result

def _monday_assets(
    company: str,
    jobs: list[dict],
    benefits: list[str],
    person: str,
    research: dict[str, Any],
) -> dict[str, str]:
    titles = _job_titles(jobs)
    title_phrase = _natural_join(titles, limit=3)
    title_one = titles[0] if titles else "Ihre offene Position"
    family = _job_family(titles)
    salutation = _salutation(person)
    usable = [_clean_single(value) for value in benefits if _clean_single(value)]

    if len(usable) >= 2:
        benefit_phrases = {
            "Homeoffice": "Homeoffice",
            "Flexible Arbeitszeiten": "flexiblen Arbeitszeiten",
            "4 Tage Woche": "einer 4 Tage Woche",
            "30 oder mehr Tage Urlaub": "30 oder mehr Tagen Urlaub",
            "JobRad": "JobRad",
            "Jobticket": "Jobticket",
            "Weiterbildung": "Weiterbildungsmöglichkeiten",
            "Betriebliche Altersvorsorge": "betrieblicher Altersvorsorge",
            "Bonus oder Prämien": "zusätzlichen Bonusmöglichkeiten",
            "Keine Wochenendarbeit": "Arbeitszeiten ohne Wochenendarbeit",
            "Keine Überstunden": "verlässlichen Arbeitszeiten",
            "Unbefristet": "unbefristeten Verträgen",
            "Digitale Arbeitsweise": "einer digitalen Arbeitsweise",
            "Familiäres Team": "einem familiären Team",
        }
        shown = _natural_join([benefit_phrases.get(x, x) for x in usable], limit=2)
        intro = (
            f"Sie suchen aktuell {title_phrase}. Mit {shown} bieten Sie als Arbeitgeber bereits deutlich mehr "
            "als nur den klassischen Obstkorb."
        )
        evidence = "erkannte Benefits: " + ", ".join(usable[:2])
    else:
        intro = (
            f"Sie suchen aktuell {title_phrase}. Gerade bei {family} würde ich mich nicht darauf verlassen, "
            "dass die passenden Fachkräfte selbst aktiv nach einer neuen Stelle suchen."
        )
        evidence = f"aktuelle Suche: {title_phrase}"

    mail = f"""{salutation}

{intro}

Genau deshalb möchte ich Sie zu unserer aktuellen XING Testkampagne einladen. Statt sich direkt für zwölf Monate festzulegen, können Sie eine XING Stellenanzeige und den TalentManager zwei Monate im eigenen Recruiting testen.

Die Stellenanzeige bringt Sichtbarkeit und Bewerbungen. Parallel können Sie passende und wechselwillige Fachkräfte selbst finden und direkt ansprechen. So warten Sie nicht nur darauf, wer sich bewirbt, sondern entscheiden selbst, wen Sie kennenlernen möchten.

Klingt das für Ihre aktuelle Suche spannend?

Beste Grüße aus Münster
Berkant Devrim"""

    opener = (
        f"Guten Tag, Berkant Devrim von XING. Ich komme direkt zum Punkt. Bei {company} suchen Sie aktuell {title_phrase}. "
        "Wir haben gerade eine Testmöglichkeit, bei der Sie Stellenanzeige und TalentManager zwei Monate statt direkt zwölf Monate nutzen können. "
        "Wie läuft die Suche aktuell und wo fehlt Ihnen noch die passende Resonanz?"
    )
    discovery = "\n".join([
        "1. Welche Position hat aktuell die höchste Priorität?",
        "2. Seit wann suchen Sie dafür?",
        "3. Wie viele fachlich passende Bewerbungen kommen aktuell tatsächlich an?",
        "4. Welche Kanäle funktionieren bei Ihnen heute am besten?",
        "5. Wo verlieren Sie im aktuellen Recruitingprozess die meisten passenden Kandidaten?",
        "6. Welche Auswirkung hat die offene Stelle auf Team, Auslastung oder Wachstum?",
        "7. Welche weiteren Einstellungen planen Sie in den kommenden zwölf Monaten?",
        "8. Was müsste ein zweimonatiger Test zeigen, damit Sie ihn als erfolgreich bewerten?",
    ])
    challenger = (
        "Eine klassische Anzeige erreicht vor allem aktiv Suchende. Der größere Hebel liegt häufig bei passenden Fachkräften, "
        "die beschäftigt sind, aber für einen guten Wechsel offen wären. Der Testlauf verbindet beide Wege, ohne direkt zwölf Monate festzulegen."
    )
    follow1 = f"""{salutation}

ich greife meine Einladung für {company} noch einmal kurz auf.

Statt direkt zwölf Monate festzulegen, können Sie Stellenanzeige und TalentManager zwei Monate testen und dabei Bewerbungen mit der direkten Ansprache wechselwilliger Fachkräfte verbinden.

Ist {title_one} weiterhin offen?

Beste Grüße aus Münster
Berkant Devrim"""
    follow2 = f"""{salutation}

falls {title_one} inzwischen besetzt ist, hake ich das Thema gerne ab.

Falls die Suche noch läuft, können wir kurz prüfen, ob der zweimonatige Testlauf für {company} sinnvoll ist.

Beste Grüße aus Münster
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
        "mail_variant": "Montagswelle Testpilot V1",
        "ai_status": "Fallback genutzt",
    }
    for key in ASSET_KEYS:
        result[key] = _no_customer_hyphens(_clean_multiline(result[key]))
    return result


def _radar_assets(
    company: str,
    jobs: list[dict],
    benefits: list[str],
    person: str,
    research: dict[str, Any],
) -> dict[str, str]:
    salutation = _salutation(person)
    need_signal = _clean_single(research.get("need_signal", ""))
    diamond_reason = _clean_single(research.get("diamond_reason", ""))
    website = _clean_single(research.get("website", ""))
    career_page = _clean_single(research.get("career_page", ""))

    if career_page and need_signal and "Kein öffentlicher" not in need_signal:
        intro = f"bei {company} ist ein eigener Karrierebereich sichtbar. {need_signal}."
        evidence = f"Karrierebereich: {need_signal}"
    elif website:
        intro = f"ich bin bei meiner Recherche auf {company} als regionalen Arbeitgeber gestoßen."
        evidence = diamond_reason or "eigene Unternehmenswebsite und regionaler Firmenfund"
    else:
        intro = f"ich bin bei meiner Recherche auf {company} als regionales Unternehmen gestoßen."
        evidence = diamond_reason or "regionaler Firmenfund"

    mail = f"""{salutation}

{intro}

Ich spreche aktuell bewusst mit kleineren Unternehmen, bei denen Personalbedarf nicht immer auf den großen Stellenbörsen sichtbar ist.

Wenn bei Ihnen neue Fachkräfte gebraucht werden, können Sie über XING nicht nur Stellen sichtbar machen, sondern passende und wechselbereite Fachkräfte gezielt finden und direkt ansprechen.

Mich interessiert deshalb weniger, ob heute bereits eine konkrete Stelle online ist, sondern wie Sie neuen Personalbedarf aktuell lösen.

Wäre ein kurzer Austausch dazu grundsätzlich interessant?

Beste Grüße aus Münster
Berkant Devrim"""

    opener = (
        f"Guten Tag, Berkant Devrim von XING. Ich bin bei meiner Recherche auf {company} gestoßen. "
        "Ich spreche gerade bewusst mit kleineren regionalen Arbeitgebern, bei denen Personalbedarf nicht immer öffentlich ausgeschrieben wird. "
        "Wie lösen Sie es heute, wenn kurzfristig eine passende Fachkraft gebraucht wird?"
    )
    discovery = "\n".join([
        "1. Wie entsteht bei Ihnen typischerweise neuer Personalbedarf?",
        "2. Welche Fachkräfte sind für Sie grundsätzlich am schwersten zu finden?",
        "3. Nutzen Sie heute eher Empfehlungen, eigene Netzwerke oder Stellenbörsen?",
        "4. Wie gut funktioniert das, wenn eine Position kurzfristig besetzt werden muss?",
        "5. Welche Profile würden Sie auch ohne akute Ausschreibung kennenlernen?",
        "6. Wer kümmert sich bei Ihnen um Recruiting, wenn Bedarf entsteht?",
        "7. Welche Einstellungen erwarten Sie in den kommenden zwölf Monaten?",
        "8. Was müsste ein zusätzlicher Recruiting Kanal leisten, damit er für Sie relevant wird?",
    ])
    challenger = (
        "Gerade kleinere Arbeitgeber veröffentlichen Personalbedarf oft erst dann, wenn die Lücke bereits da ist. "
        "Ein eigener Zugang zu wechselbereiten Fachkräften schafft vorher eine zusätzliche Option, ohne dass dauerhaft Stellen ausgeschrieben sein müssen."
    )
    follow1 = f"""{salutation}

ich greife meine Nachricht zu {company} noch einmal kurz auf.

Mir geht es nicht darum, Ihnen eine offene Stelle zu unterstellen. Spannend ist vielmehr, wie Sie passende Fachkräfte erreichen, sobald bei Ihnen neuer Personalbedarf entsteht.

Wäre ein kurzer Austausch dazu grundsätzlich interessant?

Beste Grüße aus Münster
Berkant Devrim"""
    follow2 = f"""{salutation}

falls das Thema Personalgewinnung bei Ihnen aktuell keine Rolle spielt, hake ich es gerne ab.

Wenn Sie grundsätzlich offen dafür sind, passende Fachkräfte auch unabhängig von einer öffentlichen Ausschreibung kennenzulernen, können wir uns kurz austauschen.

Beste Grüße aus Münster
Berkant Devrim"""

    result = {
        "erstmail_betreff": "Frage zur Personalgewinnung",
        "erstmail": mail,
        "call_opener": opener,
        "discovery_fragen": discovery,
        "challenger_reframe": challenger,
        "follow_up_1": follow1,
        "follow_up_2": follow2,
        "personalization_evidence": evidence,
        "mail_variant": "Diamanten Radar V1",
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


def _valid_campaign_mail(mail: str, company: str, campaign: str = "", radar_mode: bool = False) -> bool:
    text = _clean_multiline(mail)
    words = len(re.findall(r"\b\w+\b", text))
    if radar_mode:
        if not 75 <= words <= 155:
            return False
    elif not 95 <= words <= 195:
        return False
    if company.lower() not in text.lower():
        return False
    if radar_mode:
        required = ("XING", "Personalbedarf", "direkt ansprechen")
    elif campaign == TESTPILOT_CAMPAIGN:
        required = TESTPILOT_REQUIRED_PHRASES
    elif campaign == MONDAY_WAVE_CAMPAIGN:
        required = MONDAY_REQUIRED_PHRASES
    else:
        required = REQUIRED_MAIL_PHRASES
    return all(phrase.lower() in text.lower() for phrase in required)


def create_sales_assets(
    *,
    company: str,
    jobs: list[dict],
    benefits: list[str],
    person: str,
    research: dict[str, Any] | None,
    api_key: str,
    model: str = "gpt-5-mini",
    campaign: str = "",
) -> dict[str, str]:
    research = research or {}
    titles = _job_titles(jobs)
    radar_mode = _clean_single(research.get("discovery_kind", "")) == "Firmenradar" and not titles
    if radar_mode:
        fallback = _radar_assets(company, jobs, benefits, person, research)
    elif campaign == TESTPILOT_CAMPAIGN:
        fallback = _testpilot_assets(company, jobs, benefits, person, research)
    elif campaign == MONDAY_WAVE_CAMPAIGN:
        fallback = _monday_assets(company, jobs, benefits, person, research)
    else:
        fallback = _fallback_assets(company, jobs, benefits, person, research)
    if OpenAI is None:
        fallback["ai_status"] = "Fallback: OpenAI Paket fehlt"
        return fallback
    if not api_key:
        fallback["ai_status"] = "Fallback: OpenAI Key fehlt"
        return fallback

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
    exact_subject = "Frage zur Personalgewinnung" if radar_mode else f"Exklusive Einladung | {company}"
    deterministic_variant = int(hashlib.sha1(company.encode("utf-8")).hexdigest()[:2], 16) % 2 + 1
    if radar_mode:
        campaign_rules = """
Spezielle Firmenradar Ansprache:
4. Es ist ausdrücklich NICHT belegt, dass aktuell eine Stelle offen ist. Unterstelle niemals eine Vakanz.
5. Verwende den belegten Firmen oder Karrierehinweis als Einstieg, ohne Lob und ohne zu behaupten, die Firma suche gerade Personal.
6. Erkläre knapp: Wenn Personalbedarf entsteht, kann XING Sichtbarkeit mit der gezielten Auswahl und direkten Ansprache wechselbereiter Fachkräfte verbinden.
7. Verwende die Begriffe XING, Personalbedarf und direkt ansprechen.
8. Frage offen, wie das Unternehmen neuen Personalbedarf aktuell löst oder ob ein kurzer Austausch grundsätzlich interessant ist.
9. Keine Preise, Rabatte, künstliche Verknappung oder unbelegte Recruiting Probleme nennen.
10. Die Erstmail umfasst 75 bis 135 Wörter.
"""
        mail_variant_name = f"Diamanten Radar V{deterministic_variant}"
    elif campaign == MONDAY_WAVE_CAMPAIGN:
        campaign_rules = """
Spezielle Kampagne Montagswelle 500:
4. Schreibe wie ein echter Account Executive, nicht wie ein Marketing Bot. Kurze klare Sätze. Keine Floskeln wie ich habe mir Ihre Website angesehen.
5. Wenn mindestens zwei Benefits belegt sind, darf sinngemäß der leicht freche Gedanke vorkommen: Sie bieten mehr als nur den klassischen Obstkorb. Sonst nicht erfinden.
6. Lade zur aktuellen XING Testkampagne ein. Statt direkt zwölf Monate festzulegen, können Stellenanzeige und TalentManager zwei Monate getestet werden.
7. Die Stellenanzeige bringt Sichtbarkeit und Bewerbungen. Der TalentManager ermöglicht die gezielte Auswahl und direkte Ansprache passender und wechselwilliger Fachkräfte.
8. Der Kern lautet sinngemäß: Nicht nur warten, wer sich bewirbt, sondern selbst entscheiden, wen man kennenlernen möchte.
9. Abschluss sehr kurz: Klingt das für Ihre aktuelle Suche spannend?
10. Keine Preise und keine Rabatte nennen.
11. Die Erstmail umfasst 90 bis 145 Wörter.
"""
        mail_variant_name = f"Montagswelle Testpilot V{deterministic_variant}"
    elif campaign == TESTPILOT_CAMPAIGN:
        campaign_rules = """
Spezielle Kampagne Testpilot Therapie:
4. Ein eigener Absatz lädt das Unternehmen als Testpilot zur aktuellen XING Kampagne ein.
5. Erkläre klar: Statt sich direkt für zwölf Monate festzulegen, können Stellenanzeige und TalentManager zwei Monate getestet werden.
6. Die Stellenanzeige bringt Sichtbarkeit und Bewerbungen. Der TalentManager ermöglicht die gezielte Auswahl und direkte Ansprache passender Fachkräfte.
7. Verwende sinngemäß: So warten Sie nicht nur darauf, wer sich bewirbt, sondern entscheiden selbst, wen Sie kennenlernen möchten.
8. Die Abschlussfrage lautet: Ist die Position noch offen?
9. Keine Preise und keine Rabatte nennen.
10. Die Erstmail umfasst 105 bis 160 Wörter.
"""
        mail_variant_name = f"Testpilot Therapie V{deterministic_variant}"
    else:
        campaign_rules = """
4. Danach steht als eigener Absatz exakt sinngemäß: Deshalb möchte ich Sie zu unserer aktuellen XING Kampagne einladen.
5. Erkläre, dass es nicht nur darum geht, Stellen zu veröffentlichen und auf Bewerbungen zu warten. Passende Fachkräfte sollen gezielt identifiziert und direkt angesprochen werden können.
6. Nutze ausdrücklich den Gedanken: So drehen Sie den Spieß um und entscheiden selbst, welche Fachkräfte Sie kennenlernen möchten.
7. Die Abschlussfrage lautet: Passt Ihnen ein kurzer Austausch kommende Woche eher vormittags oder nachmittags?
8. Signatur: Beste Grüße, Berkant Devrim, Senior Account Executive, XING.
9. Die Erstmail umfasst 120 bis 175 Wörter.
10. Keine Bindestriche, keine Gedankenstriche, keine Produktliste, keine Preise, keine unbelegten XING Kennzahlen, keine künstliche Verknappung.
"""
        mail_variant_name = f"Exklusive Einladung V{deterministic_variant}"

    prompt = f"""
Du schreibst für Berkant Devrim, Senior Account Executive bei XING, eine maßgeschneiderte Kaltakquise.
Nutze ausschließlich die gelieferten Fakten. Erfinde keine Benefits, Unternehmensmerkmale, Kennzahlen, Preise, Rabatte, Ergebnisse, Ansprechpartner oder Produktfunktionen.

Verbindlicher Stil der Erstmail:
1. Der Betreff lautet exakt: {exact_subject}
2. Beginne mit einer korrekten persönlichen Anrede. Wenn Frau oder Herr nicht sicher geliefert wurde, erfinde keine geschlechtliche Anrede.
3. Der erste Absatz nennt die aktuelle Personalsuche und genau ein belegtes, individuelles Merkmal des Unternehmens oder der Stellen. Kein Lob und keine Schleimerei.
{campaign_rules}
11. Ruhig, direkt, professionell und menschlich. Kein Werbeton.
12. Keine Bindestriche oder Gedankenstriche in Kundentexten.

Call und Gespräch:
Der Call Opener setzt einen klaren Frame und fragt nach der tatsächlichen Besetzbarkeit.
Die acht Discovery Fragen folgen dieser Logik: Priorität, Suchdauer, Bewerbungseingang, Qualität, bisherige Kanäle, geschäftliche Auswirkung, künftiger Bedarf, Entscheidung.
Der Challenger Reframe erklärt knapp die Lücke zwischen aktiv Suchenden und wechselbereiten Fachkräften.
Die Follow ups bleiben freundlich, konkret und enthalten keinen neuen unbelegten Fakt.

Fakten:
Unternehmen: {company}
Ansprechpartner: {person or 'nicht sicher bekannt'}
Rolle des Ansprechpartners: {_clean_single(research.get('role', '')) or 'nicht sicher bekannt'}
Offene Rollen: {', '.join(titles[:8]) or 'keine öffentliche Vakanz belegt'}
Anzahl gefundener Stellen: {len(titles)}
Discovery Art: {_clean_single(research.get('discovery_kind', '')) or 'Vakanz'}
Bedarfssignal: {_clean_single(research.get('need_signal', '')) or 'nicht eindeutig'}
Diamanten Hinweis: {_clean_single(research.get('diamond_reason', '')) or 'kein zusätzlicher Hinweis'}
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
mail_variant lautet exakt {mail_variant_name}.
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
        if not _valid_campaign_mail(result["erstmail"], company, campaign, radar_mode=radar_mode):
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
