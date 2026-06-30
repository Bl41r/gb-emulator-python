"""Game Boy cartridge ROM, external RAM, and memory bank controllers."""


ROM_ONLY_TYPES = {0x00, 0x08, 0x09}
MBC1_TYPES = {0x01, 0x02, 0x03}
MBC5_TYPES = {0x19, 0x1A, 0x1B, 0x1C, 0x1D, 0x1E}
MBC5_RUMBLE_TYPES = {0x1C, 0x1D, 0x1E}
SUPPORTED_TYPES = ROM_ONLY_TYPES | MBC1_TYPES | MBC5_TYPES

CARTRIDGE_TYPE_NAMES = {
    0x00: "ROM ONLY",
    0x01: "MBC1",
    0x02: "MBC1+RAM",
    0x03: "MBC1+RAM+BATTERY",
    0x08: "ROM+RAM",
    0x09: "ROM+RAM+BATTERY",
    0x19: "MBC5",
    0x1A: "MBC5+RAM",
    0x1B: "MBC5+RAM+BATTERY",
    0x1C: "MBC5+RUMBLE",
    0x1D: "MBC5+RUMBLE+RAM",
    0x1E: "MBC5+RUMBLE+RAM+BATTERY",
}

RAM_SIZE_BYTES = {
    0x00: 0,
    0x01: 2 * 1024,
    0x02: 8 * 1024,
    0x03: 32 * 1024,
    0x04: 128 * 1024,
    0x05: 64 * 1024,
}


class Cartridge:
    """A loaded cartridge with ROM-only, MBC1, or MBC5 translation."""

    ROM_BANK_SIZE = 0x4000
    RAM_BANK_SIZE = 0x2000

    def __init__(self, rom):
        if len(rom) < 0x150:
            raise ValueError("ROM is too small to contain a cartridge header")

        self.rom = bytes(rom)
        self.cartridge_type = self.rom[0x0147]
        self.rom_size_code = self.rom[0x0148]
        self.ram_size_code = self.rom[0x0149]
        self.has_mbc1 = self.cartridge_type in MBC1_TYPES
        self.has_mbc5 = self.cartridge_type in MBC5_TYPES
        self.has_mbc5_rumble = self.cartridge_type in MBC5_RUMBLE_TYPES
        self.is_rom_only_type = self.cartridge_type in ROM_ONLY_TYPES

        if self.cartridge_type not in SUPPORTED_TYPES:
            raise NotImplementedError(
                "cartridge type 0x{:02X} is not supported".format(
                    self.cartridge_type
                )
            )

        self.rom_bank_count = max(
            1,
            (len(self.rom) + self.ROM_BANK_SIZE - 1)
            // self.ROM_BANK_SIZE,
        )
        ram_size = RAM_SIZE_BYTES.get(self.ram_size_code)
        if ram_size is None:
            raise ValueError(
                "unknown cartridge RAM size code 0x{:02X}".format(
                    self.ram_size_code
                )
            )
        self.ram = bytearray(ram_size)

        self.ram_enabled = self.cartridge_type in {0x08, 0x09}
        self.rom_bank = 1
        self.mbc5_rom_bank_high = 0
        self.secondary_bank = 0
        self.banking_mode = 0

    @property
    def type_name(self):
        return CARTRIDGE_TYPE_NAMES[self.cartridge_type]

    @property
    def title(self):
        raw_title = self.rom[0x0134:0x0144]
        return raw_title.split(b"\x00", 1)[0].decode("ascii", errors="replace")

    @property
    def is_mbc1(self):
        return self.has_mbc1

    @property
    def is_mbc5(self):
        return self.has_mbc5

    def read(self, address):
        """Read a cartridge-mapped byte."""
        if self.is_rom_only_type:
            if 0x0000 <= address <= 0x7FFF:
                return self.rom[address] if address < len(self.rom) else 0xFF

            if 0xA000 <= address <= 0xBFFF:
                if not self.ram or not self.ram_enabled:
                    return 0xFF
                offset = address - 0xA000
                return self.ram[offset] if offset < len(self.ram) else 0xFF

            raise ValueError(
                "address 0x{:04X} is not cartridge-mapped".format(address)
            )

        if 0x0000 <= address <= 0x3FFF:
            bank = (
                self.secondary_bank << 5
                if self.has_mbc1 and self.banking_mode
                else 0
            )
            return self._read_rom_bank(bank, address)

        if 0x4000 <= address <= 0x7FFF:
            bank = self.rom_bank
            if self.has_mbc1:
                bank |= self.secondary_bank << 5
            elif self.has_mbc5:
                bank |= self.mbc5_rom_bank_high << 8
            return self._read_rom_bank(bank, address - 0x4000)

        if 0xA000 <= address <= 0xBFFF:
            if not self.ram or not self.ram_enabled:
                return 0xFF
            bank = (
                self._active_ram_bank()
            )
            offset = bank * self.RAM_BANK_SIZE + (address - 0xA000)
            return self.ram[offset] if offset < len(self.ram) else 0xFF

        raise ValueError(
            "address 0x{:04X} is not cartridge-mapped".format(address)
        )

    def write(self, address, value):
        """Write external RAM or an MBC control register."""
        value &= 0xFF

        if 0xA000 <= address <= 0xBFFF:
            if not self.ram or not self.ram_enabled:
                return
            bank = (
                self._active_ram_bank()
            )
            offset = bank * self.RAM_BANK_SIZE + (address - 0xA000)
            if offset < len(self.ram):
                self.ram[offset] = value
            return

        if not (self.has_mbc1 or self.has_mbc5):
            return

        if self.has_mbc5:
            self._write_mbc5_control(address, value)
        elif 0x0000 <= address <= 0x1FFF:
            self.ram_enabled = (value & 0x0F) == 0x0A
        elif 0x2000 <= address <= 0x3FFF:
            self.rom_bank = value & 0x1F
            if self.rom_bank == 0:
                self.rom_bank = 1
        elif 0x4000 <= address <= 0x5FFF:
            self.secondary_bank = value & 0x03
        elif 0x6000 <= address <= 0x7FFF:
            self.banking_mode = value & 0x01

    def _active_ram_bank(self):
        if self.has_mbc5:
            if self.has_mbc5_rumble:
                return self.secondary_bank & 0x07
            return self.secondary_bank & 0x0F
        if self.has_mbc1 and self.banking_mode:
            return self.secondary_bank
        return 0

    def _write_mbc5_control(self, address, value):
        if 0x0000 <= address <= 0x1FFF:
            self.ram_enabled = (value & 0x0F) == 0x0A
        elif 0x2000 <= address <= 0x2FFF:
            self.rom_bank = value
        elif 0x3000 <= address <= 0x3FFF:
            self.mbc5_rom_bank_high = value & 0x01
        elif 0x4000 <= address <= 0x5FFF:
            self.secondary_bank = value & (0x07 if self.has_mbc5_rumble else 0x0F)

    def _read_rom_bank(self, bank, offset):
        bank %= self.rom_bank_count
        rom_offset = bank * self.ROM_BANK_SIZE + offset
        return self.rom[rom_offset] if rom_offset < len(self.rom) else 0xFF
