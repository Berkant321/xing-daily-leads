# XING Daily Leads V6

Diese Version verbindet breite Leadgewinnung, belastbare Recherche, den verbindlichen Mailstil und ein messbares Feedbacksystem.

## Was neu ist

1. Die Standardkampagne heißt Breite Massenkampagne und enthält mehr als 100 gemischte Suchbegriffe aus Therapie, Pflege, Steuer, Recht, Technik, Industrie, Bau, IT, Vertrieb, Marketing, Logistik, Pharma, Personal und Verwaltung.

2. Pro Suchlauf werden standardmäßig acht Suchbegriffe verarbeitet. Die Regionen decken Deutschland deutlich breiter ab.

3. Mittelständische Direktkunden werden nicht mehr allein wegen mehrerer Stellen oder Standorte verworfen. Personaldienstleister, öffentliche Arbeitgeber und eindeutig bekannte Großunternehmen bleiben ausgeschlossen.

4. Die Website Recherche bevorzugt persönliche oder Recruiting E Mail Adressen. Eine allgemeine Info Adresse wird deutlich schlechter bewertet.

5. Stellenbeschreibungen und Website Inhalte werden im Lead gespeichert. Dadurch kann OpenAI echte Unternehmensmerkmale und Benefits für die Personalisierung verwenden.

6. Der Betreff lautet immer exakt Exklusive Einladung | Unternehmensname.

7. Die Erstmail folgt verbindlich dem gewünschten Aufbau mit aktueller Personalsuche, belegtem Unternehmensmerkmal, Einladung zur XING Kampagne, aktiver Ansprache, dem Gedanken den Spieß umzudrehen und der Terminfrage vormittags oder nachmittags.

8. Jeder Lead erhält eine Qualitätsbewertung von 0 bis 100.

Versandbereit bedeutet, dass eine konkrete Vakanz, ein belastbarer Personalisierungsbeleg, eine direkte oder Recruiting E Mail Adresse und die vollständige Kampagnenstruktur vorhanden sind.

Kurz prüfen bedeutet, dass die Mail grundsätzlich nutzbar ist, aber mindestens ein wichtiges Qualitätsmerkmal fehlt.

Nicht freigeben bedeutet, dass die Mail noch nicht versendet werden sollte.

9. Im neuen Bereich Kampagnen Feedback werden Versand, Antworten, positive Antworten, Termine, Antwortquote und Terminquote nach Segment und Mailvariante ausgewertet.

## Dateien im GitHub Repository ersetzen

1. app.py

2. pipeline.py

3. scanner.py

4. research.py

5. sales_ai.py

6. requirements.txt

Danach alle Dateien committen und die Streamlit App neu starten.

## Wichtiger Hinweis vor dem ersten Start

Erstelle einmalig eine Kopie des verbundenen Google Sheets. Beim ersten Start erweitert die App das Leads Tabellenblatt um die neuen Qualitäts und Feedbackspalten und schreibt die neue Spaltenstruktur zurück.

## Secrets

```toml
openai_api_key = "DEIN_OPENAI_KEY"
openai_model = "gpt-5-mini"
serpapi_key = "DEIN_SERPAPI_KEY"
adzuna_app_id = "DEINE_ADZUNA_APP_ID"
adzuna_api_key = "DEIN_ADZUNA_API_KEY"
```

## Empfohlener erster Test

1. Kampagne Breite Massenkampagne auswählen.

2. Zeitraum auf 14 Tage setzen.

3. Seiten je Suche auf 1 setzen.

4. Suchbegriffe pro Klick auf 8 setzen.

5. Adzuna, Bundesagentur und Google Jobs aktivieren, sofern die Zugangsdaten vorhanden sind.

6. Schritt 1 starten.

7. Danach fünf bis zehn Firmen in Schritt 2 recherchieren.

8. Anschließend die Texte in Schritt 3 erzeugen.

9. Zuerst nur Leads mit dem Status Versandbereit verwenden.

10. Versand und Antworten konsequent im Feedback Tab dokumentieren.

## Realistische Garantie

Die App kann keine Antwort eines Unternehmens garantieren. Sie garantiert technisch aber, dass kein Lead als Versandbereit markiert wird, solange zentrale Pflichtmerkmale fehlen. Die tatsächliche Antwort und Terminquote wird anschließend anhand der echten Kampagnendaten gemessen.
