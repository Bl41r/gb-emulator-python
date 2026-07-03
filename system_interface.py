"""Memory interface.

This module serves as the interface between the GB memory and the CPU/GPU
units.
"""

import array
import os
from pathlib import Path
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
    TIMER_BITS = (7, 1, 3, 5)

    def __init__(self, memory, cpu, gpu, apu=None):
        """Init."""
        self.cartridge_type = None
        self.memory = memory
        self.raw_memory = memory.memory
        self.cpu = cpu
        self.gpu = gpu
        self.apu = apu
        self.divider_counter = 0
        self.cartridge = None
        self.rom_path = None
        self.save_path = None
        self.direct_rom = None
        self.direct_rom_length = 0
        self.timer_enabled = False
        self.timer_bit = self.TIMER_BITS[0]
        self.timer_period_shift = self.timer_bit + 1
        self.joypad = Joypad()

    def load_rom_image(self, filename):
        """Load a ROM image into memory.

        TODO: multiple rom banks for oversized roms
        """
        self.memory.reset_memory()
        self.divider_counter = 0
        self._set_timer_control(0)
        self.joypad = Joypad()
        rom_array = self._read_rom_file(filename)
        self.cartridge = Cartridge(rom_array)
        self.rom_path = Path(filename)
        self.save_path = (
            self.rom_path.with_suffix(".sav")
            if self.cartridge.has_battery and self.cartridge.ram
            else None
        )
        self._load_save_ram()
        if self.cartridge.is_rom_only_type:
            self.direct_rom = self.cartridge.rom
        else:
            self.direct_rom = self.cartridge.rom_window
        self.direct_rom_length = len(self.direct_rom)
        self.cpu.direct_rom = self.direct_rom
        self.cpu.direct_rom_length = self.direct_rom_length

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
            value &= 0x07
            self.memory.write_byte(address, value)
            self._set_timer_control(value)
            if old_signal and not self._timer_signal():
                self._increment_tima()
            return

        if address == 0xFF41:
            self.gpu.write_stat(value)
            return

        if address == 0xFF45:
            self.gpu.write_lyc(value)
            return

        if (
            self.apu is not None
            and (
                0xFF10 <= address <= 0xFF26
                or 0xFF30 <= address <= 0xFF3F
            )
        ):
            self.memory.write_byte(address, value)
            self.apu.write_register(
                address,
                value,
                cycle=self.cpu.clock['m'] * 4,
            )
            return

        self.memory.write_byte(address, value)
        if 0x8000 <= address <= 0x97FF:     # VRAM tile area write
            self.gpu.update_tile(address, value)
        elif 0xFE00 <= address <= 0xFE9F:
            self.gpu.invalidate_sprite_cache()

    def step(self, m_cycles):
        """Advance the divider and programmable timer by CPU M-cycles."""
        memory = self.raw_memory
        divider_counter = self.divider_counter
        next_divider_counter = (divider_counter + m_cycles) & 0x3FFF
        div_value = next_divider_counter >> 6
        if not self.timer_enabled:
            self.divider_counter = next_divider_counter
            if memory[0xFF04] != div_value:
                memory[0xFF04] = div_value
            return

        shift = self.timer_period_shift
        edge_count = (divider_counter + m_cycles) >> shift
        edge_count -= divider_counter >> shift
        if edge_count:
            tima = memory[0xFF05]
            tma = memory[0xFF06]
            for _ in range(edge_count):
                if tima == 0xFF:
                    tima = tma
                    memory[0xFF0F] |= 0x04
                else:
                    tima += 1
            memory[0xFF05] = tima

        self.divider_counter = next_divider_counter
        if memory[0xFF04] != div_value:
            memory[0xFF04] = div_value

    def _timer_signal(self):
        """Return the timer input selected by TAC."""
        if not self.timer_enabled:
            return 0

        return (self.divider_counter >> self.timer_bit) & 1

    def m_cycles_until_timer_interrupt(self):
        """Return M-cycles until TIMA next overflows, or a large sentinel."""
        if not self.timer_enabled:
            return 0x10000

        period = 1 << self.timer_period_shift
        until_next_edge = period - (self.divider_counter & (period - 1))
        edges_until_overflow = 0x100 - self.raw_memory[0xFF05]
        return until_next_edge + (edges_until_overflow - 1) * period

    def _set_timer_control(self, tac):
        """Cache decoded TAC timer settings for the instruction hot path."""
        self.timer_enabled = bool(tac & 0x04)
        self.timer_bit = self.TIMER_BITS[tac & 0x03]
        self.timer_period_shift = self.timer_bit + 1

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
        if 0x0000 <= address <= 0x7FFF:
            cartridge = self.cartridge
            if cartridge:
                return cartridge.rom_window[address]
            return self.raw_memory[address]

        if 0xA000 <= address <= 0xBFFF:
            cartridge = self.cartridge
            if cartridge:
                if not cartridge.ram or not cartridge.ram_enabled:
                    return 0xFF
                offset = (
                    cartridge.active_ram_offset
                    + address - 0xA000
                )
                return (
                    cartridge.ram[offset]
                    if offset < len(cartridge.ram)
                    else 0xFF
                )
            return self.raw_memory[address]

        if (
            address == 0xFF44
            and self.memory.gb_doctor_test_mode
        ):
            return 0x90

        if address == 0xFF00:
            return self.joypad.read()

        return self.raw_memory[address]

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
        self.gpu.invalidate_sprite_cache()

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

    def flush_save_ram(self):
        """Atomically persist dirty battery-backed cartridge RAM."""
        cartridge = self.cartridge
        save_path = self.save_path
        if (
            cartridge is None
            or save_path is None
            or not cartridge.ram_dirty
        ):
            return False

        temporary_path = save_path.with_name(save_path.name + ".tmp")
        try:
            temporary_path.write_bytes(bytes(cartridge.ram))
            os.replace(str(temporary_path), str(save_path))
        except OSError as error:
            print(f"Could not write save RAM {save_path}: {error}")
            return False

        cartridge.ram_dirty = False
        print(f"Saved battery RAM: {save_path}")
        return True

    def _load_save_ram(self):
        cartridge = self.cartridge
        save_path = self.save_path
        if cartridge is None or save_path is None or not save_path.exists():
            return
        try:
            data = save_path.read_bytes()
        except OSError as error:
            print(f"Could not read save RAM {save_path}: {error}")
            return

        cartridge.load_ram(data)
        print(
            f"Loaded battery RAM: {save_path} "
            f"({len(data):,} bytes)"
        )

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
