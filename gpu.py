"""GPU module.

The GameBoy's tiled graphics system operates with tiles of 8x8 pixels, and
256 unique tiles can be used in a map; there are two maps of 32x32 tiles that
can be held in memory, and one of them can be used for the display at a time.
There is space in the GameBoy memory for 384 tiles, so half of them are shared
between the maps: one map uses tile numbers from 0 to 255, and the other uses
numbers between -128 and 127 for its tiles.


Region  Usage
8000-87FF   Tile set #1: tiles 0-127
8800-8FFF   Tile set #1: tiles 128-255
            Tile set #0: tiles -1 to -128
9000-97FF   Tile set #0: tiles 0-127
9800-9BFF   Tile map #0
9C00-9FFF   Tile map #1

The background map is 32x32 tiles; this comes to 256 by 256 pixels. The
display of the GameBoy is 160x144 pixels, so there's scope for the background
o be moved relative to the screen. The GPU achieves this by defining a
point in the background that corresponds to the top-left of the screen:
by moving this point between frames, the background is made to scroll on
the screen. For this reason, the definition of the top-left corner is held
by two GPU registers: Scroll X and Scroll Y.

Palettes
Each pixel is two bits.
Value   Pixel       Emulated colour
0       Off         [255, 255, 255]
1       33% on      [192, 192, 192]
2       66% on      [96, 96, 96]
3       On          [0, 0, 0]

These bits are read by the GPU when the tile is referenced in the map, run
through the palette and pushed to screen. The hardware of the GPU is wired
such that one whole row of the tile is accessible at the same time, and the
pixels are cycled through by running up the bits. The only issue with this
is that one row of the tile is two bytes: from this results the slightly
convoluted scheme for storage of the bits, where each pixel's low bit is
held in one byte, and the high bit in the other byte.
"""
import numpy as np

DMG_SHADES = (255, 192, 96, 0)
DMG_PALETTES = tuple(
    tuple(DMG_SHADES[(palette >> (index * 2)) & 0x03] for index in range(4))
    for palette in range(256)
)
TILE_ROW_PIXELS = tuple(
    bytes((code >> shift) & 0x03 for shift in range(14, -1, -2))
    for code in range(0x10000)
)
GPU_LCDC = 0xFF40
GPU_STAT = 0xFF41
GPU_SCY = 0xFF42
GPU_SCX = 0xFF43
GPU_LY = 0xFF44
GPU_LYC = 0xFF45
GPU_BGP = 0xFF47


class GbGpu(object):
    """GPU unit for the gameboy."""

    def __init__(self):
        """Init."""
        self._line = 0
        self._curscan = 0
        self._mode_clock = 0
        self.frame_ready = False
        self.screen_data = bytearray([255] * (160 * 144 * 4))
        self.screen_buffer = np.frombuffer(
            self.screen_data,
            dtype=np.uint8,
        ).reshape((144, 160, 4))
        self.screen_rgb = self.screen_buffer[:, :, :3]
        self.tile_set = self._create_tile_set()
        self.tile_row_codes = self._create_tile_row_codes()
        self._tile_row_rgba_cache = [None] * 256
        self.sys_interface = None    # Set after interface instantiated
        self.register_map = {
            'lcd_gpu_ctrl': 0xFF40,
            'stat': 0xFF41,
            'scroll_y': 0xFF42,
            'scroll_x': 0xFF43,
            'curr_line': 0xFF44,
            'raster': 0xFF45,
            'oam_dma': 0xFF46,
            'bgrnd_palette': 0xFF47
        }
        self.linemode = 0
        self._scanrow = bytearray(160)
        self._empty_scanrow = bytes(160)
        self._sprite_claimed = bytearray(160)
        self._sprite_objects = []
        self._white_scanline = bytes([255] * (160 * 4))
        self._palette = {'obj0': [], 'obj1': []}
        self._palette['bg'] = [
            255,  # white
            192,  # light gray
            96,   # dark gray
            0     # black
        ]

        self.screen = {
            'data': self.screen_data,
            'buffer': self.screen_buffer,
            'rgb': self.screen_rgb,
            'width': 160,
            'heaight': 144
        }

    def step(self, m):
        """Perform one step."""
        self._mode_clock += m
        linemode = self.linemode
        if linemode == 0:
            if self._mode_clock >= 204:
                memory = self.sys_interface.raw_memory
                self._mode_clock -= 204
                curr_line = memory[GPU_LY]
                memory[GPU_LY] = (curr_line + 1) & 0xFF

                if curr_line == 143:
                    self.linemode = 1  # enter V-Blank
                    self.frame_ready = True
                    memory[0xFF0F] |= 0x01  # Set V-Blank flag
                else:
                    self.linemode = 2

                self._update_stat_register()
        elif linemode == 1:
            if self._mode_clock >= 456:
                memory = self.sys_interface.raw_memory
                self._mode_clock -= 456
                memory[GPU_LY] = (memory[GPU_LY] + 1) & 0xFF

                if memory[GPU_LY] > 153:
                    memory[GPU_LY] = 0  # reset LY
                    self.linemode = 2   # Switch to OAM mode
                    self._curscan = 0   # Reset scanline render state

                self._update_stat_register()
        elif linemode == 2:
            if self._mode_clock >= 80:
                self._mode_clock -= 80
                self.linemode = 3   # Switch to VRAM mode
                self._update_stat_register()
        else:
            if self._mode_clock >= 172:
                self._mode_clock -= 172
                self.linemode = 0   # Switch to H-Blank mode
                self._update_stat_register()
                self._renderscan()

    def consume_frame_ready(self):
        """Return whether a frame completed, clearing the notification."""
        if not self.frame_ready:
            return False
        self.frame_ready = False
        return True

    def update_tile(self, addr, val):
        """Update a tile.

        Called when a value written to VRAM, and updates the
        internal tile set.
        """
        base_addr = addr & 0xFFFE
        vram_offset = base_addr - 0x8000
        tile_index = (vram_offset >> 4) & 511
        row = (vram_offset >> 1) & 7

        memory = self.sys_interface.memory.memory
        byte1 = memory[base_addr]
        byte2 = memory[base_addr + 1]

        row_pixels = self.tile_set[tile_index][row]
        row_code = 0
        for x in range(8):
            bit = 1 << (7 - x)
            lo = 1 if byte1 & bit else 0
            hi = 2 if byte2 & bit else 0
            color_id = lo + hi
            row_pixels[x] = color_id
            row_code = (row_code << 2) | color_id
        self.tile_row_codes[tile_index][row] = row_code

        # print(f"Tile update: tile={tile_index}, row={row}, data={self.tile_set[tile_index][row]}")

    def get_gpu_ctrl_reg(self, reg_name):
        """Return on/off (bit value or 0) for the LCD/GPU control register bit.

        Bit     Function               When 0  When 1
        0       Background: on/off      Off     On
        1       Sprites: on/off         Off     On
        2       Sprites: size (pixels)  8x8     8x16
        3       Background: tile map    #0      #1
        4       Background: tile set    #0      #1
        5       Window: on/off          Off     On
        6       Window: tile map        #0      #1
        7       Display: on/off         Off     On
        """
        register_value = self.sys_interface.read_byte(
            self.register_map['lcd_gpu_ctrl'])

        if reg_name == 'bgrnd':
            return register_value & 0x01
        elif reg_name == 'sprites':
            return register_value & 0x02
        elif reg_name == 'sprites_size':
            return register_value & 0x04
        elif reg_name == 'bgrnd_tilemap':
            return register_value & 0x08
        elif reg_name == 'bgrnd_tileset':
            return register_value & 0x10
        elif reg_name == 'window':
            return register_value & 0x20
        elif reg_name == 'window_tilemap':
            return register_value & 0x40
        elif reg_name == 'display':
            return register_value & 0x80
        else:
            raise KeyError(reg_name + ' does not exist!')

    @staticmethod
    def _create_tile_set():
        return [
            [
                bytearray(8), bytearray(8), bytearray(8), bytearray(8),
                bytearray(8), bytearray(8), bytearray(8), bytearray(8)
            ] for i in range(512)
        ]

    @staticmethod
    def _create_tile_row_codes():
        return [[0] * 8 for i in range(512)]

    def reset_screen(self):
        """Reset screen to white."""
        self.screen_buffer.fill(255)

    def set_system_interface(self, sys_interface):
        """Set the system interface."""
        self.sys_interface = sys_interface

    def write_reg(self, register_name, val):
        """Write a byte to memory."""
        address = self.register_map[register_name]
        self.sys_interface.write_byte(address, val)

    def read_reg(self, register_name):
        """Read a register from mem."""
        return self.sys_interface.read_byte(self.register_map[register_name])

    def _update_stat_register(self):
        """Use whenever linemode is set"""
        memory = self.sys_interface.raw_memory
        stat = memory[GPU_STAT] & 0b11111000  # Clear mode + coincidence flag

        # Set current mode (bits 0–1)
        stat |= self.linemode & 0b11

        # Bit 2 is undocumented, usually set to 1
        stat |= 0b100

        # Coincidence flag (bit 3)
        if memory[GPU_LY] == memory[GPU_LYC]:
            stat |= 0b1000  # Bit 3: coincidence match

        memory[GPU_STAT] = stat

    def _renderscan(self):
        memory = self.sys_interface.raw_memory
        line = memory[GPU_LY]
        lcdc = memory[GPU_LCDC]

        if line >= 144 or not (lcdc & 0x80):
            return

        if lcdc & 0x01:
            self._render_background_scanline(line, lcdc)
        else:
            self._scanrow[:] = self._empty_scanrow
            offset = line * 160 * 4
            self.screen_data[offset:offset + 160 * 4] = self._white_scanline

        if lcdc & 0x02:
            self._render_sprite_scanline(line, lcdc)

    def _render_background_scanline(self, line, lcdc):
        """Render the background and retain its color IDs for OBJ priority."""
        memory = self.sys_interface.raw_memory
        scroll_y = memory[GPU_SCY]
        scroll_x = memory[GPU_SCX]
        y = (line + scroll_y) & 0xFF
        tile_row = y >> 3
        tile_pixel_row = y & 7
        map_base = 0x9C00 if (lcdc & 0x08) else 0x9800
        signed_addressing = not (lcdc & 0x10)
        palette_value = memory[GPU_BGP]
        screen_data = self.screen_data
        screen_offset = line * 160 * 4
        scanrow = self._scanrow
        tile_row_codes = self.tile_row_codes
        row_rgba_cache = self._tile_row_rgba_cache[palette_value]
        if row_rgba_cache is None:
            row_rgba_cache = [None] * 0x10000
            self._tile_row_rgba_cache[palette_value] = row_rgba_cache
        palette = DMG_PALETTES[palette_value]

        x = 0
        while x < 160:
            x_scrolled = (x + scroll_x) & 0xFF
            tile_col = x_scrolled >> 3
            tile_pixel_col = x_scrolled & 7

            tile_addr = map_base + tile_row * 32 + tile_col
            tile_id = memory[tile_addr]

            if signed_addressing:
                tile_id = tile_id - 256 if tile_id > 127 else tile_id
                tile_index = 256 + tile_id
            else:
                tile_index = tile_id

            row_code = tile_row_codes[tile_index][tile_pixel_row]
            run = 8 - tile_pixel_col
            remaining = 160 - x
            if run > remaining:
                run = remaining
            end = tile_pixel_col + run
            pixels = TILE_ROW_PIXELS[row_code]
            rgba = row_rgba_cache[row_code]
            if rgba is None:
                row = bytearray(8 * 4)
                rgba_offset = 0
                for color_index in pixels:
                    color = palette[color_index]
                    row[rgba_offset] = color
                    row[rgba_offset + 1] = color
                    row[rgba_offset + 2] = color
                    row[rgba_offset + 3] = 255
                    rgba_offset += 4
                rgba = bytes(row)
                row_rgba_cache[row_code] = rgba

            scanrow[x:x + run] = pixels[tile_pixel_col:end]
            offset = screen_offset + x * 4
            screen_data[offset:offset + run * 4] = rgba[tile_pixel_col * 4:end * 4]
            x += run

    def _render_sprite_scanline(self, line, lcdc):
        """Composite the DMG's first ten eligible objects onto one scanline."""
        memory = self.sys_interface.raw_memory
        height = 16 if (lcdc & 0x04) else 8
        objects = self._sprite_objects
        objects.clear()

        for index in range(40):
            base = 0xFE00 + index * 4
            object_y = memory[base] - 16
            if object_y <= line < object_y + height:
                objects.append((
                    memory[base + 1],
                    index,
                    object_y,
                    memory[base + 2],
                    memory[base + 3],
                ))
                if len(objects) == 10:
                    break

        # On DMG, smaller X wins; equal X uses the earlier OAM entry.
        objects.sort(key=lambda obj: (obj[0], obj[1]))
        claimed = self._sprite_claimed
        claimed[:] = self._empty_scanrow
        screen_data = self.screen_data
        screen_offset = line * 160 * 4
        obj0_palette = DMG_PALETTES[memory[0xFF48]]
        obj1_palette = DMG_PALETTES[memory[0xFF49]]

        for object_x, _, object_y, tile_index, attributes in objects:
            row = line - object_y
            if attributes & 0x40:
                row = height - 1 - row

            if height == 16:
                tile_index = (tile_index & 0xFE) + (row >> 3)
                row &= 7

            tile_row = self.tile_set[tile_index][row]
            palette = obj1_palette if attributes & 0x10 else obj0_palette

            for pixel in range(8):
                screen_x = object_x - 8 + pixel
                if not 0 <= screen_x < 160 or claimed[screen_x]:
                    continue

                tile_x = 7 - pixel if attributes & 0x20 else pixel
                color_index = tile_row[tile_x]
                if color_index == 0:
                    continue

                claimed[screen_x] = True
                if attributes & 0x80 and self._scanrow[screen_x] != 0:
                    continue

                color = palette[color_index]
                offset = screen_offset + screen_x * 4
                screen_data[offset] = color
                screen_data[offset + 1] = color
                screen_data[offset + 2] = color
                screen_data[offset + 3] = 255

    @staticmethod
    def _palette_lookup(palette):
        """Return the four grayscale shades selected by a DMG palette."""
        return DMG_PALETTES[palette]

    @staticmethod
    def _palette_color(palette, color_index):
        """Map a two-bit color ID through a DMG palette register."""
        return DMG_SHADES[(palette >> (color_index * 2)) & 0x03]

    def _write_pixel(self, line, x, color):
        offset = (line * 160 + x) * 4
        self.screen_data[offset] = color
        self.screen_data[offset + 1] = color
        self.screen_data[offset + 2] = color
        self.screen_data[offset + 3] = 255

    def _get_mapbase(self):
        """Get mapbase."""
        return 0x9C00 if self.get_gpu_ctrl_reg('bgrnd_tilemap') else 0x9800

    def lcdc(self):
        return self.sys_interface.read_byte(0xFF40)

    def get_tile_map_base(self):
        """Returns correct BG tile map base from LCDC."""
        return 0x9C00 if (self.lcdc() & 0x08) else 0x9800

    def get_tile_data_base(self):
        """Returns correct tile data addressing mode."""
        return 0x8000 if (self.lcdc() & 0x10) else 0x8800

    def is_display_enabled(self):
        """Checks if LCD display is enabled."""
        return (self.lcdc() & 0x80) != 0

    def is_background_enabled(self):
        """Checks if BG is enabled."""
        return (self.lcdc() & 0x01) != 0
