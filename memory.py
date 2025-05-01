"""Gameboy memory.

Cartridge
---------
[0000-3FFF] Cartridge ROM, bank 0: The first 16,384 bytes of the cartridge program are always available at this point in the memory map. Special circumstances apply:
[0000-00FF] BIOS: When the CPU starts up, PC starts at 0000h, which is the start of the 256-byte GameBoy BIOS code. Once the BIOS has run, it is removed from the memory map, and this area of the cartridge rom becomes addressable.
[0100-014F] Cartridge header: This section of the cartridge contains data about its name and manufacturer, and must be written in a specific format.
[4000-7FFF] Cartridge ROM, other banks: Any subsequent 16k "banks" of the cartridge program can be made available to the CPU here, one by one; a chip on the cartridge is generally used to switch between banks, and make a particular area accessible. The smallest programs are 32k, which means that no bank-selection chip is required.

System Mem
----------
[8000-9FFF] Graphics RAM: Data required for the backgrounds and sprites used by the graphics subsystem is held here, and can be changed by the cartridge program. This region will be examined in further detail in part 3 of this series.
[A000-BFFF] Cartridge (External) RAM: There is a small amount of writeable memory available in the GameBoy; if a game is produced that requires more RAM than is available in the hardware, additional 8k chunks of RAM can be made addressable here.
[C000-DFFF] Working RAM: The GameBoy's internal 8k of RAM, which can be read from or written to by the CPU.
[E000-FDFF] Working RAM (shadow): Due to the wiring of the GameBoy hardware, an exact copy of the working RAM is available 8k higher in the memory map. This copy is available up until the last 512 bytes of the map, where other areas are brought into access.

[FE00-FE9F] Graphics: sprite information: Data about the sprites rendered
by the graphics chip are held here, including the sprites' positions and
attributes.

[FF00-FF7F] Memory-mapped I/O: Each of the GameBoy's subsystems (graphics, sound, etc.) has control values, to allow programs to create effects and use the hardware. These values are available to the CPU directly on the address bus, in this area.
[FF80-FFFF] Zero-page RAM: A high-speed area of 128 bytes of RAM is available at the top of memory. Oddly, though this is "page" 255 of the memory, it is referred to as page zero, since most of the interaction between the program and the GameBoy hardware occurs through use of this page of memory.
"""

import array

WATCH_ADDRESSES = {0xFF44}

class GbMemory(object):
    """Memory of the LC-3 VM."""

    def __init__(self, skip_bios=False, test_mode=False):
        """Init."""
        self.mem_size = 2**16
        self.memory = array.array('B', [0 for i in range(self.mem_size)])
        self.cartridge_type = 0
        if not skip_bios:
            self.initialize_memory()
        self.test_mode = test_mode

    def write_byte(self, address, value):
        """Write a byte to an address."""
        # === DEBUG: Watch specific address ===
        if address in WATCH_ADDRESSES:
            print(f"[MEMORY] WRITE to {address:04X}: {value:02X}")
        # ======================================
        self.memory[address] = value

    def read_byte(self, address):
        """Return a byte from memory at an address."""
        if address == 0xFF44 and self.test_mode:
            return 0x90
        return self.memory[address]

    def read_word(self, address):
        """Read a word from memoery @ address."""
        return self.read_byte(address) + (self.read_byte(address + 1) << 8)

    def write_word(self, address, value):
        """Write a word in mem @ address."""
        low = value & 0xFF
        high = (value >> 8) & 0xFF

        if address in WATCH_ADDRESSES:
            print(f"[MEMORY] WRITE (low) to {address:04X}: {low:02X}")
        if (address + 1) in WATCH_ADDRESSES:
            print(f"[MEMORY] WRITE (high) to {address + 1:04X}: {high:02X}")

        self.write_byte(address, low)
        self.write_byte(address + 1, high)

    def reset_memory(self):
        """Reset all memory slots to 0."""
        for i in range(self.mem_size):
            self.memory[i] = 0
        self.cartridge_type = 0

    def initialize_memory(self):
        initial_values = {
            0xFF05: 0x00, 0xFF06: 0x00, 0xFF07: 0x00,
            0xFF10: 0x80, 0xFF11: 0xBF, 0xFF12: 0xF3, 0xFF14: 0xBF,
            0xFF16: 0x3F, 0xFF17: 0x00, 0xFF19: 0xBF,
            0xFF1A: 0x7F, 0xFF1B: 0xFF, 0xFF1C: 0x9F, 0xFF1E: 0xBF,
            0xFF20: 0xFF, 0xFF21: 0x00, 0xFF22: 0x00, 0xFF23: 0xBF,
            0xFF24: 0x77, 0xFF25: 0xF3, 0xFF26: 0xF1,
            0xFF40: 0x91, 0xFF42: 0x00, 0xFF43: 0x00, 0xFF45: 0x00,
            0xFF47: 0xFC, 0xFF48: 0xFF, 0xFF49: 0xFF,
            0xFF4A: 0x00, 0xFF4B: 0x00, 0xFFFF: 0x00
        }
        for addr, value in initial_values.items():
            self.write_byte(addr, value)
