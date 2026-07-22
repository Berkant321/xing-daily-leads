XING Sales Cockpit V4

Alle Dateien in GitHub ersetzen/hochladen:
- app.py
- scanner.py
- requirements.txt

Danach:
1. Streamlit neu starten.
2. Unter „Salesforce-Abgleich“ einen Account-Export als CSV oder XLSX hochladen.
3. Abgleich speichern.
4. Einen neuen Scan starten.

Neu:
- Adzuna-Links werden nicht mehr als Firmenwebsite übernommen.
- Offizielle Firmenwebsite wird automatisch gesucht.
- Kontakt-, Impressums-, Karriere- und Teamseiten werden gecrawlt.
- E-Mail, Telefon, Ansprechpartner und Rolle werden gesucht.
- Salesforce-Bestandsfirmen werden aus Daily Leads entfernt.
- Vollständige Tabelle inklusive Website/Kontaktdaten/CRM-Status.
- CSV-Export der gefilterten Tabelle.

Hinweis:
Die Website-Suche nutzt bevorzugt einen vorhandenen serpapi_key.
Ohne SerpApi wird DuckDuckGo als kostenloser Fallback genutzt. Suchmaschinen
können Anfragen zeitweise begrenzen; deshalb ist die Recherchezahl pro Scan
weiterhin einstellbar.
