# XING Daily Leads V11.2

Diese Fassung räumt die aktuelle 429 Problematik auf und verhindert, dass offene Leads durch externe Limits dauerhaft hängen bleiben.

## Behobene Punkte

1. SerpApi 429 wird nicht mehr automatisch mehrfach wiederholt.
2. Der Firmenradar und Google Jobs stoppen ihre SerpApi Quelle beim ersten 429 für den laufenden Scan. Andere Quellen laufen weiter.
3. Die Firmenrecherche nutzt zuerst direkte Quellen und DuckDuckGo. SerpApi ist nur noch zweite Stufe.
4. Nach einem SerpApi 429 pausiert die Recherche SerpApi für 15 Minuten, statt für jede weitere Firma erneut Requests zu verbrennen.
5. Alte Recherchezeilen mit 429 oder Quota Fehler werden wieder in die Recherche Queue aufgenommen, auch wenn bereits drei Versuche gespeichert sind.
6. Ein fehlender Ansprechpartner zählt jetzt als offene Recherche. Eine Website plus allgemeine E Mail gilt nicht mehr automatisch als vollständig.
7. Temporäre 429 Fehler verbrauchen keinen zusätzlichen Rechercheversuch.
8. OpenAI 429 wird nicht mehr erneut versucht. Nach dem ersten Limit wird OpenAI zehn Minuten pausiert.
9. Der faktenbasierte Fallback Text zählt als fertiger Text. Ein fehlendes OpenAI Kontingent blockiert die Pipeline damit nicht mehr.
10. Alte Fallback Texte mit vorhandenem Mailtext und Personalisierungsbeleg zählen ebenfalls als erledigt und werden nicht in jeder Runde neu geschickt.
11. Wenn neue Recherche Fakten einen bestehenden Text veralten lassen, wird der Lead automatisch wieder für Schritt 3 eingeplant.
12. Firmenradar Leads erhalten wieder den korrekten Betreff `Frage zur Personalgewinnung`. Der bisherige globale Betreff Override ist entfernt.
13. Kundentexte entfernen jetzt auch normale ASCII Bindestriche vollständig.
14. Standardgröße der Recherchepakete wurde von 20 auf 10 reduziert.

## Deployment

Die Dateien im Repository müssen exakt so heißen:

1. `app.py`
2. `pipeline.py`
3. `scanner.py`
4. `research.py`
5. `sales_ai.py`
6. `requirements.txt`

Danach die Streamlit App neu starten. Bestehende Google Sheets Daten bleiben erhalten.

## Was nach dem Neustart passiert

`Texte offen` sollte deutlich sinken, weil vorhandene brauchbare Fallback Texte nicht mehr als dauerhaft offen gelten.

`Recherche offen` kann zunächst steigen. Das ist beabsichtigt, weil alte 429 Fälle und Leads ohne konkreten Ansprechpartner wieder korrekt in die Recherche Queue kommen.

Für die erste Runde nach dem Update Schritt 2 mit 10 Firmen starten. Wenn die Ergebnisse sauber laufen, weitere Pakete abarbeiten.
