# XING Daily Leads V11

## Ziel

V11 ergänzt die bisherige stellenbasierte Suche um einen separaten Firmenradar für kleine lokale Direktkunden.

Der Radar darf niemals eine offene Stelle behaupten, wenn keine echte Vakanz gefunden wurde.

## Neue Kampagne

`Diamanten Radar | kleine Direktkunden`

Diese Kampagne nutzt standardmäßig den neuen Google Firmenradar.

Der Firmenradar sucht über Google Maps nach passenden Betriebstypen in den eingetragenen Regionen. Die angegebenen Umkreise werden als räumlicher Suchrahmen an SerpApi übergeben.

Für gefundene Unternehmen werden vorhandene Websites sofort leicht geprüft. Eigene Karrierebereiche, externe ATS Seiten und strukturierte JobPosting Daten werden erkannt.

Wenn eine echte Vakanz gefunden wird, wird der Fund als `Karrieresignal` behandelt.

Wenn keine Vakanz belegt ist, bleibt der Fund `Firmenradar` und erhält `anzahl_stellen = 0`.

## Vertiefte Recherche

Schritt 2 sucht für Radar Firmen weiterhin die offizielle Website, Ansprechpartner, E Mail und Telefon.

Dabei werden auch interne Karrierebereiche und externe ATS Links verfolgt. Erkannte Karrierehinweise, Anzahl gefundener JobPosting Einträge und Jobtitel werden in die Recherche übernommen.

## Diamanten Score

Der Score priorisiert kleine Direktkunden anhand belastbarer Signale wie klarem Arbeitgebersegment, eigener Website, direkter Telefonnummer, Karrierebereich und Recruiting Hinweis.

Wenige Google Bewertungen werden nur als schwaches Signal für einen lokalen Footprint verwendet. Der Score behauptet ausdrücklich nicht, dass ein Unternehmen noch nie durch Vertrieb kontaktiert wurde.

## Fehlerdiagnose

Wenn alle Suchaufgaben scheitern, zeigt die Streamlit Oberfläche jetzt den echten Python Trace direkt unter der Fehlermeldung an.

Der Scan Log Fehler wird separat abgefangen, damit ein zusätzlicher Logging Fehler die eigentliche Ursache nicht verdeckt.

## BeautifulSoup Warnung

URLs werden nicht mehr pauschal als HTML an BeautifulSoup übergeben. Dadurch verschwindet die wiederholte MarkupResemblesLocatorWarning aus `research.py`.

## Bestehende Suche

Bundesagentur, Google Jobs, Adzuna und manuelle Karriereseiten bleiben erhalten.

Die klassische Stellen Tabelle enthält weiterhin nur echte Vakanzen. Reine Firmenradar Funde werden nicht als Stelle gezählt.

## Deployment

Die Dateien im Repository müssen exakt so heißen:

1. `app.py`
2. `pipeline.py`
3. `scanner.py`
4. `research.py`
5. `sales_ai.py`
6. `requirements.txt`

`secrets_example.toml` enthält keine echten Zugangsdaten.

Für den Google Firmenradar wird der bestehende `serpapi_key` verwendet. Es ist keine neue Python Abhängigkeit erforderlich.

## Empfohlener erster Lauf

Kampagne `Diamanten Radar | kleine Direktkunden` auswählen.

Aktuellen vollständigen Salesforce Export laden.

Zunächst nur `Google Firmenradar` aktivieren.

Mit 6 Suchaufgaben pro Klick, 3 Regionen je Suchaufgabe und einer Seite starten.

Danach Schritt 2 für die neuen Radar Firmen laufen lassen und zuerst die Kandidaten mit hohem Diamanten Score prüfen.
