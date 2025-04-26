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
        self.cartridge_type = None
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

        self.fake_fill_vram()
        print('loaded fake vram data!')

    def write_byte(self, address, value):
        """Write a byte to an address."""
        self.memory.write_byte(address, value)
        if address == 0xFF40:
            print(f"!!! LCDC write detected: {hex(value)} !!!")
        if 0x8000 <= address <= 0x97FF:     # VRAM tile area write
            self.gpu.update_tile(address, value)
            print(f"Writing to VRAM TILE area! Address: {hex(address)}, Value: {hex(value)}")
        elif 0x9800 <= address <= 0x9FFF:   # VRAM tilemap area write
            print(f"Writing to VRAM TILEMAP area! Address: {hex(address)}, Value: {hex(value)}")

    def write_word(self, address, value):
        """Write a word into memory."""
        self.memory.write_word(address, value)

    def read_byte(self, address):
        """Read a byte in memory."""
        # if address == 0xFF00:
        #     # Pretend the player is holding down "Start" and "A"
        #     # A = Bit 0, Start = Bit 3
        #     # Joypad reads 0 when button is pressed
        #     return 0b11100110  # Bits cleared (0) for A and Start
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
            print('byteswapping rom...')
            rom_array.byteswap()

        return rom_array

    def _show_mem_around_addr(self, address):
        """Print mem around address for dubugging."""
        if 65533 >= address >= 3:
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

    def fake_fill_vram(self):
        """Artificially fill VRAM with visible tile patterns."""
        for tile_num in range(20):  # Fill 20 fake tiles
            base_addr = 0x8000 + (tile_num * 16)
            for row in range(8):
                pattern = 0b10101010 if row % 2 == 0 else 0b01010101
                self.memory.write_byte(base_addr + row*2, pattern)      # low bits
                self.memory.write_byte(base_addr + row*2 + 1, pattern)   # high bits
                self.gpu.update_tile(base_addr + row*2, pattern)
                self.gpu.update_tile(base_addr + row*2 + 1, pattern)
