#!/usr/bin/env python3
"""
FIX: Modify spoofing.py to capture RX data to file
This shows what needs to be changed to properly log received frames.
"""

FIX_INSTRUCTIONS = """
╔═══════════════════════════════════════════════════════════════════════════╗
║                  HOW TO FIX THE CAPTURE LOGGING                           ║
╚═══════════════════════════════════════════════════════════════════════════╝

PROBLEM:
  The spoofing.py _run_mass_send() method receives RX data from the bus
  but only logs it to GUI/stdout, NOT to the .txt file.

SOLUTION:
  Modify _run_mass_send() to write RX frames to a capture log file.

FILE TO MODIFY:
  c:/Users/nicol/bmw/bmw_gui/ui/pages/spoofing.py
  Method: _run_mass_send() around line 500-620

CHANGE REQUIRED (Pseudo-Code):
────────────────────────────────────────────────────────────────────────────

OLD CODE (current):
~~~~~~~~~~~~~~~~~~~~~
def _run_mass_send(self, tx_plan, repeats, delay_s, rx_window_s):
    bus = None
    tx_total = 0
    rx_total = 0
    reaction_by_tx = {}
    new_rx_ids = set()
    
    # ... setup ...
    
    try:
        bus = open_bus()
        
        for cycle in range(1, repeats + 1):
            for index, item in enumerate(tx_plan, start=1):
                # Send TX
                msg = make_msg(...)
                bus.send(msg)
                
                # Listen for RX (logged but NOT saved to file)
                while time.time() < deadline:
                    rx_msg = bus.recv(timeout=0.01)
                    if rx_msg:
                        self._queue_log(f"RX ... data={rx_msg.data}")
                        # ← Only GUI/stdout, file gets NOTHING
                        

NEW CODE (fixed):
~~~~~~~~~~~~~~~~~
def _run_mass_send(self, tx_plan, repeats, delay_s, rx_window_s):
    bus = None
    tx_total = 0
    rx_total = 0
    reaction_by_tx = {}
    new_rx_ids = set()
    
    # CREATE A CAPTURE OUTPUT FILE:
    root_dir = Path(__file__).resolve().parents[3]
    out_dir = root_dir / "generated_captures"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    capture_out = out_dir / f"capture_RX_{timestamp}.txt"  # ← NEW!
    capture_lines = []  # ← Buffer for lines
    
    try:
        bus = open_bus()
        
        for cycle in range(1, repeats + 1):
            for index, item in enumerate(tx_plan, start=1):
                # Send TX
                msg = make_msg(...)
                bus.send(msg)
                tx_id = (item["can_id"], item["is_extended"])
                
                # Log TX to file
                capture_lines.append(
                    f"ID={item['can_id']},Type=D,Length={item['dlc']},"
                    f"Data={item['data_hex']}"
                )
                
                # Listen for RX
                while time.time() < deadline:
                    rx_msg = bus.recv(timeout=0.01)
                    if rx_msg:
                        rx_id = getattr(rx_msg, "arbitration_id", 0)
                        rx_data = bytes(rx_msg.data).hex().upper()
                        
                        # Log RX to file ← THIS IS NEW!
                        capture_lines.append(
                            f"ID={rx_id},Type=RX,Length={rx_msg.dlc},"
                            f"Data={rx_data}"
                        )
                        
                        self._queue_log(f"RX ... data={rx_msg.data}")
        
        # Write all captured frames to file
        capture_out.write_text("\\n".join(capture_lines) + "\\n")
        self._queue_log(f"Capture-Datei gespeichert: {capture_out}")


TESTING THE FIX:
────────────────────────────────────────────────────────────────────────────

After modifying spoofing.py:

1. Re-run the fuzzing test with the GUI
2. Look for new file: generated_captures/capture_RX_YYYYMMDD_HHMMSS.txt
3. Check if it contains Type=RX entries

If you see RX data:
  ✓ Hardware works, ECUs ARE responding
  ✓ Analyze the RX patterns for vulnerabilities
  ✓ Focus on high-reaction IDs (those with most RX count)

If you see NO RX data:
  ✗ Hardware RX is not working (MCP2515 config)
  ✗ ECUs not responding (vehicle offline)
  ✗ CAN bus not active during test


WHAT THE FILE WOULD LOOK LIKE (if working):
────────────────────────────────────────────────────────────────────────────

ID=128,Type=D,Length=8,Data=80107FB500000000
ID=128,Type=RX,Length=8,Data=00F0FCFFFFFF       ← Real response!
ID=128,Type=D,Length=1,Data=80
(No RX for this one)
ID=128,Type=D,Length=2,Data=807F
ID=128,Type=RX,Length=8,Data=00F0FCFFFFFF       ← Same response pattern
ID=133,Type=D,Length=0
(No response)


ALTERNATIVE: USE STDOUT CAPTURE
────────────────────────────────────────────────────────────────────────────

If you don't want to modify spoofing.py, redirect output:

  python -c "
  import subprocess
  import sys
  from pathlib import Path
  
  # Run your fuzzer and capture stdout
  result = subprocess.run([sys.executable, 'run_fuzzer.py'],
                          capture_output=True, text=True)
  
  # Save output to file
  out_file = Path('captured_output.txt')
  out_file.write_text(result.stdout)
  print(f'Output saved to {out_file}')
  "


SUMMARY:
────────────────────────────────────────────────────────────────────────────

Your .txt files are test PLANS, not captured data.
The real RX went to stdout/GUI but nowhere permanent.
Modify spoofing.py OR capture stdout to get actual RX data.
Then re-analyze the RX patterns to find ECU vulnerabilities.
"""

print(FIX_INSTRUCTIONS)
