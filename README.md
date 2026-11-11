# Wahltool Batch-Druck

Windows-Desktop-Tool für den Batch-Druck ausgewählter Unterseiten der Oberstufenwahl im Schulportal Hessen.

## Verwendung

1. `WahltoolBatchDruck.exe` starten.
2. **Portal öffnen** wählen und sich im geöffneten Microsoft Edge anmelden.
3. **Seiten suchen** wählen. Die App öffnet danach erneut die Oberstufenwahl-Hauptseite und liest dort die Linktitel der verfügbaren Unterseiten aus.
4. Eine oder mehrere Unterseiten auswählen und **Auswahl drucken** wählen. Die Seiten beziehungsweise darin eingebettete PDF-Dokumente werden an den Windows-Standarddrucker gesendet.

Die App speichert keine Zugangsdaten. Die Anmeldung findet direkt im sichtbaren Edge statt; beim Schließen der App wird das Browserfenster geschlossen. Es werden nur Unterseiten auf demselben Portal und mit demselben Seitenpfad wie die Hauptseite angeboten.

## Voraussetzungen

- Windows 10 oder neuer
- Microsoft Edge
- Zugriff auf die Oberstufenwahl im Schulportal Hessen

Der Druck erfolgt ohne einzelne Druckdialoge über Edge an den Standarddrucker. Vor dem Batch zeigt die App eine Bestätigung.

## Windows-EXE bauen

Auf einem Windows-Rechner mit Python 3.12:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
```

Die fertige Datei liegt danach unter `dist\WahltoolBatchDruck.exe`. Ein Windows-Build kann nicht direkt auf Linux erzeugt werden. Ist das Repository mit GitHub verbunden, erstellt der Workflow **Build Windows executable** bei Push auf `main` oder manuell unter **Actions** ebenfalls ein herunterladbares EXE-Artefakt.
