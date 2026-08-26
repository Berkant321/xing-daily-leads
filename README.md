# XING Daily Leads V11.3

## Ziel

Diese Version ergänzt eine eigene Kampagne namens `Logopädie Radar Deutschland`.

Der Modus ist für maximale Firmendiscovery gebaut. Er verlangt in Schritt 1 keine offene Stelle, keine E Mail, keinen Ansprechpartner und keinen fertigen Verkaufstext.

## Was geändert wurde

1. Eigener Logopädie Radar

Die Kampagne verwendet standardmäßig ausschließlich Google Firmenradar.
Bundesagentur, Google Jobs und Adzuna sind in diesem Modus standardmäßig deaktiviert.

2. Deutschland Raster

Statt 25 sehr großer Regionen enthält der neue Modus 213 lokale Startpunkte mit jeweils 30 km Radius.

3. Breitere Suchlogik

Der Scanner kennt zwölf Suchvarianten rund um Logopädie und Sprachtherapie.
Je Ort werden vier Varianten genutzt.
Zwei Kernbegriffe sind immer aktiv.
Zwei weitere Varianten rotieren abhängig vom Ort.
Dadurch wird die Abdeckung breiter, ohne in jedem Ort zwölf nahezu identische SerpApi Requests auszuführen.

4. Rohsammlung vor Recherche

Schritt 1 speichert Firmenfunde sofort.
Website, Karrierebereich, Ansprechpartner, E Mail und tiefere Prüfung bleiben Aufgabe von Schritt 2.

5. Bessere Dublettenlogik

Google Maps Place Referenzen werden als Discovery Identität genutzt.
Gleichnamige Praxen in unterschiedlichen Städten werden dadurch nicht mehr automatisch als dieselbe Firma behandelt.

6. Generische Praxisnamen

Namen wie `Praxis für Logopädie` werden beim Salesforce Abgleich nicht mehr deutschlandweit nur aufgrund des Namens ausgeschlossen.
Wenn Website Domain oder Telefonnummer vorhanden sind, werden diese weiterhin für den Abgleich genutzt.

7. Zielgröße

Die neue Rohsammlung hat ein technisches Kampagnenziel von 3000 eindeutigen Firmenfunden.
Das ist ein Stop Ziel und keine Garantie für 3000 tatsächlich verfügbare Praxen.
Die reale Zahl hängt unter anderem von Google Maps, SerpApi Kontingent, Dubletten und Salesforce Ausschlüssen ab.

## Empfohlene Einstellungen

Kampagne: `Logopädie Radar Deutschland`

Quelle: nur `Google Firmenradar`

Seiten je Suche: `1`

Suchaufgaben pro Klick: `10`

Regionen je Suchaufgabe: `3`

Damit werden pro Klick ungefähr 30 lokale Startpunkte verarbeitet.
Bei vier Maps Suchvarianten je Ort entstehen ungefähr 120 Maps Requests pro vollständigem Klick, sofern jede Suche ausgeführt werden kann.

## Dateien

`app.py`

`scanner.py`

`xing_pipeline.py`

`research.py`

`sales_ai.py`

`requirements.txt`

Die letzten drei Dateien entsprechen der hochgeladenen Version und wurden für ein vollständiges Paket mit aufgenommen.

## Technischer Check

Alle Python Dateien wurden mit `py_compile` auf Syntaxfehler geprüft.
Zusätzlich wurden die neue Suchvariantenlogik, die Maps Identität und die getrennten Lead IDs für gleichnamige Praxen geprüft.
