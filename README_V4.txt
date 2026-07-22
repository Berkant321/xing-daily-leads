# XING Daily Leads V3.1

Diese Version korrigiert drei konkrete Fehler aus V3:

1. Bestehende Alt Leads werden nicht mehr als neue Unternehmen des aktuellen Scans angezeigt.
2. Die Website Recherche bewertet SerpApi Treffer anhand von URL, Suchtreffer Titel, Snippet und Seiteninhalt. Kleine Praxen und Kanzleien werden nicht mehr durch eine zu strenge Schwelle verworfen.
3. Recherche und OpenAI Fehler werden pro Unternehmen in den technischen Details angezeigt. Fallback Texte enthalten immer den Firmennamen und sind deshalb nicht mehr identisch.

## Dateien ersetzen

Im GitHub Repository vollständig ersetzen:

- `app.py`
- `scanner.py`
- `research.py`
- `sales_ai.py`
- `requirements.txt`

Danach committen und die Streamlit App neu starten.

## Secrets

```toml
openai_api_key = "DEIN_OPENAI_KEY"
openai_model = "gpt-5-mini"
serpapi_key = "DEIN_SERPAPI_KEY"
adzuna_app_id = "DEINE_ADZUNA_APP_ID"
adzuna_api_key = "DEIN_ADZUNA_API_KEY"
```

## Erster Test

- Ansicht: `Nur neue Unternehmen`
- Zeitraum: 14 Tage
- Seiten je Suche: 1
- Websites recherchieren: 10
- Suchbegriffe je Lauf: 8
- Adzuna, Bundesagentur und Google Jobs aktivieren

Nach dem Scan die technischen Details öffnen. Dort stehen jetzt konkrete Fehler pro Unternehmen, statt nur Summen.
