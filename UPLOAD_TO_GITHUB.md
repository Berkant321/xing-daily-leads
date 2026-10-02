# XING Lead Claim Engine V12 – Drop-in Upgrade

Dieses Paket ist für das bestehende Repository `Berkant321/xing-daily-leads` gedacht.

## Was du hochlädst

1. `app.py` ersetzt die vorhandene `app.py`.
2. `claim_engine.py` ist neu und kommt ins Repository-Root.
3. `requirements.txt` ersetzt die vorhandene Datei.

Die vorhandenen Dateien `scanner.py` und `research.py` bleiben bestehen und werden weiterverwendet.
`xing_pipeline.py` und `sales_ai.py` können zunächst im Repo bleiben, werden von V12 aber nicht mehr für den Kernprozess benötigt.

## Ziel der V12

Der Kern ist nicht mehr E-Mail-Textgenerierung, sondern:

- Job-Signale aus mehreren Quellen einsammeln
- denselben Arbeitgeber quellenübergreifend zusammenführen
- jede Quelle als Evidence behalten
- offizielle Firmenwebsite verifizieren
- Sitemap, Karrierebereich und ATS untersuchen
- strukturierte `JobPosting`-Daten auf Firmen-/ATS-Seiten erkennen
- Recruiting-Bedarf (`need_score`) bewerten
- Firmenidentität (`company_confidence`) bewerten
- Salesforce-Bestand über Name, Domain und Telefon ausschließen
- einen eigenständigen `claim_score` und `claim_status` erzeugen

Ein guter Lead benötigt **keine E-Mail-Adresse** und **keinen fertigen Mailtext**.

## Neue Google-Sheets-Struktur

V12 nutzt weiter die vorhandenen Tabs:

- `Leads`
- `Stellen`
- `CRM_Ausschluss`
- `Scan_Log`

und legt zusätzlich automatisch an:

- `Evidence`

Bestehende Leads und Stellen werden beim Start auf das neue Schema migriert. Die alten Mail-/Feedback-Spalten bleiben erhalten, damit vorhandene Daten nicht verloren gehen.

## Bedienung

### 1. Salesforce

Unter `Salesforce` zuerst einen aktuellen Account-Export hochladen. Der Abgleich nutzt soweit vorhanden:

- Firmenname/Aliase
- Domain/Website
- Telefonnummer

### 2. Discovery

Unter `Discovery` Quellen auswählen. Unterstützt werden die Quellen aus dem bestehenden `scanner.py`:

- Bundesagentur
- Adzuna
- Google Jobs
- Google Firmenradar
- direkte Karriere-/ATS-URLs

Zusätzlich können CSV-/XLSX-Exporte von **beliebigen weiteren Jobportalen** importiert werden. Benötigt werden mindestens eine Firmen- und eine Positionsspalte.

### 3. Deep Research

Unter `Deep Research` priorisierte Arbeitgeber recherchieren. Dabei werden u. a. geprüft:

- offizielle Domain
- Unternehmensidentität
- Sitemap / Sitemap-Index
- Kontakt / Impressum / Teamseiten
- Karrierebereich
- ATS-Erkennung (Personio, Greenhouse, Lever, SmartRecruiters, Workable, Teamtailor, Softgarden, Onlyfy, JOIN)
- strukturierte `JobPosting`-Daten
- Zahl verifizierter offizieller Jobs

### 4. Claim Queue

Unter `Claim Queue` stehen die priorisierten Arbeitgeber mit:

- `CLAIMABLE`
- `RESEARCH`
- `REVIEW`
- `EXCLUDE`

Wichtige Scores:

- `company_confidence`: Ist die richtige Firma sicher identifiziert?
- `need_score`: Wie stark ist der aktuelle Recruiting-Bedarf belegt?
- `claim_score`: Wie attraktiv ist der Account als neuer Lead?

## Secrets

Die bisherigen Streamlit-Secrets bleiben kompatibel:

```toml
spreadsheet_id = "..."
serpapi_key = "..."
adzuna_app_id = "..."
adzuna_api_key = "..."

[gcp_service_account]
# bestehender Service Account
```

`openai_api_key` darf bestehen bleiben, ist für V12 Claiming aber nicht erforderlich.

## Vor dem ersten großen Lauf

Empfohlen:

1. Salesforce-Export neu einlesen.
2. Erst 5–10 Suchbegriffe laufen lassen.
3. 10–20 Firmen Deep Research durchführen.
4. Claim Queue prüfen.
5. Danach Suchumfang erhöhen.

## Technischer Hinweis

V12 ist bewusst als Drop-in-Version gebaut und verwendet weiterhin Google Sheets. Bei deutlich größeren Datenmengen kann später PostgreSQL/Supabase hinter dieselbe Claim-Logik gesetzt werden.
