# Wahltool – Sammel-PDF

Inoffizielles Hilfsprogramm für Kurswahl-Abgaben im Schulportal Hessen.
Kein Angebot und keine Freigabe des Schulportals. Nur im Rahmen der eigenen Berechtigungen verwenden.

## Voraussetzungen
Windows, installiertes Microsoft Edge und berechtigter Portalzugang.
Für die fertige EXE ist keine separate Python-Installation nötig.

## Bedienung
1. Wahltool starten. Optional „Schule / Sitzung auf diesem Rechner merken“ aktivieren.
2. „Portal öffnen“ wählen und bei Bedarf manuell anmelden und Schule wählen.
3. Selbst zur Teilnehmenden-/Abgabenübersicht der konkreten Wahl navigieren.
4. Tabellenfilter leeren und im Portal alle Tabellenzeilen anzeigen.
5. „Teilnehmende einlesen“, Personen auswählen.
6. Optional die Ein-Seiten-Optimierung aktivieren.
7. „Sammel-PDF erstellen …“ und Speicherort wählen.
8. Ergebnis kontrollieren und anschließend selbst drucken. Kein automatischer Druck.

Reihenfolge: Klasse/Kommentar, Nachname, Vorname, mit natürlicher Zahlensortierung.
Bei Abruffehlern wird die Sammlung abgebrochen. Bestehende Zieldateien bleiben bei solchen Fehlern erhalten.
Beim Schließen des Portalfensters werden die eingelesenen Einträge verworfen. Das Portal kann erneut geöffnet werden.
Während des Abrufs nicht navigieren. Beim Beenden des Wahltools wird ein laufender Vorgang zunächst beendet und dann der Browser geschlossen.

## Lokales Browserprofil – Datenschutz
Standardmäßig deaktiviert. Aktivierung verwendet ein eigenes Edge-Profil, nicht das normale persönliche Edge-Profil.
Speicherort unter Windows: %LOCALAPPDATA%\WahltoolBatchDruck\edge-profile
Die Einstellung liegt daneben in settings.json. Keine Zugangsdaten werden im Python-Programm hinterlegt.
Cookies und lokale Webspeicherdaten können Zugang zum Portal ermöglichen. Nur auf dem eigenen, geschützten Windows-Konto verwenden.
Das Tool implementiert keinen eigenen Passwortspeicher. Wiederanmeldung und Schulwahl hängen vom Portal ab; Sitzungen können ablaufen.
Abwählen der Option löscht ein zuvor angelegtes Profil NICHT, sondern öffnet beim nächsten Start eine vorübergehende Sitzung.
Zum vollständigen Entfernen: erst Browser schließen, dann „Gespeicherte Browserdaten löschen“ anklicken und bestätigen.
Nicht mehrere Instanzen gleichzeitig mit demselben gespeicherten Profil öffnen.
Profil, Cookies, Schülerdaten, Portal-HTMLs und Schüler-PDFs niemals auf GitHub hochladen.

## Optionale Ein-Seiten-Optimierung
Standardmäßig aus. Gilt nur für geeignete, textbasierte, zweiseitige A4-Hochformat-PDFs ohne Bilder, Drehungen oder Anmerkungen/Formularfelder.
Alle erkannten Text- und Zeichnungselemente werden mit Sicherheitsrand berücksichtigt. Verwendete Bereiche werden untereinander auf A4 angeordnet.
Die Skalierung wird pro Dokument berechnet, maximal 95 %, mindestens 85 %. Kein pauschales Löschen der zweiten Seite.
Eine zusätzliche Textkontrolle vergleicht den vollständigen auslesbaren Text vor und nach der Umwandlung.
Einseitige, längere und nicht sicher geeignete PDFs bleiben unverändert und vollständig.
Nach der Erstellung zeigt ein Ergebnisfenster pro Person den Status. Es wird keine zusätzliche personenbezogene Protokolldatei gespeichert.
Der Textvergleich ersetzt keine Sicht- und Druckkontrolle. Diese Funktion ist anhand zweier Testaccount-PDFs erprobt, nicht an allen Portalvarianten.

## Lokal mit Python starten
In der Windows-Eingabeaufforderung im Projektordner:

    python -m pip install -r requirements.txt
    python wahltool_batch_druck.py

Tests:

    python -m unittest discover -s tests -v

## Windows-EXE bauen
Der Workflow „Build Windows executable“ läuft bei Änderungen auf main und manuell über Actions.
Er installiert Abhängigkeiten, prüft Syntax und Tests und baut danach die EXE mit PyInstaller.
Das Artefakt heißt WahltoolBatchDruck-windows, das Programm WahltoolBatchDruck.exe.
Alternativ lokal build_windows.ps1 ausführen (PowerShell-Ausführungsrichtlinien beachten).
Das Artefakt enthält keine lokalen Browserdaten. Die neue EXE vor Veröffentlichung auf Windows testen.
Ein erfolgreiches Actions-Build aktualisiert KEIN bestehendes Release. Die neue getestete EXE anschließend separat als Release veröffentlichen.
Browser- und Schulrechner-Richtlinien gelten weiterhin. Keine Sicherheitsmechanismen pauschal deaktivieren.
