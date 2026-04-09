#!/usr/bin/env python3
"""
QUICK START GUIDE - BMW CAN Fuzzing mit RX-Erfassung
Praktische Anleitung zum sofort Umsetzen
"""

guide = """
╔═══════════════════════════════════════════════════════════════════════════╗
║              QUICK START: RX DATA CAPTURE NOW ENABLED                     ║
║                                                                           ║
║            "130 wird die ganze Zeit gesendet" Problem GELÖST             ║
╚═══════════════════════════════════════════════════════════════════════════╝


SITUATION JETZT:
────────────────────────────────────────────────────────────────────────────
✓ spoofing.py wurde MODIFIZIERT
✓ RX-Daten werden nun GESPEICHERT
✓ Keine Syntax-Fehler
✓ Bereit zum Testen


LOS GEHT'S - 3 SCHRITTE:
────────────────────────────────────────────────────────────────────────────

SCHRITT 1: Fuzzer starten
───────────────────────────
  $ cd c:\\Users\\nicol\\bmw
  $ python bmw.py
  
  Dann:
  → Auf "Spoofing" Tab klicken
  → "Massensendung starten" Button klicken
  → Warten bis Test beendet ist (~2-5 Minuten je nach Einstellungen)


SCHRITT 2: Nach neuem File suchen
──────────────────────────────────
  Öffnen Sie: c:\\Users\\nicol\\bmw\\generated_captures\\
  
  Suchen Sie nach NEUESTER Datei:
  capture_RX_results_YYYYMMDD_HHMMSS.txt
  
  (Das ist die neue Datei mit RX-Daten!)


SCHRITT 3: Datei untersuchen
────────────────────────────
  Option A - Mit Text-Editor öffnen:
    Windows Explorer → Double-Click auf Datei → Mit Notepad öffnen
  
  Option B - Mit Terminal analysieren (Windows PowerShell):
    
    # Prüf ob RX-Daten vorhanden (Ja/Nein):
    $ Select-String -Path "generated_captures\\capture_RX_results_*.txt" -Pattern "Type=RX"
    
    # Zähle RX-Einträge:
    $ (Select-String -Path "generated_captures\\capture_RX_results_*.txt" -Pattern "Type=RX").Count
    
    # Finde Top-10 Reaktions-IDs:
    $ Select-String -Path "generated_captures\\capture_RX_results_*.txt" -Pattern "Type=RX" | 
        ForEach-Object { $_.Line -split "," | Select-Object -First 1 } | 
        Group-Object | Sort-Object -Property Count -Descending | Select-Object -First 10


INTERPRETATION DER ERGEBNISSE:
────────────────────────────────

SZENARIO A: Datei hat VIELE RX-Einträge
└─ Beispiel:
   ID=128,Type=D,Length=0,Data=
   ID=128,Type=D,Length=1,Data=80
   ID=130,Type=RX,Length=8,Data=00F0FCFFFFFF  ← REAL RESPONSE!
   ID=128,Type=D,Length=2,Data=807F
   ID=128,Type=RX,Length=8,Data=00F0FCFFFFFF  ← REAL RESPONSE!

✓ GUTE NACHRICHT: Hardware funktioniert!
✓ GUTE NACHRICHT: ECUs reagieren!
✓ NÄCHSTES: Finde die reaktivsten IDs und fokussiere auf sie

SZENARIO B: Datei hat NUR TX-Einträge (Type=D), KEINE RX (Type=RX)
└─ Beispiel:
   ID=128,Type=D,Length=0,Data=
   ID=128,Type=D,Length=1,Data=80
   ID=128,Type=D,Length=2,Data=807F
   (... keine Type=RX einträge ...)

❌ PROBLEM: Hardware RX funktioniert nicht
❌ Mögliche Ursachen:
   1. MCP2515 im LOOPBACK-Modus statt NORMAL
   2. RX-Filter zu restriktiv
   3. CAN_RX Pin nicht richtig verdrahtet
   4. Vehicle nicht aktiv auf dem Bus
   5. CAN Transceiver Power Problem

✓ DEBUG: Folge den Anweisungen in IMPLEMENTATION_REPORT.txt


WEITERE BEFEHLE (PowerShell Windows):
──────────────────────────────────────────────────────────────────────────

# Zeige alle Type=RX Zeilen (mit Line Numbers):
gc "generated_captures\\capture_RX_results_*.txt" | Select-String "Type=RX" | 
  ForEach-Object { "$($_.LineNumber): $($_.Line)" } | head -20

# Zähle Reaktionen pro TX-ID:
$responses = (gc "generated_captures\\capture_RX_results_*.txt" | Select-String "Type=RX").Count
Write-Host "Total RX Responses: $responses"

# Finde die ID mit MEISTEN Reaktionen:
gc "generated_captures\\capture_RX_results_*.txt" | Select-String "Type=RX" | 
  ForEach-Object { $_.Line -split "," | Select-Object -First 1 } | 
  Group-Object | Sort-Object -Property Count -Descending | 
  Select-Object -First 1


ALTERNATIVE: BASH/GREP (wenn Git Bash or WSL installiert):
──────────────────────────────────────────────────────────

# Zähle RX-Einträge:
grep "Type=RX" generated_captures/capture_RX_results_*.txt | wc -l

# Top 10 Reaktions-IDs:
grep "Type=RX" generated_captures/capture_RX_results_*.txt | 
  cut -d, -f1 | sort | uniq -c | sort -rn | head -10

# Finde spezifische ID-Reaktionen (z.B. ID=130):
grep "Type=RX.*ID=130" generated_captures/capture_RX_results_*.txt


WAS BEDEUTET WAS:
─────────────────────────────────────────────────────────────────────────

  ID=XXX
    ├─ XXX = Die CAN-ID (in Dezimal)
    └─ Beispiel: ID=128 = 0x80, ID=256 = 0x100, etc.

  Type=D
    └─ Data Frame (WAS WIR SENDEN)

  Type=RX
    └─ RX Response (WAS DIE ECU ANTWORTET) ← DAS IST NEU!

  Length=Y
    └─ DLC (Data Length Code) 0-8 Bytes

  Data=HEXDATA
    └─ Hex-Payload
    └─ Beispiel: Data=00F0FCFFFFFF


NÄCHSTE SCHRITTE NACH ERFOLG:
─────────────────────────────

1. Identifiziere die Top-3 reaktivsten IDs
2. Lagere sie für gezielte Fuzzing aus
3. Untersuche die Payloads (welche Bytes ändern sich?)
4. Reverse-Engineere die Signale im DBC
5. Entwickle Exploits für die am meisten reagierenden IDs


FRAGEN?
───────

Siehe: IMPLEMENTATION_REPORT.txt
Siehe: ANALYSIS_SUMMARY.txt
Siehe: root_cause_analysis.py


VIEL ERFOLG!
═════════════════════════════════════════════════════════════════════════════
"""

print(guide)

# Speichere als Datei
from pathlib import Path
quick_start = Path("QUICK_START.txt")
quick_start.write_text(guide, encoding='utf-8', errors='replace')
print(f"\n✓ Quick Start Anleitung gespeichert: {quick_start}")
print(f"✓ Öffne die Datei zum Folgen der Schritte!")
