# XING Daily Leads V11.2.1

Hotfix für den Startfehler `KeyError: 'pipeline'`.

## Ursache und Fix

Die bisherige App importierte ein lokales Modul mit dem sehr generischen Namen `pipeline` und importierte es zudem zweimal: einmal als Modul und einmal per `from pipeline import ...`.
In der Deployment Umgebung kann dieser Name mit Import Hooks beziehungsweise bereits geladenen Modulen kollidieren.

V11.2.1:

1. benennt `pipeline.py` in `xing_pipeline.py` um
2. passt sämtliche Imports in `app.py` auf `xing_pipeline` an
3. liefert das ZIP flach aus, also `app.py`, `xing_pipeline.py`, `scanner.py`, `research.py`, `sales_ai.py` und `requirements.txt` direkt im Root
4. enthält bewusst keinen `__pycache__` Ordner
5. behält die V11.2 Rate Limit und Queue Fixes bei

## Deployment

Im Repository müssen diese Dateien direkt nebeneinander liegen:

`app.py`
`xing_pipeline.py`
`scanner.py`
`research.py`
`sales_ai.py`
`requirements.txt`

Alte `pipeline.py` aus dem Repository löschen, damit kein veralteter Importpfad mehr übrig bleibt.
Danach die App neu starten beziehungsweise redeployen.
