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

    def __init__(self, memory, cpu, gpu, apu=None, force_cgb_mode=False):
        """Init."""
        self.cartridge_type = None
        self.memory = memory
        self.raw_memory = memory.memory
        self.cpu = cpu
        self.gpu = gpu
        self.apu = apu
        self.force_cgb_mode = force_cgb_mode
        self.cgb_mode = False
        self.double_speed = False
        self.cgb_vram_bank1 = bytearray(0x2000)
        self.cgb_wram_banks = [bytearray(0x1000) for _ in range(7)]
        self.cgb_wram_bank = 1
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
        self.cgb_bg_palette_index = 0
        self.cgb_obj_palette_index = 0
        self.cgb_bg_palette_data = bytearray(0x40)
        self.cgb_obj_palette_data = bytearray(0x40)
        self.cgb_bg_palette_rgb = [[(0, 0, 0) for _ in range(4)] for _ in range(8)]
        self.cgb_obj_palette_rgb = [[(0, 0, 0) for _ in range(4)] for _ in range(8)]
        self.cgb_bg_palette_generation = 0
        self.cgb_obj_palette_generation = 0

    def load_rom_image(self, filename):
        """Load a ROM image into memory.

        TODO: multiple rom banks for oversized roms
        """
        self.memory.reset_memory()
        self.cgb_vram_bank1[:] = bytes(0x2000)
        for bank in self.cgb_wram_banks:
            bank[:] = bytes(0x1000)
        self.cgb_wram_bank = 1
        self.cgb_bg_palette_index = 0
        self.cgb_obj_palette_index = 0
        self.cgb_bg_palette_data[:] = bytes(0x40)
        self.cgb_obj_palette_data[:] = bytes(0x40)
        self.cgb_bg_palette_generation = 0
        self.cgb_obj_palette_generation = 0
        self._refresh_cgb_palette_rgb(
            self.cgb_bg_palette_data,
            self.cgb_bg_palette_rgb,
        )
        self._refresh_cgb_palette_rgb(
            self.cgb_obj_palette_data,
            self.cgb_obj_palette_rgb,
        )
        self.divider_counter = 0
        self._set_timer_control(0)
        self.joypad = Joypad()
        rom_array = self._read_rom_file(filename)
        self.cartridge = Cartridge(rom_array)
        self.cgb_mode = self.force_cgb_mode or self.cartridge.cgb_only
        self.gpu.cgb_mode = self.cgb_mode
        if self.cgb_mode:
            self._initialize_cgb_mode()
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
        if self.cgb_mode:
            reason = (
                "CGB-only cartridge"
                if self.cartridge.cgb_only
                else "--gbc requested"
            )
            print(f"Hardware mode: Game Boy Color ({reason})")
        elif self.cartridge.supports_cgb:
            print("Hardware mode: DMG (ROM also supports Game Boy Color)")
        else:
            print("Hardware mode: DMG")

        # print(f"ROM bytes at 0x0100: {self.memory.read_byte(0x0100):02X} {self.memory.read_byte(0x0101):02X} {self.memory.read_byte(0x0102):02X} {self.memory.read_byte(0x0103):02X}")

    def _initialize_cgb_mode(self):
        """Apply the post-boot state needed to identify as CGB hardware."""
        memory = self.raw_memory
        self.cpu.registers['a'] = 0x11
        memory[0xFF4D] = 0x7E  # KEY1, normal speed, prepare bit clear
        memory[0xFF4F] = 0xFE  # VBK, VRAM bank 0
        memory[0xFF51] = 0xFF
        memory[0xFF52] = 0xFF
        memory[0xFF53] = 0xFF
        memory[0xFF54] = 0xFF
        memory[0xFF55] = 0xFF
        memory[0xFF68] = 0x00  # BG palette index
        memory[0xFF69] = 0x00  # BG palette data
        memory[0xFF6A] = 0x00  # OBJ palette index
        memory[0xFF6B] = 0x00  # OBJ palette data
        memory[0xFF70] = 0xF8  # SVBK, WRAM bank 1 selected by value 0

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

        if self.cgb_mode and address == 0xFF4D:
            self.memory.write_byte(address, (self.raw_memory[address] & 0x80) | 0x7E | (value & 0x01))
            return

        if self.cgb_mode and address == 0xFF4F:
            self.memory.write_byte(address, 0xFE | (value & 0x01))
            return

        if self.cgb_mode and 0xFF51 <= address <= 0xFF55:
            self.memory.write_byte(address, value)
            if address == 0xFF55:
                self._cgb_dma_transfer(value)
            return

        if self.cgb_mode and address == 0xFF68:
            self.cgb_bg_palette_index = value & 0xBF
            self.memory.write_byte(address, self.cgb_bg_palette_index)
            return

        if self.cgb_mode and address == 0xFF69:
            palette_offset = self.cgb_bg_palette_index & 0x3F
            palette_number = palette_offset >> 3
            palette_changed = self.cgb_bg_palette_data[palette_offset] != value
            if self.gpu.diagnostics_enabled:
                diagnostics = self.gpu.diagnostics
                diagnostics['cgb_bg_palette_writes'] = (
                    diagnostics.get('cgb_bg_palette_writes', 0) + 1
                )
                if not palette_changed:
                    diagnostics['cgb_bg_palette_redundant_writes'] = (
                        diagnostics.get('cgb_bg_palette_redundant_writes', 0) + 1
                    )
            if palette_changed:
                self._write_cgb_palette_byte(
                    self.cgb_bg_palette_data,
                    self.cgb_bg_palette_rgb,
                    palette_offset,
                    value,
                )
                self.cgb_bg_palette_generation += 1
                self.gpu.invalidate_cgb_bg_palette_cache(palette_number)
            self.memory.write_byte(address, value)
            if self.cgb_bg_palette_index & 0x80:
                self.cgb_bg_palette_index = (
                    (self.cgb_bg_palette_index & 0x80)
                    | ((self.cgb_bg_palette_index + 1) & 0x3F)
                )
                self.memory.write_byte(0xFF68, self.cgb_bg_palette_index)
            return

        if self.cgb_mode and address == 0xFF6A:
            self.cgb_obj_palette_index = value & 0xBF
            self.memory.write_byte(address, self.cgb_obj_palette_index)
            return

        if self.cgb_mode and address == 0xFF6B:
            palette_offset = self.cgb_obj_palette_index & 0x3F
            palette_number = palette_offset >> 3
            palette_changed = self.cgb_obj_palette_data[palette_offset] != value
            if self.gpu.diagnostics_enabled:
                diagnostics = self.gpu.diagnostics
                diagnostics['cgb_obj_palette_writes'] = (
                    diagnostics.get('cgb_obj_palette_writes', 0) + 1
                )
                if not palette_changed:
                    diagnostics['cgb_obj_palette_redundant_writes'] = (
                        diagnostics.get('cgb_obj_palette_redundant_writes', 0) + 1
                    )
            if palette_changed:
                self._write_cgb_palette_byte(
                    self.cgb_obj_palette_data,
                    self.cgb_obj_palette_rgb,
                    palette_offset,
                    value,
                )
                self.cgb_obj_palette_generation += 1
                self.gpu.invalidate_cgb_obj_palette_cache(palette_number)
            self.memory.write_byte(address, value)
            if self.cgb_obj_palette_index & 0x80:
                self.cgb_obj_palette_index = (
                    (self.cgb_obj_palette_index & 0x80)
                    | ((self.cgb_obj_palette_index + 1) & 0x3F)
                )
                self.memory.write_byte(0xFF6A, self.cgb_obj_palette_index)
            return

        if self.cgb_mode and address == 0xFF70:
            bank = value & 0x07
            self._select_cgb_wram_bank(bank or 1)
            self.memory.write_byte(address, 0xF8 | bank)
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

        if address == 0xFF40:
            self.gpu.write_lcdc(value)
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

        if self.cgb_mode and 0x8000 <= address <= 0x9FFF:
            if self.gpu.diagnostics_enabled:
                diagnostics = self.gpu.diagnostics
                diagnostics['cgb_vram_writes'] = (
                    diagnostics.get('cgb_vram_writes', 0) + 1
                )
                mode_key = f"cgb_vram_writes_mode{self.gpu.linemode}"
                diagnostics[mode_key] = diagnostics.get(mode_key, 0) + 1
                if address <= 0x97FF:
                    diagnostics['cgb_tile_data_writes'] = (
                        diagnostics.get('cgb_tile_data_writes', 0) + 1
                    )
                else:
                    diagnostics['cgb_tilemap_writes'] = (
                        diagnostics.get('cgb_tilemap_writes', 0) + 1
                    )
            if self.raw_memory[0xFF4F] & 0x01:
                offset = address - 0x8000
                if self.cgb_vram_bank1[offset] == value:
                    return
                self.cgb_vram_bank1[offset] = value
                if address <= 0x97FF:
                    self.gpu.update_tile(address, value, bank=1)
            else:
                if self.raw_memory[address] == value:
                    return
                self.memory.write_byte(address, value)
                if address <= 0x97FF:
                    self.gpu.update_tile(address, value, bank=0)
            return

        if self.cgb_mode and 0xD000 <= address <= 0xDFFF:
            offset = address - 0xD000
            self.raw_memory[address] = value
            if offset < 0x0E00:
                self.raw_memory[0xF000 + offset] = value
            self.cgb_wram_banks[self.cgb_wram_bank - 1][offset] = value
            return

        if self.cgb_mode and 0xF000 <= address <= 0xFDFF:
            offset = address - 0xF000
            self.raw_memory[0xD000 + offset] = value
            self.raw_memory[address] = value
            self.cgb_wram_banks[self.cgb_wram_bank - 1][offset] = value
            return

        if 0x8000 <= address <= 0x9FFF and self.raw_memory[address] == value:
            return
        self.memory.write_byte(address, value)
        if 0x8000 <= address <= 0x97FF:     # VRAM tile area write
            self.gpu.update_tile(address, value, bank=0)
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
                if cartridge.has_mbc2:
                    return cartridge.read(address)
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

        if self.cgb_mode and 0x8000 <= address <= 0x9FFF:
            if self.raw_memory[0xFF4F] & 0x01:
                return self.cgb_vram_bank1[address - 0x8000]
            return self.raw_memory[address]

        if self.cgb_mode and 0xD000 <= address <= 0xDFFF:
            return self.raw_memory[address]

        if self.cgb_mode and 0xF000 <= address <= 0xFDFF:
            return self.raw_memory[0xD000 + (address - 0xF000)]

        if (
            address == 0xFF44
            and self.memory.gb_doctor_test_mode
        ):
            return 0x90

        if address == 0xFF00:
            return self.joypad.read()

        if self.cgb_mode and address == 0xFF69:
            return self.cgb_bg_palette_data[self.cgb_bg_palette_index & 0x3F]

        if self.cgb_mode and address == 0xFF6B:
            return self.cgb_obj_palette_data[self.cgb_obj_palette_index & 0x3F]

        return self.raw_memory[address]

    def _select_cgb_wram_bank(self, bank):
        """Mirror the selected CGB WRAM bank into raw memory D000-DFFF."""
        if bank == self.cgb_wram_bank:
            return
        old = self.cgb_wram_bank - 1
        self.cgb_wram_banks[old][:] = self.raw_memory[0xD000:0xE000]
        self.cgb_wram_bank = bank
        selected = self.cgb_wram_banks[bank - 1]
        self.raw_memory[0xD000:0xE000] = array.array('B', selected)
        self.raw_memory[0xF000:0xFE00] = array.array('B', selected[:0x0E00])

    @staticmethod
    def _refresh_cgb_palette_rgb(raw_palette, decoded_palette):
        for palette in range(8):
            for color_index in range(4):
                offset = palette * 8 + color_index * 2
                color = raw_palette[offset] | (raw_palette[offset + 1] << 8)
                red = color & 0x1F
                green = (color >> 5) & 0x1F
                blue = (color >> 10) & 0x1F
                decoded_palette[palette][color_index] = (
                    (red << 3) | (red >> 2),
                    (green << 3) | (green >> 2),
                    (blue << 3) | (blue >> 2),
                )

    @staticmethod
    def _write_cgb_palette_byte(raw_palette, decoded_palette, offset, value):
        raw_palette[offset] = value
        palette = offset >> 3
        color_index = (offset >> 1) & 0x03
        color_offset = palette * 8 + color_index * 2
        color = raw_palette[color_offset] | (raw_palette[color_offset + 1] << 8)
        red = color & 0x1F
        green = (color >> 5) & 0x1F
        blue = (color >> 10) & 0x1F
        decoded_palette[palette][color_index] = (
            (red << 3) | (red >> 2),
            (green << 3) | (green >> 2),
            (blue << 3) | (blue >> 2),
        )

    def _cgb_dma_transfer(self, control):
        """Perform a first-pass CGB VRAM DMA transfer immediately."""
        source = (
            (self.raw_memory[0xFF51] << 8)
            | (self.raw_memory[0xFF52] & 0xF0)
        ) & 0xFFF0
        destination = (
            0x8000
            | ((self.raw_memory[0xFF53] & 0x1F) << 8)
            | (self.raw_memory[0xFF54] & 0xF0)
        )
        length = ((control & 0x7F) + 1) * 0x10
        for offset in range(length):
            self.write_byte(
                0x8000 | ((destination + offset) & 0x1FFF),
                self.read_byte((source + offset) & 0xFFFF),
            )
        self.memory.write_byte(0xFF55, 0xFF)

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
        if 0xC000 <= source and source + 0xA0 <= 0xFE00:
            self.raw_memory[0xFE00:0xFEA0] = self.raw_memory[source:source + 0xA0]
        else:
            values = [self.read_byte(source + offset) for offset in range(0xA0)]
            self.raw_memory[0xFE00:0xFEA0] = array.array('B', values)
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
