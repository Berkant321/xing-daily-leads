
# XING Daily Leads

Ein schlankes Vorbereitungs-Tool vor Salesforce:

- frische Stellen aus der Jobsuche der Bundesagentur für Arbeit
- kleinere Direktkunden priorisieren
- Vermittler und offensichtliche Großunternehmen ausblenden
- mehrere Stellen je Firma bündeln
- Ansprechpartner, E-Mail, Telefon, Website, Benefits recherchieren
- HOT/WARM/COLD-Score
- Call-Opener, Discovery-Fragen, Erstmail und Follow-ups
- Salesforce-CSV als Ausschlussliste
- Wiedervorlagen ohne doppelte KPI-Dokumentation

## Sofort testen

1. Lade alle Projektdateien in ein neues GitHub-Repository.
2. Öffne Streamlit Community Cloud.
3. Klicke auf **Create app**.
4. Wähle das Repository.
5. Main file path: `app.py`
6. Deploy.

Ohne weitere Einrichtung startet die App im lokalen Testmodus. Dieser reicht zum Ausprobieren, ist in der Cloud aber nicht dauerhaft zuverlässig.

## Dauerhaft mit Google Sheets speichern

### 1. Google Cloud Service Account erstellen

- Google Cloud Console öffnen
- neues Projekt anlegen
- Google Sheets API und Google Drive API aktivieren
- Service Account erstellen
- JSON-Schlüssel herunterladen

### 2. Google Sheet erstellen

Erstelle eine Tabelle, z. B.:

`XING Daily Leads`

Teile die Tabelle mit der E-Mail-Adresse des Service Accounts als **Bearbeiter**.

### 3. Streamlit Secrets eintragen

In Streamlit:

**App → Settings → Secrets**

Inhalt:

```toml
spreadsheet_name = "XING Daily Leads"

[gcp_service_account]
type = "service_account"
project_id = "DEIN_PROJECT_ID"
private_key_id = "DEIN_PRIVATE_KEY_ID"
private_key = """-----BEGIN PRIVATE KEY-----
DEIN_PRIVATE_KEY
-----END PRIVATE KEY-----
"""
client_email = "DEIN_SERVICE_ACCOUNT@DEIN_PROJEKT.iam.gserviceaccount.com"
client_id = "DEINE_CLIENT_ID"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "DEINE_CERT_URL"
universe_domain = "googleapis.com"
```

Danach App neu starten.

## täglicher Ablauf

- abends oder morgens **Jetzt frische Leads laden**
- im Bereich **Daily Leads** priorisierte Firmen abarbeiten
- gute Leads in Salesforce übernehmen
- nur Wiedervorlage und Arbeitsstatus im Tool pflegen
- echte Calls und KPIs weiterhin ausschließlich in Salesforce dokumentieren

## Hinweise

- Ansprechpartner- und E-Mail-Erkennung ist heuristisch: vor Versand kurz prüfen.
- Kein automatischer Mailversand, damit du die Kontrolle behältst.
- Unternehmensgröße wird zunächst über Ausschlussregeln angenähert, nicht garantiert.
