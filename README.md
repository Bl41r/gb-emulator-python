# gb-emulator-python
A Game Boy emulator implementation written in Python — work in progress.

This emulator began by loosely following
[GameBoy Emulation in JavaScript](http://imrannazar.com/GameBoy-Emulation-in-JavaScript)
and has since grown to support playable commercial DMG games, audio, battery
saves, memory banking, input, and automated CPU regression testing.

## Current status

The following games have been tested through normal gameplay:

| Game | Cartridge hardware | Status |
| --- | --- | --- |
| Tetris | ROM only | Playable with graphics, input, and audio |
| Donkey Kong Land | MBC1 + RAM + battery | Playable; saving and audio work |
| Final Fantasy Adventure | MBC2 + battery | Playable; MBC2 banking and saving work |
| Kirby's Pinball Land | MBC2 + battery | Playable; graphics, banking, and saving work |
| Pokémon Blue | MBC3 + RAM + battery | Playable; dialogs, saving, and audio work |
| The Legend of Zelda: Link's Awakening | MBC5 + RAM + battery | Playable; window overlays, raster scrolling, saving, and audio work |

ROM images are not included in this repository.

Python 3.12 is recommended. Create an isolated environment and install the
runtime dependencies on Windows with:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

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

For performance work, run a ROM for a fixed number of frames and optionally
write a `cProfile` capture:

```powershell
python main.py roms/tetris.gb --max-frames 60 --profile profile.stats
python main.py roms/tetris.gb --no-display --max-frames 60 --profile profile-headless.stats
```

Count exact base and CB-prefixed opcodes without cProfile's larger overhead:

```powershell
python main.py roms/tetris.gb --uncapped --no-audio --opcode-stats --max-seconds 30
```

Capture GPU diagnostics and visual reference frames when investigating CGB
rendering:

```powershell
python main.py roms/Zelda_IV_ZX.gb --gbc --no-display --max-frames 900 --gpu-diagnostics
python main.py roms/Zelda_IV_ZX.gb --gbc --no-display --max-frames 900 --screenshot-dir captures/zelda --screenshot-start-frame 300 --screenshot-end-frame 900 --screenshot-interval-frames 60
```

Compare this emulator against PyBoy for the same ROM and frame range:

```powershell
python tools/visual_compare.py roms/Zelda_IV_ZX.gb --gbc --start-frame 1494 --end-frame 2094 --interval-frames 60 --output-dir captures/zelda_beach_compare
```

The visual comparison tool writes this emulator's captures, PyBoy reference
captures, individual contact sheets, and a combined contact sheet under the
chosen output directory.

For cross-hardware comparisons, select exact rows with `--modes`:

```powershell
python tools/visual_compare.py roms/Zelda_IV_ZX.gb --modes ours-cgb pyboy-cgb ours-dmg pyboy-dmg --start-frame 1494 --end-frame 1614 --interval-frames 5 --crop 0 0 160 70 --make-gif --motion-metrics --output-dir captures/zelda_four_way_compare
```

For motion-sensitive rendering bugs, add `--make-gif`. This always writes a
side-by-side PNG sequence under `motion_frames` and a browser-playable
`motion_viewer.html`; if the optional `imageio` package is installed, it also
writes `motion_compare.gif`.

```powershell
python tools/visual_compare.py roms/Zelda_IV_ZX.gb --gbc --start-frame 1494 --end-frame 1614 --interval-frames 5 --crop 0 0 160 70 --make-gif --output-dir captures/zelda_beach_motion_compare
```

Script repeatable button input for profiling gameplay instead of title screens:

```powershell
python main.py roms/tetris.gb --input-script input_scripts/tetris_start.json --max-frames 600 --profile profile-gameplay.stats
```

Input scripts are JSON arrays of frame-based button events:

```json
[
  {"frame": 60, "button": "start", "pressed": true},
  {"frame": 68, "button": "start", "pressed": false}
]
```

If rendering is the bottleneck, skip displayed frames while still emulating
every frame:

```powershell
python main.py roms/tetris.gb --frameskip 2
```

`--frameskip 1` draws every completed frame. `--frameskip 2` draws every other
completed frame, `--frameskip 3` draws every third frame, and so on.

Displayed gameplay is paced to the DMG's approximately 59.73 FPS by default.
Disable pacing and audio for performance measurements with:

```powershell
python main.py roms/tetris.gb --uncapped
```

Use `--no-audio` to retain normal frame pacing without sound.

Output volume defaults to 10 percent. Set it from 0 to 100 with:

```powershell
python main.py roms/tetris.gb --volume 25
```

When running with a window, the title bar updates about once per second with
recent emulated FPS, drawn FPS, and instruction throughput.

Keyboard controls are the same on Windows, Linux, and macOS:

- D-pad: arrow keys
- A / B: `Z` / `X`
- Start: Enter or keypad Enter
- Select: Backspace

Supported cartridge hardware:

- ROM-only cartridges (`0x00`, `0x08`, `0x09`)
- MBC1 cartridges (`0x01`, `0x02`, `0x03`)
- MBC1 ROM and external RAM banking modes
- MBC2 cartridges (`0x05`, `0x06`) with mirrored 512×4-bit internal RAM
- MBC3 cartridges without a real-time clock (`0x11`, `0x12`, `0x13`)
- MBC5 cartridges (`0x19` through `0x1E`), including rumble bank masks

Battery-backed cartridge RAM is loaded from a `.sav` file beside the ROM and
written atomically when the emulator exits normally.

Current DMG graphics support includes background tiles, OAM DMA, and 8x8 or
8x16 sprites with palettes, flips, priority, transparency, and the 10-sprites-
per-scanline limit. Window rendering, scrolling, LCD STAT interrupts, and the
line-153 `LY` timing behavior used by raster effects are implemented. LCD
enable and disable transitions reset the PPU state and suppress scanline and
VBlank activity while the display is off. OAM DMA currently copies immediately
rather than modeling its 160 M-cycle CPU bus restriction.

Audio support includes all four DMG channels: two square waves, Channel 1
frequency sweep, programmable wave RAM, and noise/percussion. Length counters,
volume envelopes, stereo routing, cycle-timestamped register writes, and
continuous SDL audio streaming are also implemented.

## CPU regression suite

`doctor_suite.py` runs Blargg's 11 individual `cpu_instrs` ROMs headlessly
and compares every CPU state with Gameboy Doctor's reference traces. It stops
each ROM automatically on success, the first mismatch, or an emulator error.
Run this suite before and after CPU, memory, timer, interrupt, or PPU timing
changes.

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
