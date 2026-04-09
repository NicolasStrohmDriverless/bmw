#!/usr/bin/env python3
"""
Hardware Diagnostics für BMW CAN Spoofing Setup
Überprüft MCP2515 Konfiguration und RX-Kapazität
"""

import struct
import sys

def analyze_capture_files():
    """Analysiert alle Capture-Dateien auf RX-Daten"""
    
    capture_files = [
        'generated_captures/capture_20260409_113048.txt',  # Init test
        'generated_captures/capture_20260409_113744.txt',  # Extended address sweep
        'generated_captures/capture_20260409_114650.txt',  # ID range fuzzing
    ]
    
    print("="*70)
    print("HARDWARE DIAGNOSTICS - CAN BUS CAPTURE ANALYSIS")
    print("="*70)
    print()
    
    for filepath in capture_files:
        print(f"\n📁 Analyzing: {filepath}")
        print("-" * 70)
        
        try:
            with open(filepath, 'r') as f:
                lines = f.readlines()
            
            tx_frames = 0
            rx_echoes = 0
            rx_data = 0
            msg_types = set()
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # Parse: ID=xxx,Type=X,Length=Y,...
                if 'Type=D' in line:
                    tx_frames += 1
                    msg_types.add('D')
                elif 'Type=R' in line:
                    rx_echoes += 1
                    msg_types.add('R')
                elif 'Type=' in line:
                    # Any other type would indicate real RX
                    rx_data += 1
                    msg_type = line.split('Type=')[1].split(',')[0]
                    msg_types.add(msg_type)
            
            print(f"  TX Frames (D):           {tx_frames}")
            print(f"  RX Echoes (R):           {rx_echoes}")
            print(f"  Real RX Data:            {rx_data}")
            print(f"  Message Types Found:     {sorted(msg_types)}")
            
            if rx_data == 0:
                print(f"\n  ⚠️  WARNING: NO GENUINE RX DATA DETECTED")
                print(f"      Only Type=D (TX) and Type=R (Echo) found!")
            
        except FileNotFoundError:
            print(f"  ❌ File not found: {filepath}")
        except Exception as e:
            print(f"  ❌ Error processing file: {e}")
    
    print("\n" + "="*70)
    print("DIAGNOSIS RESULTS")
    print("="*70)
    print("""
The MCP2515 is NOT capturing incoming CAN bus messages from external ECUs.

POSSIBLE CAUSES:
1. ❌ MCP2515 Operating Mode
   → Currently: Likely LOOPBACK or SILENT mode
   → Should be: NORMAL mode
   → Need to verify: CANCTRL register setting (bits 7-6)

2. ❌ Receive Buffer Configuration  
   → RxB0 filter/mask may be rejecting IDs
   → RxB1 buffer may not be enabled
   → Need to verify: RXFxSIDL/RXMxSIDL registers

3. ❌ Physical Wiring
   → MCP2515 CAN_RX pin → CAN transceiver RX output
   → CAN transceiver RX input → CAN bus line (CANH/CANL)
   → Verify continuity with multimeter

4. ❌ CAN Transceiver Enable
   → Transceiver may be in standby mode
   → RS (Recessive Supply) pin high = disabled
   → Need to verify: Transceiver is powered and enabled

5. ❌ RP2040 SPI Configuration
   → SPI bus may not be reading MCP2515 RX buffers correctly
   → CS (chip select) timing issue?
   → Need to verify: SPI speed and mode

RECOMMENDED ACTIONS:
✓ 1. Read MCP2515 CANCTRL register (address 0x0F)
     → Bits 7:6 should be 0x00 (NORMAL mode)
     → If 0x01 or 0x02, that's the problem!

✓ 2. Read RX filter configuration
     → RXF0SIDH (0x00), RXF0SIDL (0x01)
     → Mask RXM0SIDH (0x20), RXM0SIDL (0x21)
     → Look for overly restrictive filters

✓ 3. Monitor MCP2515 Status Register (0x0E)
     → Bit 4: RX0IF - Set if message in RxB0?
     → Bit 5: RX1IF - Set if message in RxB1?
     → Should toggle when CAN traffic is on the bus

✓ 4. Perform loopback test
     → Disable external CAN transceiver temporarily
     → Send TX frames with MCP2515 in LOOPBACK mode
     → Verify RX buffers fill (proves SPI/buffer works)

✓ 5. Check CAN bus voltage
     → CANH should be ~2.5V at idle
     → CANL should be ~2.5V at idle
     → Differential should stabilize around 0V
     → Oscilloscope needed if voltage wrong

TEST COMMAND SEQUENCE:
python3 -c "
import board
import busio
import digitalio

# MCP2515 Register Read Test
print('Reading MCP2515 registers...')
# Add your SPI code here to read:
# - CANCTRL (0x0F) - should read 0x00 for NORMAL mode
# - Status (0x0E) - check RX interrupt flags
# - RXF0SIDH (0x00) - check RX filter
"
""")

if __name__ == "__main__":
    analyze_capture_files()
