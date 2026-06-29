# gb-emulator-python
A gameboy emulator implementation written in Python - work in progress

This is a gameboy emulator written in Python.  I am following along loosely with
http://imrannazar.com/GameBoy-Emulation-in-JavaScript with this guide as
a reference.

Other references:
- http://www.devrs.com/gb/files/opcodes.html
- http://marc.rawer.de/Gameboy/Docs/GBCPUman.pdf
- https://github.com/Baekalfen/PyBoy

Run a ROM:

```powershell
python main.py path/to/game.gb
```

Instruction and interrupt tracing is disabled by default. Enable it when
debugging with:

```powershell
python main.py --trace path/to/game.gb
```

Keyboard controls are the same on Windows, Linux, and macOS:

- D-pad: arrow keys
- A / B: `Z` / `X`
- Start: Enter or keypad Enter
- Select: Backspace

Supported cartridge hardware:

- ROM-only cartridges (`0x00`, `0x08`, `0x09`)
- MBC1 cartridges (`0x01`, `0x02`, `0x03`)
- MBC1 ROM and external RAM banking modes

Battery-backed RAM is currently kept in memory only; save-file persistence is
not implemented yet.

Current DMG graphics support includes background tiles, OAM DMA, and 8x8 or
8x16 sprites with palettes, flips, priority, transparency, and the 10-sprites-
per-scanline limit. Window rendering is not implemented. OAM DMA currently
copies immediately rather than modeling its 160 M-cycle CPU bus restriction.

## CPU regression suite

`doctor_suite.py` runs Blargg's 11 individual `cpu_instrs` ROMs headlessly
and compares every CPU state with Gameboy Doctor's reference traces. It stops
each ROM automatically on success, the first mismatch, or an emulator error.

Download the two upstream repositories into the ignored `test-roms` directory:

```powershell
git clone --depth 1 https://github.com/retrio/gb-test-roms.git test-roms/gb-test-roms
git clone --depth 1 https://github.com/robert/gameboy-doctor.git test-roms/gameboy-doctor
```

Run the entire suite:

```powershell
python doctor_suite.py
```

Run selected ROM numbers:

```powershell
python doctor_suite.py 1 5 10
```

