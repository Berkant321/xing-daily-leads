# XING Daily Leads V3

Diese Version behebt die konkreten Probleme der bisherigen App:

* Der letzte Scan zeigt neue Unternehmen separat und verkauft alte Leads nicht erneut als neu.
* Suchbegriffe rotieren pro Lauf, damit nicht ständig exakt dieselben Firmen erscheinen.
* Bereits vollständige Recherchen werden zwischengespeichert und nicht bei jedem Scan überschrieben.
* Fehlende alte Leads können über „Bestehende Leads nachrecherchieren“ erneut angereichert werden.
* Die Firmenwebsite wird über mehrere Suchabfragen ermittelt und gegen Firmenname und Ort geprüft.
* Kontakt, Impressum, Karriere, Team und Ansprechpartner werden automatisch durchsucht.
* Mailto Links, Tel Links, sichtbare Kontaktdaten und typische HR Rollen werden ausgewertet.
* OpenAI Fehler werden sichtbar im Feld `ai_status` gespeichert. Es gibt keinen stillen Fehler mehr.
* Manuell geänderte Texte können gesperrt werden und bleiben bei künftigen Scans erhalten.
* Bestehende Kontaktdaten werden nicht mehr durch leere neue Ergebnisse überschrieben.

## Installation

Alle Dateien aus diesem Ordner in das GitHub Repository kopieren:

* `app.py`
* `scanner.py`
* `research.py`
* `sales_ai.py`
* `requirements.txt`

Danach committen und die Streamlit App neu starten.

## Streamlit Secrets

Die Schlüssel werden klein geschrieben. Vorlage: `secrets.example.toml`.

Wichtig:

* `openai_api_key` erzeugt die individuellen Texte. Er findet keine Telefonnummern.
* `serpapi_key` verbessert die Suche nach der offiziellen Website erheblich.
* Die Bundesagentur kann öffentliche Kontaktdaten aus Stellenangeboten liefern.
* Nicht jedes Unternehmen veröffentlicht eine direkte E Mail oder Telefonnummer. Die App erfindet keine Kontaktdaten.

## Erster Test

1. Im Systemcheck müssen OpenAI Paket und OpenAI Key als bereit erscheinen.
2. Bundesagentur aktivieren. Adzuna aktivieren, wenn die Zugangsdaten hinterlegt sind.
3. Zunächst 12 Suchbegriffe, 14 Tage, eine Seite und 20 bis 30 Website Recherchen nutzen.
4. Nach dem Scan die technischen Details öffnen.
5. Danach „Bestehende Leads nachrecherchieren“ starten, um alte unvollständige Leads zu ergänzen.

## Warum trotzdem manchmal keine Kontaktdaten erscheinen

Einige Websites blockieren automatisierte Abrufe, laden Kontaktdaten ausschließlich per JavaScript oder veröffentlichen keine direkten Daten. In diesen Fällen bleibt das Feld bewusst leer. Eine falsche Telefonnummer oder erfundene E Mail wäre für den Vertrieb schlechter als ein transparent leeres Feld.

