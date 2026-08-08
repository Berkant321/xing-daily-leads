# XING Daily Leads

## Aktueller Code Stand

Stand: 6. August 2026

Version der Oberfläche: V10.2

Schema Version: 10.0.0

GitHub Repository: Berkant321/xing-daily-leads

Streamlit Hauptdatei: app.py

Branch: main

## Enthaltene Dateien

1. app.py

2. pipeline.py

3. scanner.py

4. research.py

5. sales_ai.py

6. requirements.txt

7. secrets_example.toml

Alle Python Dateien wurden am 6. August 2026 erfolgreich auf Syntax geprüft.

## Zweck

Das Tool ist eine schlanke Vertriebsintelligenz vor Salesforce. Es ist kein zweites CRM. Neue Unternehmen, Stellen, Ansprechpartner, Kontaktdaten, Rechercheergebnisse und Vertriebstexte werden vorbereitet. Echte Aktivitäten, Angebote und Kennzahlen bleiben ausschließlich in Salesforce.

## Ablauf

1. Stellen finden und Firmen sofort speichern

2. Website, Ansprechpartner, E Mail und Telefon recherchieren

3. Individuelle Vertriebstexte erzeugen

## Quellen

1. Bundesagentur für Arbeit

2. Adzuna

3. Google Jobs über SerpApi

4. Direkte Karriereseiten und ATS Boards

## Kampagnen

Enthalten sind unter anderem die breite Massenkampagne, Architektur und Planung, kleine Ingenieurbüros, Steuerkanzleien, kleine IT Unternehmen, Therapiepraxen, Recht und Kanzleien, ambulante Pflege, Arztpraxen, Handwerk und Technik, Industrie und Produktion, Logistik und Einkauf, Vertrieb und Marketing, Pharma und Forschung sowie Personal und Verwaltung.

Die breite Massenkampagne enthält über 50 Suchbegriffe. Kleine und mittelständische Direktkunden werden priorisiert. Personaldienstleister, öffentliche Arbeitgeber und klar erkennbare Großunternehmen werden gefiltert.

## Standardsuche

Standardzeitraum: 14 Tage

Standardregionen: Hamburg, Bremen, Hannover, Münster, Dortmund, Köln, Frankfurt am Main, Stuttgart, Nürnberg, München, Leipzig und Berlin

Bundesagentur ist standardmäßig aktiv. Adzuna und Google Jobs werden automatisch aktiviert, wenn die Zugangsdaten vorhanden sind. Karriereseiten werden bei Bedarf manuell aktiviert.

## Speicherung

Mit vollständiger Konfiguration speichert das Tool dauerhaft in Google Sheets.

Verwendete Tabellenblätter:

1. Leads

2. Stellen

3. CRM_Ausschluss

4. Scan_Log

Ohne Google Sheets läuft ein lokaler Testmodus mit CSV Dateien.

## Salesforce Abgleich

Ein Salesforce Export als CSV oder XLSX kann eingelesen werden. Bereits vorhandene Unternehmen werden ausgeschlossen. Die Ausschlusslogik arbeitet mit normalisierten Firmennamen. Die bekannte Ausschlussliste umfasste zuletzt rund 379.000 Datensätze aus Unternehmen und Bundesland.

## Qualität

Der Betreff wird automatisch als Exklusive Einladung | Unternehmensname erzeugt.

Eine persönliche oder Recruiting E Mail wird gegenüber einer allgemeinen Info Adresse bevorzugt.

Die Qualitätsprüfung reicht von 0 bis 100 Punkten.

Ab 85 Punkten und erfüllten Pflichtkriterien gilt ein Lead als versandbereit.

Ab 70 Punkten gilt ein Lead als kurz zu prüfen.

## Streamlit Secrets

Die benötigten Namen stehen in secrets_example.toml. Echte Zugangsdaten gehören ausschließlich in die Streamlit Secrets und niemals in GitHub.

## Start

Abhängigkeiten installieren:

```bash
pip install -r requirements.txt
```

App starten:

```bash
streamlit run app.py
```

## Bekannter letzter Betriebsstand

Am 25. Juli 2026 zeigte eine frühere Fassung 317 Stellen, 168 eindeutige Arbeitgeber, keine öffentlichen E Mail Adressen und keine Ansprechpartner. Außerdem waren alle 317 Stellen dem Suchbegriff Physiotherapeut zugeordnet. Die breite Kampagne lieferte damals keine breite Stellenmischung und nur vier neue Firmen.

Danach wurden Scanner, Pipeline, Recherche und Oberfläche weiterentwickelt. Die aktuelle V10.1 enthält Aufgabenpakete je Berufsgruppe und Region, getrennte Schritte für Suche, Recherche und Texte, sofortige Speicherung sowie den safe_int Fix.

Für die aktuelle V10.1 ist die Python Syntax geprüft. Ein vollständiger Live Test mit echten Zugangsdaten und allen Quellen ist nach dem letzten Umbau nicht dokumentiert. Deshalb ist der Code der aktuelle Arbeitsstand, aber noch nicht als vollständig stabil bestätigt.

## Wichtige Hinweise für GitHub und Streamlit

Die Dateien müssen exakt app.py, pipeline.py, scanner.py, research.py und sales_ai.py heißen. Namen mit Klammern oder Zusätzen werden von den internen Imports nicht gefunden.

Streamlit muss main als Branch und app.py als Hauptdatei verwenden.

Bei Änderungen nur die tatsächlich geänderten Dateien ersetzen, committen und anschließend normal neu laden. Wiederholte Neustarts lösen keine Import oder Syntaxfehler.


## Neu in V10.2: Testpilot Therapie 500

Die neue Kampagne Testpilot Therapie 500 ist als kontrollierte Vertriebswelle für Physio, Ergo und Logopädie Praxen aufgebaut.

Enthalten sind:

1. Deutschlandweite Regionsabdeckung mit 25 Suchzentren

2. Breitere Suchbegriffe und Berufsvarianten für Therapieprofile

3. Kampagnenziel von 500 neuen Firmen mit automatischer Pause beim Erreichen des Ziels

4. Eigene Testpilot Texte für Stellenanzeige plus TalentManager über zwei Monate statt direkter Festlegung auf zwölf Monate

5. Kampagnenkennzeichnung direkt am Lead sowie Filterung in der Arbeitsansicht

6. Preisfreie Erstansprache. Konditionen werden erst nach Interesse individuell geklärt

Empfohlener Ablauf: Zuerst 30 bis 50 Firmen vollständig durch Suche, Recherche und Textgenerierung laufen lassen. Qualität und Rückmeldungen prüfen. Danach die Welle schrittweise bis 500 ausbauen.

## V10.4 Strict Filter

Der Lead Filter wurde grundlegend verschärft.

1. CRM Abgleich nutzt sichere Alias Keys statt nur exakt identischer Firmennamen.
2. Ein Suchbegriff bestimmt nicht mehr das Unternehmenssegment.
3. Kleine Direktkunden benötigen jetzt ein echtes Kleinunternehmenssignal.
4. Alle kleinen Direktkunden speichert nur noch Leads mit Größenfit Klein.
5. Testpilot Therapie 500 akzeptiert nur Arbeitgeber mit erkennbarem Praxis beziehungsweise Therapieprofil.
6. Salesforce Schutzschalter blockiert Suchläufe, wenn die Ausschlussbasis offensichtlich fehlt.
