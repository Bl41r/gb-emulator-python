"""Memory interface.

This module serves as the interface between the GB memory and the CPU/GPU
units.
"""

import array
import sys

from cartridge import Cartridge
from joypad import Joypad


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
        self.divider_counter = 0
        self.cartridge = None
        self.joypad = Joypad()

    def load_rom_image(self, filename):
        """Load a ROM image into memory.

        TODO: multiple rom banks for oversized roms
        """
        self.memory.reset_memory()
        self.divider_counter = 0
        self.joypad = Joypad()
        rom_array = self._read_rom_file(filename)
        self.cartridge = Cartridge(rom_array)

        self.cpu.registers['pc'] = 0x0100

        self.cartridge_type = self.cartridge.cartridge_type
        print(
            "Cartridge type:",
            "0x{:02X} ({})".format(
                self.cartridge_type, self.cartridge.type_name
            ))
        print(
            "Manufacturer code:",
            self.read_byte(GbSystemInterface.MANUFACTURER_CODE_BYTE))
        print(
            "Language:",
            self.read_byte(GbSystemInterface.LANGUAGE_BYTE))
        print("Title:", self.cartridge.title)

        # print(f"ROM bytes at 0x0100: {self.memory.read_byte(0x0100):02X} {self.memory.read_byte(0x0101):02X} {self.memory.read_byte(0x0102):02X} {self.memory.read_byte(0x0103):02X}")

    def write_byte(self, address, value):
        """Write a byte to an address."""
        if (
            0x0000 <= address <= 0x7FFF
            or 0xA000 <= address <= 0xBFFF
        ):
            if self.cartridge:
                self.cartridge.write(address, value)
            return

        if address == 0xFF00:
            if self.joypad.write(value):
                self._request_interrupt(0x10)
            return

        if address == 0xFF46:
            self._transfer_oam(value)
            return

        if address == 0xFF04:
            old_signal = self._timer_signal()
            self.divider_counter = 0
            self.memory.write_byte(address, 0)
            if old_signal and not self._timer_signal():
                self._increment_tima()
            return

        if address == 0xFF07:
            old_signal = self._timer_signal()
            self.memory.write_byte(address, value & 0x07)
            if old_signal and not self._timer_signal():
                self._increment_tima()
            return

        self.memory.write_byte(address, value)
        if 0x8000 <= address <= 0x97FF:     # VRAM tile area write
            self.gpu.update_tile(address, value)

    def step(self, m_cycles):
        """Advance the divider and programmable timer by CPU M-cycles."""
        if not (self.read_byte(0xFF07) & 0x04):
            self.divider_counter = (
                self.divider_counter + m_cycles
            ) & 0x3FFF
            self.memory.write_byte(
                0xFF04, (self.divider_counter >> 6) & 0xFF
            )
            return

        for _ in range(m_cycles):
            old_signal = self._timer_signal()
            self.divider_counter = (self.divider_counter + 1) & 0x3FFF
            self.memory.write_byte(
                0xFF04, (self.divider_counter >> 6) & 0xFF
            )
            if old_signal and not self._timer_signal():
                self._increment_tima()

    def _timer_signal(self):
        """Return the timer input selected by TAC."""
        tac = self.memory.read_byte(0xFF07)
        if not (tac & 0x04):
            return 0

        divider_bits = {
            0x00: 7,
            0x01: 1,
            0x02: 3,
            0x03: 5,
        }
        return (self.divider_counter >> divider_bits[tac & 0x03]) & 1

    def _increment_tima(self):
        """Increment TIMA and request its interrupt on overflow."""
        tima = self.memory.read_byte(0xFF05)
        if tima == 0xFF:
            self.memory.write_byte(0xFF05, self.memory.read_byte(0xFF06))
            interrupt_flags = self.memory.read_byte(0xFF0F) | 0x04
            self.memory.write_byte(0xFF0F, interrupt_flags)
        else:
            self.memory.write_byte(0xFF05, tima + 1)

    def write_word(self, address, value):
        """Write a word into memory."""
        self.write_byte(address, value & 0xFF)
        self.write_byte((address + 1) & 0xFFFF, (value >> 8) & 0xFF)

    def read_byte(self, address):
        """Read a byte in memory."""
        if address == 0xFF00:
            return self.joypad.read()
        if (
            self.cartridge
            and (
                0x0000 <= address <= 0x7FFF
                or 0xA000 <= address <= 0xBFFF
            )
        ):
            return self.cartridge.read(address)
        return self.memory.read_byte(address)

    def set_button(self, button, is_pressed):
        """Update a joypad button and request its interrupt on a falling edge."""
        if self.joypad.set_button(button, is_pressed):
            self._request_interrupt(0x10)

    def _request_interrupt(self, mask):
        interrupt_flags = self.memory.read_byte(0xFF0F) | mask
        self.memory.write_byte(0xFF0F, interrupt_flags)

    def _transfer_oam(self, source_page):
        """Copy one page's first 160 bytes into object attribute memory."""
        self.memory.write_byte(0xFF46, source_page)
        source = source_page << 8
        values = [self.read_byte(source + offset) for offset in range(0xA0)]
        for offset, value in enumerate(values):
            self.memory.write_byte(0xFE00 + offset, value)

    def read_word(self, address):
        """Read a word from memory."""
        low = self.read_byte(address)
        high = self.read_byte((address + 1) & 0xFFFF)
        return low | (high << 8)

    def _read_rom_file(self, filename):
        """Return an array containing ROM file."""
        rom_array = array.array('B', range(0))
        with open(filename, 'rb') as f:
            rom_array.frombytes(f.read())

        if sys.byteorder != 'little':
            print('byteswapping rom...')
            rom_array.byteswap()

        return rom_array

    def get_cpu_clock(self):
        """For debugging."""
        return self.cpu.clock['m']

    def _show_mem_around_addr(self, address):
        """Print mem around address for debugging."""
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
