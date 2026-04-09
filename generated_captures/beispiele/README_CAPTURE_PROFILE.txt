Capture Profile Uebersicht
==========================

1) Schnell (wenig Last)
   Datei: capture_profile_schnell.txt
   Ziel: Kurz pruefen, ob TX/RX grundsaetzlich laeuft.
   Empfohlene UI Werte:
   - Max Varianten pro ID: 1
   - Max IDs: 0
   - Wiederholungen: 1
   - Intervall TX (ms): 20-100
   - RX Fenster (ms): 200-400

2) Mittel (mehr Signale)
   Datei: capture_profile_mittel.txt
   Ziel: Mehr Reaktionsmuster ohne zu langen Lauf.
   Empfohlene UI Werte:
   - Max Varianten pro ID: -1
   - Max IDs: 0
   - Wiederholungen: 2-3
   - Intervall TX (ms): 10-30
   - RX Fenster (ms): 400-800

3) Praezise (diagnosefokussiert)
   Datei: capture_profile_praezise.txt
   Ziel: Gezielt UDS/Brake/Workshop Sequenzen pruefen.
   Empfohlene UI Werte:
   - Max Varianten pro ID: -1
   - Max IDs: 0
   - Wiederholungen: 3-5
   - Intervall TX (ms): 10-20
   - RX Fenster (ms): 800-1500

4) Komplett Seed (breiter Start)
   Datei: capture_profile_komplett_seed.txt
   Ziel: Breiter Einstieg fuer laengere Scans.
   Empfohlene UI Werte:
   - Max Varianten pro ID: -1
   - Max IDs: 0
   - Wiederholungen: 5+
   - Intervall TX (ms): 5-20
   - RX Fenster (ms): 1000-2000

Hinweis
-------
Wenn du wirklich ALLES mitschneiden willst (auch ohne direkten TX Bezug),
nutze parallel den Live Sniffer statt nur des RX Fensters pro TX.
