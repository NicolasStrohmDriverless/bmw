#!/usr/bin/env python3
"""
BMW CAN Spoofing - Understanding the Capture Format

CRITICAL DISCOVERY:
The "capture" .txt files are GENERATION PLANS, not actual bus captures!
"""

ANALYSIS = """
╔═══════════════════════════════════════════════════════════════════════════╗
║                 BMW CAN HARDWARE + SOFTWARE ANALYSIS                      ║
╚═══════════════════════════════════════════════════════════════════════════╝

PART 1: WHAT ARE THE capture_*.txt FILES?
────────────────────────────────────────────────────────────────────────────
These files contain GENERATION PLANS for fuzzing, NOT actual CAN bus captures:

  Type=D → Data frames WE GENERATE (what the fuzzer SENDS)
  Type=R → Remote frames WE GENERATE (optional test signals)
  
Source Code Location:
  bmw_gui/ui/pages/spoofing.py::_generate_capture_file_now() 
  - Lines 297-352
  
What it does:
  ✓ Reads DBC file to extract known CAN IDs (0x000 - 0x7FF)
  ✓ For EACH ID, generates 4 payload VARIANTS:
    - Type=D, Length=0       (empty frame)
    - Type=D, Length=1       (1-byte with pattern)
    - Type=D, Length=2       (2-byte with checksum)
    - Type=D, Length=8       (full 8-byte frame)
  ✓ Writes all variants to capture_YYYYMMDD_HHMMSS.txt
  ✓ Does NOT contain ANY received data

────────────────────────────────────────────────────────────────────────────

PART 2: WHERE DOES THE REAL FUZZING HAPPEN?
────────────────────────────────────────────────────────────────────────────
Real CAN bus interaction occurs in:
  bmw_gui/ui/pages/spoofing.py::_run_mass_send()
  - Lines ~500-700

The actual FUZZING LOOP:
  
  1. Load capture plan from file (the Type=D frames)
  2. Open CAN bus via python-can (PCAN backend)
  3. FOR EACH planned TX:
       A. Send the frame: bus.send(msg)
       B. LISTEN for RX responses for rx_window_s seconds
       C. Log ALL received frames to the GUI log
       D. Count reactions per TX ID
  
  4. Output results to GUI + stdout (NOT back to txt file)

Key Code Section:
────────────────
    rx_seen = 0
    deadline = time.time() + rx_window_s
    
    while not self._worker_stop.is_set() and time.time() < deadline:
        rx_msg = bus.recv(timeout=0.01)  ← ← ← REAL RX FROM BUS!
        if rx_msg is None:
            continue
        
        rx_seen += 1
        # ... log to GUI and stdout
        
    self._queue_log(
        f"RX summary for ID=0x{id}: count={rx_seen}"
    )

────────────────────────────────────────────────────────────────────────────

PART 3: THE REAL PROBLEM
────────────────────────────────────────────────────────────────────────────
The fuzzer DID run and DID listen for RX.

The OUTPUT was only to STDOUT/GUI logs, not to the .txt files.

But the .txt files show:
  - 2048 TX frames (Type=D)  ← Correctly logged
  - 2048 RX echoes (Type=R)  ← Bus loopback echoes
  - ZERO genuine RX from ECUs ← This is the REAL issue!

This means:
  ✓ Hardware sent frames correctly (TX shows in file)
  ✓ Bus acknowledgment worked (echo shows in file)
  ✗ NO RESPONSES from external ECUs (missing RX data)

Why are there NO RX responses?
────────────────────────────────────────────────────────────────────────────

Either:
  A. MCP2515 RX hardware is not configured correctly
  B. CAN bus transceiver RX line is not connected
  C. ECUs on the real vehicle bus are NOT RESPONDING to these IDs
  D. Vehicle is not in an active state (motor off, etc.)

What the .txt format ACTUALLY shows:
────────────────────────────────────────────────────────────────────────────

  ID=128,Type=D,Length=0        ← Send ID 0x80 with no data
  ID=128,Type=D,Length=1,...    ← Send ID 0x80 with 1-byte payload
  ID=128,Type=D,Length=2,...    ← Send ID 0x80 with 2-byte payload
  ID=128,Type=D,Length=8,...    ← Send ID 0x80 with 8-byte payload
  ID=128,Type=R,Length=8        ← Acknowledge frame (echo)
  
  [Then repeat for next ID...]

The "Type=R" is NOT a response - it's a REMOTE FRAME or BUS ECHO.

────────────────────────────────────────────────────────────────────────────

PART 4: WHAT'S MISSING?
────────────────────────────────────────────────────────────────────────────

To capture REAL ECU responses, the code would need to:
  1. After each TX, wait rx_window_s
  2. Collect all RX frames received on bus
  3. WRITE RX frames to the .txt file with Type=RX or similar

EXAMPLE of what we're NOT seeing:
  
  ID=128,Type=D,Length=8,Data=80107FB500000000
  ID=128,Type=R,Length=8
  ID=130,Type=RX,Length=8,Data=00F0FCFFFFFF      ← MISSING! ECU response
  ID=128,Type=D,Length=1,Data=80
  ID=128,Type=R,Length=8
  (no RX for this ID)

────────────────────────────────────────────────────────────────────────────

CONCLUSION
────────────────────────────────────────────────────────────────────────────

The captured .txt files are NOT bus captures - they're TEST PLANS.
The real RX data went to stdout/GUI, not to file.
The absence of RX in the file = absence of RX on the actual bus.

OPTIONS TO FIX:
  1. Modify spoofing.py to WRITE RX frames to .txt file
  2. Redirect stdout to capture all console output
  3. Check if message timestamps match real responses
  4. Re-test with hardware debugged (MCP2515 RX enabled)
"""

print(ANALYSIS)
