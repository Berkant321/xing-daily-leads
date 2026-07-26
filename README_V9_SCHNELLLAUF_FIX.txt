XING Daily Leads V9 Schnelllauf Fix

Ersetze vollständig:
1. app.py
2. pipeline.py
3. scanner.py

research.py kann unverändert bleiben.

Wichtigste Korrekturen:
• Salesforce Abgleich arbeitet jetzt in konstanter Zeit statt jeden Lead mit rund 200.000 Firmen zu vergleichen.
• Der beschädigte Scan Log wird beim ersten Start automatisch rekonstruiert und sauber neu geschrieben.
• Jede Suchaufgabe schreibt eine sichtbare Fortschrittsmeldung.
• Chancenmix erkennt Architektur, Ingenieurwesen, Steuer und IT als eigene Zielsegmente.
• Unpassende breite Treffer wie Software Architect bei der Suche Architekt werden entfernt.
• Große Arbeitgeber, öffentliche Arbeitgeber und Vermittler werden konsequenter ausgeschlossen.
• Mitarbeiterzahlen mit Tausendertrennzeichen wie 22.000 werden korrekt erkannt.

Nach Commit und Push Streamlit rebooten. Danach Schritt 1 mit 4 Suchaufgaben und 3 Regionen starten.
