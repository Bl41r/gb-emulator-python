# gb-emulator-python
A gameboy emulator implementation written in Python - work in progress

This is a gameboy emulator written in Python.  I am following along loosely with
http://imrannazar.com/GameBoy-Emulation-in-JavaScript with this guide as
a reference.

Other references:
- http://www.devrs.com/gb/files/opcodes.html
- http://marc.rawer.de/Gameboy/Docs/GBCPUman.pdf
- https://github.com/Baekalfen/PyBoy

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

