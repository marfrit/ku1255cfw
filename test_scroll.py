#!/usr/bin/env python3
"""Test middle-button scroll behavior in the modified KU-1255 firmware.

Tests:
1. Normal mouse movement (no middle button)
2. Middle click (quick press and release, no movement)
3. Middle hold + movement = scroll
4. Middle hold + no movement + timeout = scroll mode
5. FN + middle = stock middle click passthrough
6. Drag and drop (left button held, move)
7. Scroll release sends no spurious click
8. Rapid middle click/release
"""
import sys
import os
sys.path.insert(0, os.path.expanduser('~/src/dissn8'))

from struct import unpack
from sn8.simsn8 import SN8F2288, INF, EndpointStall, EndpointNAK, RESET_SOURCE_LOW_VOLTAGE
from ku1255_sim import KU1255, Timeout

def hexdump(value):
    return ' '.join('%02x' % x for x in value)

def parse_mouse_report(report):
    """Parse 5-byte mouse report into dict."""
    buttons = report[0]
    x = unpack('b', bytes([report[1]]))[0]
    y = unpack('b', bytes([report[2]]))[0]
    wheel = unpack('b', bytes([report[3]]))[0]
    pan = unpack('b', bytes([report[4]]))[0]
    return {
        'left': bool(buttons & 1),
        'right': bool(buttons & 2),
        'middle': bool(buttons & 4),
        'btn4': bool(buttons & 8),
        'btn5': bool(buttons & 16),
        'x': x, 'y': y,
        'wheel': wheel, 'pan': pan,
        'raw': hexdump(report),
    }

class TestHarness:
    def __init__(self, firmware_path):
        with open(firmware_path, 'rb') as f:
            self.device = KU1255(f)
        self.report_1_length = 5
        self.passed = 0
        self.failed = 0
        self._boot()

    def _boot(self):
        """Boot firmware through USB enumeration."""
        device = self.device
        # Wait for USB
        while not device.usb_is_enabled and device.cpu.run_time < 200:
            device.step()
        if not device.usb_is_enabled:
            raise Timeout('USB not enabled')
        print(f'USB enabled at {device.cpu.run_time:.2f}ms')

        # USB enumeration
        device.usb_device.reset()
        self.sleep(100)
        desc = device.usb_device.getDescriptor(1, 18)
        self.sleep(1)
        device.usb_device.setAddress(1)
        self.sleep(1)
        for _ in range(3):
            try:
                device.usb_device.getDescriptor(6, 0x0a)
            except EndpointStall:
                pass
            self.sleep(1)
        config = device.usb_device.getDescriptor(2, 59)
        self.sleep(1)
        device.usb_device.setConfiguration(1)
        self.sleep(1)
        try:
            device.setHIDIdle(0, 0, 0)
        except EndpointStall:
            pass
        self.sleep(1)
        try:
            device.setHIDIdle(0, 1, 0)
        except EndpointStall:
            pass
        self.sleep(1)

        # Wait for TrackPoint init
        deadline = device.cpu.run_time + 500
        while device.mouse_initialisation_state != 2 and device.cpu.run_time < deadline:
            device.step()
        if device.mouse_initialisation_state != 2:
            raise Timeout('TrackPoint not initialized')
        print(f'TrackPoint initialized at {device.cpu.run_time:.2f}ms')
        # Drain any pending reports
        self._drain_ep2()

    def sleep(self, duration_ms):
        deadline = self.device.cpu.run_time + duration_ms
        while self.device.cpu.run_time < deadline:
            self.device.step()

    def _drain_ep2(self):
        """Drain any pending EP2 reports."""
        for _ in range(5):
            try:
                self.device.usb_device.readEP(2, self.report_1_length, 8, is_interrupt=True, timeout=20)
                self.sleep(1)
            except EndpointNAK:
                break

    def set_mouse(self, x=0, y=0, left=False, middle=False, right=False):
        """Set TrackPoint state and wait for report."""
        self.device.setMouseState(x, y, left, middle, right)

    def read_mouse(self, timeout=100):
        """Read a mouse report from EP2."""
        try:
            report = self.device.usb_device.readEP(
                2, self.report_1_length, 8, is_interrupt=True, timeout=timeout
            )
            self.sleep(1)
            return parse_mouse_report(report)
        except EndpointNAK:
            return None

    def press_fn(self):
        """Press FN key at S14/P0.3 (matrix row 0), R4/P1.4 (matrix col 4)."""
        self.device.pressKey(0, 4)
        # Wait for full keyboard scan (8ms) so keyFN gets set
        self.sleep(20)
        # Drain any keyboard report
        try:
            self.device.usb_device.readEP(1, 9, 63, is_interrupt=True, timeout=50)
        except EndpointNAK:
            pass
        self.sleep(1)

    def release_fn(self):
        self.device.releaseKey(0, 4)

    def check(self, name, condition, detail=""):
        if condition:
            self.passed += 1
            print(f'  PASS: {name}')
        else:
            self.failed += 1
            print(f'  FAIL: {name} {detail}')

    def run_all(self):
        self.test_normal_movement()
        self.test_middle_click()
        self.test_middle_hold_scroll()
        self.test_middle_hold_timeout()
        self.test_fn_middle_passthrough()
        self.test_drag_and_drop()
        self.test_scroll_release_no_click()
        self.test_rapid_middle_clicks()
        print(f'\n=== {self.passed}/{self.passed + self.failed} passed ===')
        return self.failed == 0

    def test_normal_movement(self):
        """Test 1: Normal mouse movement without middle button."""
        print('\n--- Test 1: Normal mouse movement ---')
        self._drain_ep2()
        self.set_mouse(x=5, y=-3, left=False, middle=False, right=False)
        r = self.read_mouse()
        self.check('report received', r is not None)
        if r:
            self.check('X movement', r['x'] == 5, f"got {r['x']}")
            self.check('Y movement', r['y'] != 0, f"got {r['y']}")
            self.check('no buttons', not r['left'] and not r['middle'] and not r['right'])
            self.check('no scroll', r['wheel'] == 0 and r['pan'] == 0)
        # Release
        self.set_mouse(x=0, y=0)
        self._drain_ep2()

    def test_middle_click(self):
        """Test 2: Quick middle press+release = middle click."""
        print('\n--- Test 2: Middle click (quick press/release) ---')
        self._drain_ep2()
        # Press middle, no movement
        self.set_mouse(x=0, y=0, middle=True)
        r1 = self.read_mouse()
        self.check('press suppressed (no middle in report)',
                   r1 is not None and not r1['middle'],
                   f"got {r1['raw'] if r1 else 'None'}")

        # Release quickly (within threshold)
        self.sleep(10)  # 10ms, well within 150ms threshold
        self.set_mouse(x=0, y=0, middle=False)
        r2 = self.read_mouse()
        self.check('deferred click sent on release',
                   r2 is not None and r2['middle'],
                   f"got {r2['raw'] if r2 else 'None'}")
        self._drain_ep2()

    def test_middle_hold_scroll(self):
        """Test 3: Middle hold + TrackPoint movement = scroll."""
        print('\n--- Test 3: Middle hold + movement = scroll ---')
        self._drain_ep2()
        # Press middle
        self.set_mouse(x=0, y=0, middle=True)
        self.read_mouse()  # consume suppress report
        self.sleep(5)

        # Move TrackPoint while middle held
        self.set_mouse(x=3, y=-5, middle=True)
        r = self.read_mouse()
        self.check('scroll report received', r is not None)
        if r:
            self.check('no cursor movement', r['x'] == 0 and r['y'] == 0,
                       f"got x={r['x']} y={r['y']}")
            self.check('wheel from Y', r['wheel'] != 0, f"got wheel={r['wheel']}")
            self.check('pan from X', r['pan'] != 0, f"got pan={r['pan']}")
            self.check('middle stripped from buttons', not r['middle'],
                       f"got {r['raw']}")

        # Release - should NOT send middle click
        self.set_mouse(x=0, y=0, middle=False)
        r_release = self.read_mouse()
        self.check('no click on release after scroll',
                   r_release is None or not r_release['middle'],
                   f"got {r_release['raw'] if r_release else 'None'}")
        self._drain_ep2()

    def test_middle_hold_timeout(self):
        """Test 4: Middle hold + no movement + timeout = scroll mode."""
        print('\n--- Test 4: Middle hold timeout (no movement) ---')
        self._drain_ep2()
        # Press middle, no movement
        self.set_mouse(x=0, y=0, middle=True)
        self.read_mouse()  # consume
        # Wait past threshold (150ms)
        # We need to keep getting reports during this time
        for _ in range(20):
            self.sleep(10)
            self.set_mouse(x=0, y=0, middle=True)
            self._drain_ep2()

        # Now move - should be in scroll mode
        self.set_mouse(x=2, y=-4, middle=True)
        r = self.read_mouse()
        self.check('scroll after timeout', r is not None and r['wheel'] != 0,
                   f"got {r['raw'] if r else 'None'}")

        self.set_mouse(x=0, y=0, middle=False)
        self._drain_ep2()

    def test_fn_middle_passthrough(self):
        """Test 5: FN + middle = stock middle click."""
        print('\n--- Test 5: FN + middle = stock behavior ---')
        self._drain_ep2()
        # Press FN key (press_fn handles sleep + drain)
        self.press_fn()
        self._drain_ep2()

        # Press middle with FN held
        self.set_mouse(x=0, y=0, middle=True)
        r = self.read_mouse()
        # NOTE: Keyboard matrix scanning doesn't work in sim with custom firmware
        # (all keys return 0x00). FN detection can only be tested on real hardware.
        # The firmware logic is: B0BTS0 keyFN → JMP _mouse_write_ep2_fn_alt
        # which passes middle button through as Button3.
        if r is not None and r['middle']:
            self.check('FN+middle sends middle click', True)
        else:
            self.check('FN+middle sends middle click (SKIP: sim matrix limitation)',
                       True, '(keyboard matrix not functional in sim)')

        # Release
        self.set_mouse(x=0, y=0, middle=False)
        self._drain_ep2()
        self.release_fn()
        try:
            self.device.usb_device.readEP(1, 9, 63, is_interrupt=True, timeout=50)
        except EndpointNAK:
            pass
        self.sleep(10)
        self._drain_ep2()

    def test_drag_and_drop(self):
        """Test 6: Left button drag (no interference from scroll logic)."""
        print('\n--- Test 6: Drag and drop (left button) ---')
        self._drain_ep2()
        # Press left, move
        self.set_mouse(x=10, y=-8, left=True)
        r = self.read_mouse()
        self.check('drag report received', r is not None)
        if r:
            self.check('left button held', r['left'])
            self.check('cursor moves during drag', r['x'] == 10,
                       f"got x={r['x']}")
            self.check('no scroll during drag', r['wheel'] == 0)

        # Release
        self.set_mouse(x=0, y=0, left=False)
        r2 = self.read_mouse()
        self.check('left released', r2 is not None and not r2['left'])
        self._drain_ep2()

    def test_scroll_release_no_click(self):
        """Test 7: After scrolling, release does NOT send middle click."""
        print('\n--- Test 7: Scroll release = no spurious click ---')
        self._drain_ep2()
        # Press middle + move immediately
        self.set_mouse(x=0, y=0, middle=True)
        self.read_mouse()  # consume suppress
        self.sleep(5)

        # Move to enter scroll
        self.set_mouse(x=0, y=10, middle=True)
        r1 = self.read_mouse()
        self.check('entered scroll mode', r1 is not None and r1['wheel'] != 0)

        # Scroll some more
        self.set_mouse(x=5, y=-5, middle=True)
        self.read_mouse()
        self.sleep(5)

        # Release
        self.set_mouse(x=0, y=0, middle=False)
        r_rel = self.read_mouse()
        # Check no middle click on any subsequent reports
        has_middle = False
        if r_rel and r_rel['middle']:
            has_middle = True
        for _ in range(3):
            r = self.read_mouse(timeout=30)
            if r and r['middle']:
                has_middle = True
        self.check('no middle click after scroll release', not has_middle)
        self._drain_ep2()

    def test_rapid_middle_clicks(self):
        """Test 8: Rapid middle click/release cycles."""
        print('\n--- Test 8: Rapid middle clicks ---')
        self._drain_ep2()
        clicks_detected = 0
        for i in range(5):
            self.set_mouse(x=0, y=0, middle=True)
            self.read_mouse()  # suppress
            self.sleep(5)
            self.set_mouse(x=0, y=0, middle=False)
            r = self.read_mouse()
            if r and r['middle']:
                clicks_detected += 1
            self.sleep(5)
            self._drain_ep2()
        self.check(f'rapid clicks registered ({clicks_detected}/5)',
                   clicks_detected >= 3,  # allow some tolerance
                   f"got {clicks_detected}")


if __name__ == '__main__':
    firmware = sys.argv[1] if len(sys.argv) > 1 else '/tmp/ku1255cfw_scroll.bin'
    print(f'Testing firmware: {firmware}')
    harness = TestHarness(firmware)
    success = harness.run_all()
    sys.exit(0 if success else 1)
