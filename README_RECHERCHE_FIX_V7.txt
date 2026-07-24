XING Daily Leads Recherche Fix V7

Ersetze im GitHub Repository vollständig:

1. app.py
2. pipeline.py
3. research.py

Unverändert lassen:

scanner.py
sales_ai.py
requirements.txt

Danach Commit und Push ausführen und die Streamlit App neu starten.

Was geändert wurde:

Website wird gespeichert, auch wenn die Seite automatisierte Abrufe blockiert.
Kontaktdaten aus Stellenbeschreibungen werden vor der Webrecherche übernommen.
Öffentliche Suchtreffer von XING und LinkedIn werden als Hinweis für Ansprechpartner und Rollen ausgewertet, aber nicht direkt gecrawlt.
SerpApi sucht zusätzlich nach Personal, Recruiting, HR, Geschäftsführung und Ansprechpartnern.
Wenn Suchmaschinen keine Website liefern, werden wenige plausible Domains getestet und erst nach Namensprüfung übernommen.
Recherchepaket wurde von 5 auf 20 Firmen erhöht und kann bis 100 eingestellt werden.
Veraltete Streamlit Warnungen zu use_container_width wurden entfernt.

Wichtig:

Es werden keine E Mail Adressen frei erfunden. Persönliche Adressen werden nur übernommen, wenn sie in öffentlich zugänglichen Quellen oder Stellenanzeigen gefunden wurden.
