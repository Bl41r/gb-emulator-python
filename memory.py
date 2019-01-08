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


class GbMemory(object):
    """Memory of the LC-3 VM."""

    def __init__(self):
        """Init."""
        self.mem_size = 2**16
        self.memory = array.array('B', [0 for i in range(self.mem_size)])
        self.cartridge_type = 0

    def write_byte(self, address, value):
        """Write a byte to an address."""
        self.memory[address] = value
        # self._show_mem_around_addr(address)

    def read_byte(self, address):
        """Return a byte from memory at an address."""
        return self.memory[address]

    def read_word(self, address):
        """Read a word from memoery @ address."""
        return self.read_byte(address) + (self.read_byte(address + 1) << 8)

    def write_word(self, address, value):
        """Write a word in mem @ address."""
        self.write_byte(address, value & 255)
        self.write_byte(address + 1, value >> 8)

    def reset_memory(self):
        """Reset all memory slots to 0."""
        for i in range(self.mem_size):
            self.memory[i] = 0
        self.cartridge_type = 0
