#!/usr/bin/env python3
"""
Verification Script: Validate that spoofing.py modifications are correct
"""

import re
from pathlib import Path

def verify_spoofing_py_changes():
    """Validate that all required changes were applied to spoofing.py"""
    
    spoofing_file = Path("bmw_gui/ui/pages/spoofing.py")
    
    if not spoofing_file.exists():
        print("❌ FAIL: spoofing.py not found")
        return False
    
    content = spoofing_file.read_text(encoding='utf-8')
    
    checks = []
    
    # Check 1: capture_file initialization
    check1 = 'capture_RX_results_' in content and 'timestamp' in content
    checks.append(("Create capture_RX_results file", check1))
    
    # Check 2: capture_lines buffer
    check2 = 'capture_lines' in content and 'List[str]' in content
    checks.append(("Create capture_lines buffer", check2))
    
    # Check 3: Log TX to file
    check3 = 'capture_lines.append' in content and 'Type=D' in content
    checks.append(("Log TX frames to capture_lines", check3))
    
    # Check 4: Log RX to file
    check4 = 'Type=RX' in content and 'rx_id' in content
    checks.append(("Log RX frames to capture_lines", check4))
    
    # Check 5: Write to disk in finally
    check5 = 'capture_file.write_text' in content
    checks.append(("Write capture_lines to disk", check5))
    
    # Check 6: No syntax errors
    try:
        import py_compile
        py_compile.compile(str(spoofing_file), doraise=True)
        check6 = True
    except:
        check6 = False
    checks.append(("No Python syntax errors", check6))
    
    print("\n" + "="*70)
    print("SPOOFING.PY MODIFICATION VERIFICATION")
    print("="*70 + "\n")
    
    all_pass = True
    for check_name, result in checks:
        status = "✓" if result else "❌"
        print(f"{status} {check_name}")
        if not result:
            all_pass = False
    
    print("\n" + "="*70)
    if all_pass:
        print("✓✓✓ ALL CHECKS PASSED ✓✓✓")
        print("spoofing.py successfully modified!")
    else:
        print("❌ SOME CHECKS FAILED")
    print("="*70 + "\n")
    
    return all_pass

if __name__ == "__main__":
    import sys
    success = verify_spoofing_py_changes()
    sys.exit(0 if success else 1)
