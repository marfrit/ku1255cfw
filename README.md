# ku1255cfw
Custom open firmware for the Lenovo KU-1255 compact USB keyboard

## Overview

The Lenovo ThinkPad Compact USB Keyboard with TrackPoint (KU-1255) uses a
Sonix SN8F2288FG 8-bit MCU with 12K words (24KB) flash and 512 bytes RAM.
The TrackPoint is connected via bit-banged I2C (P2.4 SCL, P2.5 SDA, address
0x2A, Synaptics proprietary protocol).

This firmware is a from-scratch rewrite based on the original by
[ranma](https://github.com/ranma/ku1255cfw), adding standalone middle-button
scroll and other missing features so the keyboard works fully without an
external converter.

## Features added over base firmware

### Middle-button scroll
3-state state machine (IDLE / UNDECIDED / SCROLLING) with 150ms timeout:
- **Short press** (<150ms): sends a normal middle click (deferred on release)
- **Hold + TrackPoint movement**: converts XY deltas to scroll wheel events
- **FN + middle button**: passes middle button through directly (no scroll logic)

### CapsLock LED feedback
Host LED output reports (SET_REPORT) are parsed and CapsLock state (bit 1) drives
the power LED on P5.3/PWM0 (active-low). The flasher magic byte sequence detection
is preserved.

### FN+F7 through FN+F12
| Key | Normal | With FN held |
|-----|--------|-------------|
| F7  | F7     | LGUI+P (display settings) |
| F8  | F8     | F8 (passthrough) |
| F9  | F9     | LGUI+I (settings) |
| F10 | F10    | LGUI (search) |
| F11 | F11    | LCTRL+LALT+TAB (task switch) |
| F12 | F12    | F12 (passthrough) |

### USB compliance fixes
- **HID GET_REPORT**: returns proper per-interface empty reports (8B keyboard / 5B mouse)
  instead of stale buffer contents. Some OSes query this on resume from suspend.
- **SET/CLEAR FEATURE**: tracks DEVICE_REMOTE_WAKEUP state instead of just ACKing.

## Flash space

| Firmware | Words used | Free | Utilization |
|----------|-----------|------|-------------|
| OEM      | 10,226 / 10,239 | 13 | 99.9% |
| This     | 10,238 / 10,239 | 1  | 100.0% |

Key debouncing is not implemented (and not needed) — the 8ms scan cycle naturally
debounces scissor switches (<1ms bounce time). The OEM firmware also does not debounce.

## Flashing

Requires [vpelletier/dissn8](https://github.com/vpelletier/dissn8) tools.

1. Build: `asn8 main.s -o ku1255cfw.bin`
2. Enter bootloader: hold **Return** while plugging in the keyboard
3. Flash: `flashsn8 ku1255cfw.bin`

## Simulator testing

`test_scroll.py` runs 23 automated tests against the
[dissn8 simulator](https://github.com/vpelletier/dissn8) via the `ku1255_sim.py`
harness. Tests cover all scroll state transitions, deferred click timing, FN modifier
interaction, and edge cases (rapid clicks, timeout behavior).

**Note:** The simulator requires a fix for PnUR register read handlers (see below).

## Simulator fixes (for vpelletier/dissn8)

Running this firmware in the dissn8 simulator exposed three bugs:

1. **PnUR read handlers crash** — `_volatile_dict` maps P0UR-P5UR read handlers to
   `None`. B0BSET/B0BCLR (read-modify-write) on these registers causes
   `TypeError: 'NoneType' object is not callable`. Fixed by adding `readPullUp()`
   returning the latch value. Branch: `pnur_readpullup` (PR pending upstream).

2. **Hardcoded HID descriptor sizes** — `ku1255_sim.py` assumed 0x51/0xD3 byte
   HID report descriptors (OEM sizes). This firmware uses 91/61 bytes. Fixed by
   parsing sizes dynamically from the config descriptor.

3. **Wrong HID descriptor recipient** — HID report descriptor requests must use
   interface recipient (0x81), not device (0x80), per USB spec. The OEM firmware
   happened to accept both.

## Dev setup
- [OpenViszla](https://github.com/openvizsla/ov_ftdi) USB protocol analyzer
- 5V-tolerant PL2303 UART interface (e.g. https://www.adafruit.com/product/954)
- S15 pad (SN8F2288 UTX) connected to header for UART debug interface

![PCB photo](/devsetup.jpg)
