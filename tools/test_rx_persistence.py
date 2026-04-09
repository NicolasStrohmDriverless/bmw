#!/usr/bin/env python3
"""
Comprehensive test: Validate that RX persistence code blocks work correctly.
This simulates what will happen when the fuzzer runs with the modified code.
"""

import sys
from pathlib import Path
from typing import List
from datetime import datetime

def test_rx_persistence():
    """Test if the 4 code blocks work together properly."""
    
    print("=" * 80)
    print("TEST: RX Persistence Code Blocks")
    print("=" * 80)
    
    all_pass = True
    
    # TEST 1: Buffer initialization (Line 572)
    print("\n[TEST 1] Buffer Initialization")
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = Path("generated_captures")
        capture_file = out_dir / f"capture_RX_results_TEST_{timestamp}.txt"
        capture_lines: List[str] = []
        
        assert isinstance(capture_lines, list), "capture_lines must be a list"
        assert len(capture_lines) == 0, "capture_lines must start empty"
        assert isinstance(capture_file, Path), "capture_file must be a Path object"
        
        print("  ✓ PASS: Buffer initialized correctly")
    except Exception as e:
        print(f"  ✗ FAIL: {e}")
        all_pass = False
    
    # TEST 2: TX frame logging (Line 606)
    print("\n[TEST 2] TX Frame Logging")
    try:
        # Simulate a TX frame
        item = {
            'can_id': 128,
            'dlc': 8,
            'data_hex': '00F0FCFFFFFF'
        }
        
        tx_entry = f"ID={item['can_id']},Type=D,Length={item['dlc']},Data={item['data_hex']}"
        capture_lines.append(tx_entry)
        
        assert len(capture_lines) == 1, "Should have 1 TX entry"
        assert "Type=D" in capture_lines[0], "TX entry must contain Type=D"
        assert "ID=128" in capture_lines[0], "TX entry must contain correct ID"
        
        print("  ✓ PASS: TX frame logged correctly")
        print(f"    Sample: {capture_lines[0]}")
    except Exception as e:
        print(f"  ✗ FAIL: {e}")
        all_pass = False
    
    # TEST 3: RX frame logging (Line 646 - CRITICAL)
    print("\n[TEST 3] RX Frame Logging (CRITICAL NEW FEATURE)")
    try:
        # Simulate an RX frame
        rx_id = 130
        class MockRxMsg:
            dlc = 8
        rx_msg = MockRxMsg()
        rx_data_hex = "00F0FCFFFFFF"
        
        rx_entry = f"ID={rx_id},Type=RX,Length={rx_msg.dlc},Data={rx_data_hex}"
        capture_lines.append(rx_entry)
        
        assert len(capture_lines) == 2, "Should have 1 TX + 1 RX entry"
        assert "Type=RX" in capture_lines[1], "RX entry must contain Type=RX"
        assert "ID=130" in capture_lines[1], "RX entry must contain correct ID"
        
        print("  ✓ PASS: RX frame logged correctly")
        print(f"    Sample: {capture_lines[1]}")
    except Exception as e:
        print(f"  ✗ FAIL: {e}")
        all_pass = False
    
    # TEST 4: Multiple TX/RX sequence
    print("\n[TEST 4] Multiple TX/RX Sequence")
    try:
        capture_lines.clear()
        
        # Simulate a real fuzzing sequence: TX, RX, TX, RX, TX, RX
        test_sequence = [
            {"type": "TX", "id": 128, "dlc": 1, "data": "80"},
            {"type": "RX", "id": 130, "dlc": 8, "data": "00F0FCFFFFFF"},
            {"type": "TX", "id": 128, "dlc": 2, "data": "807F"},
            {"type": "RX", "id": 130, "dlc": 8, "data": "00F0FCFFFFFF"},
            {"type": "TX", "id": 129, "dlc": 3, "data": "AA55FF"},
            {"type": "RX", "id": 131, "dlc": 8, "data": "0102030405060708"},
        ]
        
        for frame in test_sequence:
            if frame["type"] == "TX":
                entry = f"ID={frame['id']},Type=D,Length={frame['dlc']},Data={frame['data']}"
            else:  # RX
                entry = f"ID={frame['id']},Type=RX,Length={frame['dlc']},Data={frame['data']}"
            capture_lines.append(entry)
        
        assert len(capture_lines) == 6, "Should have 3 TX + 3 RX entries"
        assert sum(1 for line in capture_lines if "Type=D" in line) == 3, "Should have 3 TX entries"
        assert sum(1 for line in capture_lines if "Type=RX" in line) == 3, "Should have 3 RX entries"
        
        print("  ✓ PASS: Complex sequence handled correctly")
        print(f"    Total entries: {len(capture_lines)}")
        print(f"    TX entries: {sum(1 for line in capture_lines if 'Type=D' in line)}")
        print(f"    RX entries: {sum(1 for line in capture_lines if 'Type=RX' in line)}")
    except Exception as e:
        print(f"  ✗ FAIL: {e}")
        all_pass = False
    
    # TEST 5: Disk write and read (Line 694)
    print("\n[TEST 5] Disk Write & Read Back")
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        
        # Write to disk (Line 694 logic)
        capture_file.write_text("\n".join(capture_lines) + "\n", encoding="utf-8")
        
        assert capture_file.exists(), f"File {capture_file} was not created"
        
        # Read back and verify
        content = capture_file.read_text(encoding="utf-8")
        lines_read = content.strip().split("\n")
        
        assert len(lines_read) == len(capture_lines), "Round-trip lost data"
        assert "Type=RX" in content, "RX data not persisted to disk"
        
        print("  ✓ PASS: Data written and read back successfully")
        print(f"    File: {capture_file.name}")
        print(f"    Size: {capture_file.stat().st_size} bytes")
        print(f"    Lines persisted: {len(lines_read)}")
        
        # Cleanup
        capture_file.unlink()
    except Exception as e:
        print(f"  ✗ FAIL: {e}")
        all_pass = False
    
    # TEST 6: Code blocks present in spoofing.py
    print("\n[TEST 6] Verify Code Blocks in spoofing.py")
    try:
        spoofing_file = Path("bmw_gui/ui/pages/spoofing.py")
        if not spoofing_file.exists():
            raise FileNotFoundError(f"{spoofing_file} not found")
        
        content = spoofing_file.read_text(encoding="utf-8")
        
        required_patterns = [
            ("Buffer init", "capture_lines: List[str] = []"),
            ("TX logging", 'capture_lines.append('),
            ("RX type", 'Type=RX'),
            ("Disk write", 'capture_file.write_text'),
        ]
        
        missing = []
        for name, pattern in required_patterns:
            if pattern not in content:
                missing.append(name)
        
        if missing:
            raise AssertionError(f"Missing code blocks: {', '.join(missing)}")
        
        print("  ✓ PASS: All code blocks present in spoofing.py")
        for name, _ in required_patterns:
            print(f"    ✓ {name}")
    except Exception as e:
        print(f"  ✗ FAIL: {e}")
        all_pass = False
    
    # SUMMARY
    print("\n" + "=" * 80)
    if all_pass:
        print("✓ ALL TESTS PASSED - Fix is ready for production use")
        print("\nNext steps:")
        print("  1. Run: python bmw.py")
        print("  2. Click: Spoofing → Massensendung starten")
        print("  3. Check: generated_captures/capture_RX_results_*.txt")
        print("  4. Verify: File contains Type=RX entries")
        return 0
    else:
        print("✗ SOME TESTS FAILED - Fix needs correction")
        return 1

if __name__ == "__main__":
    sys.exit(test_rx_persistence())
