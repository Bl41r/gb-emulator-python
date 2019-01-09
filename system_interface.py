"""Memory interface.

This module serves as the interface between the GB memory and the CPU/GPU
units.
"""

import array
import sys


class GbSystemInterface(object):
    """Interface between CPU/GPU and memory unit."""

    CART_TITLE = range(0x0134, 0x0143)
    CART_TYPE_CHECK_BYTE = 0x0147
    MANUFACTURER_CODE_BYTE = 0x14B
    LANGUAGE_BYTE = 0x14A
    VERSION_BYTE = 0x14C

    def __init__(self, memory, cpu, gpu):
        """Init."""
        self.memory = memory
        self.cpu = cpu
        self.gpu = gpu

    def load_rom_image(self, filename):
        """Load a ROM image into memory."""
        self.memory.reset_memory()
        rom_array = self._read_rom_file(filename)

        for i in range(0, len(rom_array)):
            self.memory.write_byte(i, rom_array[i])

        self.cartridge_type = self.read_byte(
            GbSystemInterface.CART_TYPE_CHECK_BYTE)
        print(
            "Cartridge type:",
            self.read_byte(GbSystemInterface.CART_TYPE_CHECK_BYTE))
        print(
            "Manufacturer code:",
            self.read_byte(GbSystemInterface.MANUFACTURER_CODE_BYTE))
        print(
            "Language:",
            self.read_byte(GbSystemInterface.LANGUAGE_BYTE))
        title = ""
        for i in GbSystemInterface.CART_TITLE:
            title += chr(self.read_byte(i))
        print("Title:", title)

    def start_game(self):
        """Start the game."""
        while True:
            self.cpu.execute_next_operation()

    def write_byte(self, address, value):
        """Write a byte to an address."""
        self.memory.write_byte(address, value)

        if address >= 0x8000 and address <= 0xA000:     # VRAM write
            self.gpu.update_tile(address, value)
            print("Writing to vram!", address, value)

    def write_word(self, address, value):
        """Write a word into memory."""
        self.memory.write_word(address, value)

    def read_byte(self, address):
        """Read a byte in memory."""
        return self.memory.read_byte(address)

    def read_word(self, address):
        """Read a word from memory."""
        return self.memory.read_word(address)

    def _read_rom_file(self, filename):
        """Return an array containing ROM file."""
        rom_array = array.array('B', range(0))
        with open(filename, 'rb') as f:
            rom_array.frombytes(f.read())

        if sys.byteorder != 'little':
            rom_array.byteswap()

        return rom_array

    def _show_mem_around_addr(self, address):
        """Print mem around address for dubugging."""
        if address <= 65533 and address >= 3:
            print('\n--mem view-- address:val--------------------------------')
            print('{}:{}  {}:{}  >>{}:{}  {}:{}  {}:{}  {}:{}'.format(
                address - 2, self.read_byte(address - 2),
                address - 1, self.read_byte(address - 1),
                address, self.read_byte(address),
                address + 1, self.read_byte(address + 1),
                address + 2, self.read_byte(address + 2),
                address + 3, self.read_byte(address + 2)))
            print('--------------------------------------------------------\n')
        else:
            print('{}:{}'.format(address, self.read_byte(address)))
