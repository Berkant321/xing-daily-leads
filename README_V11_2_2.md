# XING Daily Leads V11.2.2

Hotfix für die langsame Anzeige neuer Firmen.

1. Schritt 1 macht beim Google Firmenradar nur noch Discovery.
2. Es werden in Schritt 1 keine Firmenwebsites mehr tief geprüft.
3. Dadurch wird ein Suchpaket deutlich früher beendet und die gefundenen Firmen werden früher ins Google Sheet geschrieben.
4. Website, Karrierebereich, Ansprechpartner, E Mail und Telefon bleiben vollständig Aufgabe von Schritt 2.
5. Während einer laufenden Suche weist die App ausdrücklich darauf hin, dass die sichtbare Liste bis zum ersten gespeicherten Paket noch aus dem vorherigen Lauf stammen kann.

Der bisherige Flaschenhals war probe_limit_per_query=8 im Firmenradar. Bei mehreren Regionen und Suchbegriffen konnte die App dutzende Websites mit langen HTTP Timeouts prüfen, bevor scan_jobs überhaupt zurückkehrte und app.py die erste Firma speichern konnte.
