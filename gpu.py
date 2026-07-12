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
import time

DMG_SHADES = (255, 192, 96, 0)
DMG_PALETTES = tuple(
    tuple(DMG_SHADES[(palette >> (index * 2)) & 0x03] for index in range(4))
    for palette in range(256)
)


def _cgb_rgb555_to_rgb(color):
    """Convert a CGB 15-bit BGR color to 8-bit RGB components."""
    red = color & 0x1F
    green = (color >> 5) & 0x1F
    blue = (color >> 10) & 0x1F
    return (
        (red << 3) | (red >> 2),
        (green << 3) | (green >> 2),
        (blue << 3) | (blue >> 2),
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
GPU_WY = 0xFF4A
GPU_WX = 0xFF4B
GPU_MODE_CYCLES = (204, 456, 80, 172)
STAT_MODE_IRQ_MASKS = (0x08, 0x10, 0x20, 0x00)


class GbGpu(object):
    """GPU unit for the gameboy."""

    def __init__(self):
        """Init."""
        self._line = 0
        self._curscan = 0
        self._mode_clock = 0
        self._window_line = 0
        self._stat_irq_line = False
        self._line153_ly_reset = False
        self._scanline_scroll_x = 0
        self._scanline_scroll_y = 0
        self.last_frame_scroll_x = bytearray(144)
        self.last_frame_scroll_y = bytearray(144)
        self.cgb_mode = False
        self.diagnostics_enabled = False
        self.diagnostics = {}
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
        self._cgb_bg_row_cache = [{} for _ in range(16)]
        self._cgb_bg_palette0_row_cache = {}
        self._cgb_obj_row_cache = [{} for _ in range(16)]
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
        self._bg_priority = bytearray(160)
        self._bg_priority_dirty = False
        self._empty_scanrow = bytes(160)
        self._priority_runs = tuple(b"\x01" * i for i in range(9))
        self._sprite_claimed = bytearray(160)
        self._sprite_scanlines = [[] for _ in range(144)]
        self._sprite_cache_dirty = True
        self._sprite_cache_height = 0
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
        if not (self.sys_interface.raw_memory[GPU_LCDC] & 0x80):
            return

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
            memory = self.sys_interface.raw_memory
            if (
                memory[GPU_LY] == 153
                and not self._line153_ly_reset
                and self._mode_clock >= 4
            ):
                # On DMG hardware LY reads as 0 after the first four dots of
                # VBlank line 153, before mode 2 for scanline 0 begins.
                memory[GPU_LY] = 0
                self._line153_ly_reset = True
                # Do not latch/request a new STAT edge for this synthetic LY=0
                # window. CGB raster code that targets the first visible band
                # can otherwise run during VBlank and leave line 0 using stale
                # scroll until the real visible-frame split catches up.
                self._update_stat_register(request_irq=False)

            if self._mode_clock >= 456:
                self._mode_clock -= 456
                if self._line153_ly_reset:
                    self._line153_ly_reset = False
                    self.linemode = 2   # Switch to OAM mode
                    self._curscan = 0   # Reset scanline render state
                    self._window_line = 0
                else:
                    memory[GPU_LY] = (memory[GPU_LY] + 1) & 0xFF

                self._update_stat_register()
        elif linemode == 2:
            if self._mode_clock >= 80:
                self._mode_clock -= 80
                memory = self.sys_interface.raw_memory
                self._scanline_scroll_x = memory[GPU_SCX]
                self._scanline_scroll_y = memory[GPU_SCY]
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

    def m_cycles_until_mode_transition(self):
        """Return M-cycles remaining before the current PPU mode ends."""
        if not (self.sys_interface.raw_memory[GPU_LCDC] & 0x80):
            return 0x10000

        remaining = GPU_MODE_CYCLES[self.linemode] - self._mode_clock
        if (
            self.linemode == 1
            and not self._line153_ly_reset
            and self.sys_interface.raw_memory[GPU_LY] == 153
        ):
            remaining = min(remaining, 4 - self._mode_clock)
        return max(1, remaining // 4)

    def read_ly_at_cpu_bus(self):
        """Return LY as sampled during the final cycle of an LDH read."""
        memory = self.sys_interface.raw_memory
        line = memory[GPU_LY]
        if not (memory[GPU_LCDC] & 0x80):
            return 0

        # LDH A,(a8) fetches its opcode and operand before sampling the I/O
        # register. Account for those first two M-cycles without advancing
        # the PPU early or splitting every instruction into individual dots.
        mode_clock = self._mode_clock + 8
        if self.linemode == 0 and mode_clock >= 204:
            return (line + 1) & 0xFF
        if self.linemode == 1:
            if line == 153 and not self._line153_ly_reset and mode_clock >= 4:
                return 0
            if mode_clock >= 456 and not self._line153_ly_reset:
                return (line + 1) & 0xFF
        return line

    def update_tile(self, addr, val, bank=0):
        """Update a tile.

        Called when a value written to VRAM, and updates the
        internal tile set.
        """
        base_addr = addr & 0xFFFE
        vram_offset = base_addr - 0x8000
        tile_index = ((vram_offset >> 4) & 511) + (512 if bank else 0)
        row = (vram_offset >> 1) & 7

        if bank:
            vram = self.sys_interface.cgb_vram_bank1
            byte1 = vram[vram_offset]
            byte2 = vram[vram_offset + 1]
        else:
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
            ] for i in range(1024)
        ]

    @staticmethod
    def _create_tile_row_codes():
        return [[0] * 8 for i in range(1024)]

    def reset_screen(self):
        """Reset screen to white."""
        self.screen_buffer.fill(255)

    def invalidate_sprite_cache(self):
        """Mark cached per-scanline OAM selection for rebuilding."""
        self._sprite_cache_dirty = True

    def invalidate_cgb_bg_palette_cache(self, palette_number=None):
        """Drop cached CGB BG/window rows after a palette RAM write."""
        if self.diagnostics_enabled:
            diagnostics = self.diagnostics
            diagnostics['cgb_bg_palette_invalidations'] = (
                diagnostics.get('cgb_bg_palette_invalidations', 0) + 1
            )
        if palette_number is not None:
            self._cgb_bg_row_cache[palette_number].clear()
            self._cgb_bg_row_cache[palette_number + 8].clear()
            if palette_number == 0:
                self._cgb_bg_palette0_row_cache.clear()
            return
        for cache in self._cgb_bg_row_cache:
            cache.clear()
        self._cgb_bg_palette0_row_cache.clear()

    def invalidate_cgb_obj_palette_cache(self, palette_number=None):
        """Drop cached CGB OBJ rows after a palette RAM write."""
        if self.diagnostics_enabled:
            diagnostics = self.diagnostics
            diagnostics['cgb_obj_palette_invalidations'] = (
                diagnostics.get('cgb_obj_palette_invalidations', 0) + 1
            )
        if palette_number is not None:
            self._cgb_obj_row_cache[palette_number].clear()
            self._cgb_obj_row_cache[palette_number + 8].clear()
            return
        for cache in self._cgb_obj_row_cache:
            cache.clear()

    def _rebuild_sprite_cache(self, height):
        """Cache the first ten OAM objects eligible for each visible line."""
        memory = self.sys_interface.raw_memory
        scanlines = self._sprite_scanlines
        for objects in scanlines:
            objects.clear()

        for index in range(40):
            base = 0xFE00 + index * 4
            object_y = memory[base] - 16
            first_line = max(0, object_y)
            end_line = min(144, object_y + height)
            if first_line >= end_line:
                continue

            obj = (
                memory[base + 1],
                index,
                object_y,
                memory[base + 2],
                memory[base + 3],
            )
            for line in range(first_line, end_line):
                if len(scanlines[line]) < 10:
                    scanlines[line].append(obj)

        for objects in scanlines:
            if len(objects) > 1:
                objects.sort()
        self._sprite_cache_dirty = False
        self._sprite_cache_height = height

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

    def write_stat(self, value):
        """Update writable STAT interrupt-enable bits."""
        memory = self.sys_interface.raw_memory
        memory[GPU_STAT] = (value & 0xF8) | (memory[GPU_STAT] & 0x07)
        self._update_stat_register()

    def write_lcdc(self, value):
        """Apply LCD enable and disable state transitions."""
        memory = self.sys_interface.raw_memory
        was_enabled = bool(memory[GPU_LCDC] & 0x80)
        is_enabled = bool(value & 0x80)
        memory[GPU_LCDC] = value

        if was_enabled == is_enabled:
            return

        self._mode_clock = 0
        self._curscan = 0
        self._window_line = 0
        self._line153_ly_reset = False
        memory[GPU_LY] = 0

        # Disabling the LCD immediately resets the PPU to mode 0. Enabling
        # it begins a new frame in the OAM-search phase for scanline zero.
        self.linemode = 2 if is_enabled else 0
        if not is_enabled:
            self.frame_ready = False
        self._update_stat_register()

    def write_lyc(self, value):
        """Update LYC and immediately refresh coincidence state."""
        self.sys_interface.raw_memory[GPU_LYC] = value
        self._update_stat_register()

    def _update_stat_register(self, request_irq=True):
        """Refresh mode/coincidence bits and raise STAT on a line edge."""
        memory = self.sys_interface.raw_memory
        linemode = self.linemode
        stat = memory[GPU_STAT] & 0xF8

        # Set current mode (bits 0–1)
        stat |= linemode & 0b11

        # Coincidence flag is read-only bit 2.
        if memory[GPU_LY] == memory[GPU_LYC]:
            stat |= 0x04

        memory[GPU_STAT] = stat
        if not request_irq:
            return
        irq_mask = STAT_MODE_IRQ_MASKS[linemode]
        if stat & 0x04:
            irq_mask |= 0x40
        irq_line = bool(memory[GPU_LCDC] & 0x80 and stat & irq_mask)
        if irq_line and not self._stat_irq_line:
            memory[0xFF0F] |= 0x02
        self._stat_irq_line = irq_line

    def _renderscan(self):
        memory = self.sys_interface.raw_memory
        line = memory[GPU_LY]
        lcdc = memory[GPU_LCDC]

        if line >= 144 or not (lcdc & 0x80):
            return
        scroll_x = self._scanline_scroll_x
        scroll_y = self._scanline_scroll_y
        self.last_frame_scroll_x[line] = scroll_x
        self.last_frame_scroll_y[line] = scroll_y

        window_visible = (
            lcdc & 0x21 == 0x21
            and line >= memory[GPU_WY]
            and memory[GPU_WX] <= 166
        )
        window_covers_scanline = window_visible and memory[GPU_WX] <= 7

        bg_enabled = bool(lcdc & 0x01) or self.cgb_mode
        if bg_enabled and not window_covers_scanline:
            self._render_background_scanline(
                line,
                lcdc,
                scroll_x,
                scroll_y,
            )
        elif not window_covers_scanline:
            self._scanrow[:] = self._empty_scanrow
            offset = line * 160 * 4
            self.screen_data[offset:offset + 160 * 4] = self._white_scanline

        if window_visible:
            self._render_window_scanline(
                line,
                lcdc,
                self._window_line,
            )
            self._window_line += 1

        if lcdc & 0x02:
            self._render_sprite_scanline(line, lcdc)

        if self.cgb_mode and line == 1 and (
            self.last_frame_scroll_x[0] != scroll_x
            or self.last_frame_scroll_y[0] != scroll_y
        ):
            self._repair_cgb_line0_scroll(lcdc, scroll_x, scroll_y)

    def _repair_cgb_line0_scroll(self, lcdc, scroll_x, scroll_y):
        """Re-render line 0 when our coarse STAT timing latches it too early.

        Some CGB raster effects set up the first visible line through a line-0
        STAT handler. This emulator advances CPU/PPU timing at instruction
        granularity, so that handler can land just after scanline 0 was drawn
        while still being early enough for scanline 1. Re-rendering only the
        top scanline with scanline 1's scroll avoids a visible one-pixel seam
        without changing the rest of the frame's raster splits.
        """
        original_priority = bytes(self._bg_priority)
        original_scanrow = bytes(self._scanrow)
        line = 0
        self._bg_priority[:] = self._empty_scanrow
        self._bg_priority_dirty = False
        self._render_cgb_background_scanline(line, lcdc, scroll_x, scroll_y)
        if lcdc & 0x02:
            self._render_cgb_sprite_scanline(line, lcdc)
        self.last_frame_scroll_x[line] = scroll_x
        self.last_frame_scroll_y[line] = scroll_y
        self._scanrow[:] = original_scanrow
        self._bg_priority[:] = original_priority
        self._bg_priority_dirty = True

    def _render_background_scanline(self, line, lcdc, scroll_x, scroll_y):
        """Render the background and retain its color IDs for OBJ priority."""
        if self.cgb_mode:
            self._render_cgb_background_scanline(line, lcdc, scroll_x, scroll_y)
            return

        memory = self.sys_interface.raw_memory
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
        map_row_base = map_base + tile_row * 32

        if not (scroll_x & 7):
            tile_col = scroll_x >> 3
            for x in range(0, 160, 8):
                tile_id = memory[map_row_base + tile_col]
                if signed_addressing:
                    tile_id = tile_id - 256 if tile_id > 127 else tile_id
                    tile_index = 256 + tile_id
                else:
                    tile_index = tile_id

                row_code = tile_row_codes[tile_index][tile_pixel_row]
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

                scanrow[x:x + 8] = pixels
                offset = screen_offset + x * 4
                screen_data[offset:offset + 32] = rgba
                tile_col = (tile_col + 1) & 31
            return

        x = 0
        tile_col = scroll_x >> 3
        tile_pixel_col = scroll_x & 7
        while x < 160:
            tile_addr = map_row_base + tile_col
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
            tile_col = (tile_col + 1) & 31
            tile_pixel_col = 0

    def _cgb_palette_color(self, palette_data, palette_number, color_index):
        return palette_data[palette_number][color_index]

    @staticmethod
    def _tile_index(tile_id, signed_addressing):
        if signed_addressing:
            tile_id = tile_id - 256 if tile_id > 127 else tile_id
            return 256 + tile_id
        return tile_id

    def _cgb_row_rgba(
        self,
        row_code,
        palette_data,
        palette_number,
        flipped,
        cache,
    ):
        cache = cache[palette_number + (8 if flipped else 0)]
        cached = cache.get(row_code)
        if cached is not None:
            if self.diagnostics_enabled:
                diagnostics = self.diagnostics
                diagnostics['cgb_row_cache_hits'] = (
                    diagnostics.get('cgb_row_cache_hits', 0) + 1
                )
            return cached
        if self.diagnostics_enabled:
            diagnostics = self.diagnostics
            diagnostics['cgb_row_cache_misses'] = (
                diagnostics.get('cgb_row_cache_misses', 0) + 1
            )

        pixels = TILE_ROW_PIXELS[row_code]
        if flipped:
            pixels = pixels[::-1]
        row = bytearray(8 * 4)
        rgba_offset = 0
        palette = palette_data[palette_number]
        for color_index in pixels:
            red, green, blue = palette[color_index]
            row[rgba_offset] = red
            row[rgba_offset + 1] = green
            row[rgba_offset + 2] = blue
            row[rgba_offset + 3] = 255
            rgba_offset += 4
        cached = (bytes(pixels), bytes(row))
        cache[row_code] = cached
        return cached

    def _cgb_unflipped_row_rgba(
        self,
        row_code,
        palette_data,
        palette_number,
        cache,
    ):
        cache = cache[palette_number]
        cached = cache.get(row_code)
        if cached is not None:
            if self.diagnostics_enabled:
                diagnostics = self.diagnostics
                diagnostics['cgb_row_cache_hits'] = (
                    diagnostics.get('cgb_row_cache_hits', 0) + 1
                )
            return cached
        if self.diagnostics_enabled:
            diagnostics = self.diagnostics
            diagnostics['cgb_row_cache_misses'] = (
                diagnostics.get('cgb_row_cache_misses', 0) + 1
            )

        pixels = TILE_ROW_PIXELS[row_code]
        row = bytearray(8 * 4)
        rgba_offset = 0
        palette = palette_data[palette_number]
        for color_index in pixels:
            red, green, blue = palette[color_index]
            row[rgba_offset] = red
            row[rgba_offset + 1] = green
            row[rgba_offset + 2] = blue
            row[rgba_offset + 3] = 255
            rgba_offset += 4
        cached = (pixels, bytes(row))
        cache[row_code] = cached
        return cached

    def _cgb_palette0_row_rgba(self, row_code, palette_data):
        cache = self._cgb_bg_palette0_row_cache
        cached = cache.get(row_code)
        if cached is not None:
            if self.diagnostics_enabled:
                diagnostics = self.diagnostics
                diagnostics['cgb_palette0_cache_hits'] = (
                    diagnostics.get('cgb_palette0_cache_hits', 0) + 1
                )
            return cached
        if self.diagnostics_enabled:
            diagnostics = self.diagnostics
            diagnostics['cgb_palette0_cache_misses'] = (
                diagnostics.get('cgb_palette0_cache_misses', 0) + 1
            )

        pixels = TILE_ROW_PIXELS[row_code]
        row = bytearray(8 * 4)
        rgba_offset = 0
        palette = palette_data[0]
        for color_index in pixels:
            red, green, blue = palette[color_index]
            row[rgba_offset] = red
            row[rgba_offset + 1] = green
            row[rgba_offset + 2] = blue
            row[rgba_offset + 3] = 255
            rgba_offset += 4
        cached = (pixels, bytes(row))
        cache[row_code] = cached
        return cached

    def _render_cgb_background_scanline(self, line, lcdc, scroll_x, scroll_y):
        """Render a CGB background scanline using bank-1 tile attributes."""
        diagnostics_enabled = self.diagnostics_enabled
        if diagnostics_enabled:
            start_seconds = time.perf_counter()
            diagnostics = self.diagnostics
        sys_interface = self.sys_interface
        memory = sys_interface.raw_memory
        attr_vram = sys_interface.cgb_vram_bank1
        palette_data = sys_interface.cgb_bg_palette_rgb
        row_cache = self._cgb_bg_row_cache
        y = (line + scroll_y) & 0xFF
        tile_row = y >> 3
        base_tile_pixel_row = y & 7
        map_base = 0x9C00 if (lcdc & 0x08) else 0x9800
        map_offset = map_base - 0x8000
        signed_addressing = not (lcdc & 0x10)
        screen_data = self.screen_data
        screen_offset = line * 160 * 4
        scanrow = self._scanrow
        priority = self._bg_priority
        priority_runs = self._priority_runs
        if self._bg_priority_dirty:
            priority[:] = self._empty_scanrow
            self._bg_priority_dirty = False
        tile_row_codes = self.tile_row_codes
        palette0_cache = self._cgb_bg_palette0_row_cache

        x = 0
        tile_col = scroll_x >> 3
        tile_pixel_col = scroll_x & 7
        map_row_offset = map_offset + tile_row * 32

        if tile_pixel_col == 0:
            priority_run = priority_runs[8]
            for x in range(0, 160, 8):
                map_index = map_row_offset + tile_col
                tile_id = memory[0x8000 + map_index]
                attributes = attr_vram[map_index]
                if diagnostics_enabled:
                    diagnostics['cgb_bg_tiles'] = (
                        diagnostics.get('cgb_bg_tiles', 0) + 1
                    )
                    if attributes == 0:
                        diagnostics['cgb_bg_attr_zero'] = (
                            diagnostics.get('cgb_bg_attr_zero', 0) + 1
                        )
                    else:
                        if not (attributes & 0xF8):
                            diagnostics['cgb_bg_attr_palette_only'] = (
                                diagnostics.get('cgb_bg_attr_palette_only', 0) + 1
                            )
                        if attributes & 0x08:
                            diagnostics['cgb_bg_attr_bank'] = (
                                diagnostics.get('cgb_bg_attr_bank', 0) + 1
                            )
                        if attributes & 0x20:
                            diagnostics['cgb_bg_attr_xflip'] = (
                                diagnostics.get('cgb_bg_attr_xflip', 0) + 1
                            )
                        if attributes & 0x40:
                            diagnostics['cgb_bg_attr_yflip'] = (
                                diagnostics.get('cgb_bg_attr_yflip', 0) + 1
                            )
                        if attributes & 0x80:
                            diagnostics['cgb_bg_attr_priority'] = (
                                diagnostics.get('cgb_bg_attr_priority', 0) + 1
                            )
                tile_pixel_row = base_tile_pixel_row
                if signed_addressing:
                    tile_index = 256 + (
                        tile_id - 256 if tile_id > 127 else tile_id
                    )
                else:
                    tile_index = tile_id
                if attributes and not (attributes & 0xF8):
                    row_code = tile_row_codes[tile_index][tile_pixel_row]
                    cache = row_cache[attributes]
                    try:
                        pixels, rgba = cache[row_code]
                        if diagnostics_enabled:
                            diagnostics['cgb_row_cache_hits'] = (
                                diagnostics.get('cgb_row_cache_hits', 0) + 1
                            )
                    except KeyError:
                        pixels, rgba = self._cgb_unflipped_row_rgba(
                            row_code,
                            palette_data,
                            attributes,
                            row_cache,
                        )
                elif attributes:
                    if attributes & 0x40:
                        tile_pixel_row = 7 - tile_pixel_row
                    if attributes & 0x08:
                        tile_index += 512
                    row_code = tile_row_codes[tile_index][tile_pixel_row]
                    pixels, rgba = self._cgb_row_rgba(
                        row_code,
                        palette_data,
                        attributes & 0x07,
                        bool(attributes & 0x20),
                        row_cache,
                    )
                    if attributes & 0x80:
                        priority[x:x + 8] = priority_run
                        self._bg_priority_dirty = True
                else:
                    row_code = tile_row_codes[tile_index][tile_pixel_row]
                    try:
                        pixels, rgba = palette0_cache[row_code]
                        if diagnostics_enabled:
                            diagnostics['cgb_palette0_cache_hits'] = (
                                diagnostics.get('cgb_palette0_cache_hits', 0) + 1
                            )
                    except KeyError:
                        pixels, rgba = self._cgb_palette0_row_rgba(
                            row_code,
                            palette_data,
                        )
                scanrow[x:x + 8] = pixels
                offset = screen_offset + x * 4
                screen_data[offset:offset + 32] = rgba
                tile_col = (tile_col + 1) & 31
            if diagnostics_enabled:
                diagnostics['cgb_bg_scanlines'] = (
                    diagnostics.get('cgb_bg_scanlines', 0) + 1
                )
                diagnostics['cgb_bg_seconds'] = (
                    diagnostics.get('cgb_bg_seconds', 0.0)
                    + time.perf_counter()
                    - start_seconds
                )
            return

        while x < 160:
            map_index = map_row_offset + tile_col
            tile_id = memory[0x8000 + map_index]
            attributes = attr_vram[map_index]
            if diagnostics_enabled:
                diagnostics['cgb_bg_tiles'] = (
                    diagnostics.get('cgb_bg_tiles', 0) + 1
                )
                if attributes == 0:
                    diagnostics['cgb_bg_attr_zero'] = (
                        diagnostics.get('cgb_bg_attr_zero', 0) + 1
                    )
                else:
                    if not (attributes & 0xF8):
                        diagnostics['cgb_bg_attr_palette_only'] = (
                            diagnostics.get('cgb_bg_attr_palette_only', 0) + 1
                        )
                    if attributes & 0x08:
                        diagnostics['cgb_bg_attr_bank'] = (
                            diagnostics.get('cgb_bg_attr_bank', 0) + 1
                        )
                    if attributes & 0x20:
                        diagnostics['cgb_bg_attr_xflip'] = (
                            diagnostics.get('cgb_bg_attr_xflip', 0) + 1
                        )
                    if attributes & 0x40:
                        diagnostics['cgb_bg_attr_yflip'] = (
                            diagnostics.get('cgb_bg_attr_yflip', 0) + 1
                        )
                    if attributes & 0x80:
                        diagnostics['cgb_bg_attr_priority'] = (
                            diagnostics.get('cgb_bg_attr_priority', 0) + 1
                        )
            tile_pixel_row = base_tile_pixel_row
            if signed_addressing:
                tile_index = 256 + (tile_id - 256 if tile_id > 127 else tile_id)
            else:
                tile_index = tile_id
            if attributes and not (attributes & 0xF8):
                row_code = tile_row_codes[tile_index][tile_pixel_row]
                cache = row_cache[attributes]
                try:
                    pixels, rgba = cache[row_code]
                    if diagnostics_enabled:
                        diagnostics['cgb_row_cache_hits'] = (
                            diagnostics.get('cgb_row_cache_hits', 0) + 1
                        )
                except KeyError:
                    pixels, rgba = self._cgb_unflipped_row_rgba(
                        row_code,
                        palette_data,
                        attributes,
                        row_cache,
                    )
                bg_priority = 0
            elif attributes:
                if attributes & 0x40:
                    tile_pixel_row = 7 - tile_pixel_row
                if attributes & 0x08:
                    tile_index += 512
                row_code = tile_row_codes[tile_index][tile_pixel_row]
                pixels, rgba = self._cgb_row_rgba(
                    row_code,
                    palette_data,
                    attributes & 0x07,
                    bool(attributes & 0x20),
                    row_cache,
                )
                bg_priority = 1 if attributes & 0x80 else 0
            else:
                row_code = tile_row_codes[tile_index][tile_pixel_row]
                try:
                    pixels, rgba = palette0_cache[row_code]
                    if diagnostics_enabled:
                        diagnostics['cgb_palette0_cache_hits'] = (
                            diagnostics.get('cgb_palette0_cache_hits', 0) + 1
                        )
                except KeyError:
                    pixels, rgba = self._cgb_palette0_row_rgba(
                        row_code,
                        palette_data,
                    )
                bg_priority = 0
            if tile_pixel_col == 0 and x <= 152:
                run = 8
            else:
                run = min(8 - tile_pixel_col, 160 - x)
            end = tile_pixel_col + run
            scanrow[x:x + run] = pixels[tile_pixel_col:end]
            if bg_priority:
                priority[x:x + run] = priority_runs[run]
                self._bg_priority_dirty = True
            offset = screen_offset + x * 4
            screen_data[offset:offset + run * 4] = rgba[
                tile_pixel_col * 4:end * 4
            ]
            x += run

            tile_col = (tile_col + 1) & 31
            tile_pixel_col = 0

        if diagnostics_enabled:
            diagnostics['cgb_bg_scanlines'] = (
                diagnostics.get('cgb_bg_scanlines', 0) + 1
            )
            diagnostics['cgb_bg_seconds'] = (
                diagnostics.get('cgb_bg_seconds', 0.0)
                + time.perf_counter()
                - start_seconds
            )

    def _render_window_scanline(self, line, lcdc, window_line):
        """Composite the LCD window over the background for one scanline."""
        if self.cgb_mode:
            self._render_cgb_window_scanline(line, lcdc, window_line)
            return

        memory = self.sys_interface.raw_memory
        window_start = memory[GPU_WX] - 7
        x = max(0, window_start)
        window_pixel_x = x - window_start
        tile_col = window_pixel_x >> 3
        tile_pixel_col = window_pixel_x & 7
        tile_pixel_row = window_line & 7
        map_base = 0x9C00 if (lcdc & 0x40) else 0x9800
        map_row_base = map_base + (window_line >> 3) * 32
        signed_addressing = not (lcdc & 0x10)
        palette_value = memory[GPU_BGP]
        palette = DMG_PALETTES[palette_value]
        row_rgba_cache = self._tile_row_rgba_cache[palette_value]
        if row_rgba_cache is None:
            row_rgba_cache = [None] * 0x10000
            self._tile_row_rgba_cache[palette_value] = row_rgba_cache

        screen_data = self.screen_data
        screen_offset = line * 160 * 4
        scanrow = self._scanrow
        tile_row_codes = self.tile_row_codes

        if not tile_pixel_col and not ((160 - x) & 7):
            for screen_x in range(x, 160, 8):
                tile_id = memory[map_row_base + tile_col]
                if signed_addressing:
                    tile_id = tile_id - 256 if tile_id > 127 else tile_id
                    tile_index = 256 + tile_id
                else:
                    tile_index = tile_id

                row_code = tile_row_codes[tile_index][tile_pixel_row]
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

                scanrow[screen_x:screen_x + 8] = pixels
                offset = screen_offset + screen_x * 4
                screen_data[offset:offset + 32] = rgba
                tile_col += 1
            return

        while x < 160:
            tile_id = memory[map_row_base + tile_col]
            if signed_addressing:
                tile_id = tile_id - 256 if tile_id > 127 else tile_id
                tile_index = 256 + tile_id
            else:
                tile_index = tile_id

            row_code = tile_row_codes[tile_index][tile_pixel_row]
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

            run = min(8 - tile_pixel_col, 160 - x)
            end = tile_pixel_col + run
            scanrow[x:x + run] = pixels[tile_pixel_col:end]
            offset = screen_offset + x * 4
            screen_data[offset:offset + run * 4] = rgba[
                tile_pixel_col * 4:end * 4
            ]
            x += run
            tile_col += 1
            tile_pixel_col = 0

    def _render_cgb_window_scanline(self, line, lcdc, window_line):
        """Composite a CGB window scanline using bank-1 tile attributes."""
        diagnostics_enabled = self.diagnostics_enabled
        if diagnostics_enabled:
            start_seconds = time.perf_counter()
            diagnostics = self.diagnostics
        sys_interface = self.sys_interface
        memory = sys_interface.raw_memory
        attr_vram = sys_interface.cgb_vram_bank1
        palette_data = sys_interface.cgb_bg_palette_rgb
        row_cache = self._cgb_bg_row_cache
        window_start = memory[GPU_WX] - 7
        x = max(0, window_start)
        window_pixel_x = x - window_start
        tile_col = window_pixel_x >> 3
        tile_pixel_col = window_pixel_x & 7
        base_tile_pixel_row = window_line & 7
        map_base = 0x9C00 if (lcdc & 0x40) else 0x9800
        map_offset = map_base - 0x8000
        map_row_offset = map_offset + (window_line >> 3) * 32
        signed_addressing = not (lcdc & 0x10)
        screen_data = self.screen_data
        screen_offset = line * 160 * 4
        scanrow = self._scanrow
        priority = self._bg_priority
        priority_runs = self._priority_runs
        tile_row_codes = self.tile_row_codes

        if tile_pixel_col == 0 and not ((160 - x) & 7):
            priority_run = priority_runs[8]
            for screen_x in range(x, 160, 8):
                map_index = map_row_offset + tile_col
                tile_id = memory[0x8000 + map_index]
                attributes = attr_vram[map_index]
                tile_pixel_row = base_tile_pixel_row
                if signed_addressing:
                    tile_index = 256 + (
                        tile_id - 256 if tile_id > 127 else tile_id
                    )
                else:
                    tile_index = tile_id
                if attributes and not (attributes & 0xF8):
                    row_code = tile_row_codes[tile_index][tile_pixel_row]
                    pixels, rgba = self._cgb_unflipped_row_rgba(
                        row_code,
                        palette_data,
                        attributes,
                        row_cache,
                    )
                elif attributes:
                    if attributes & 0x40:
                        tile_pixel_row = 7 - tile_pixel_row
                    if attributes & 0x08:
                        tile_index += 512
                    row_code = tile_row_codes[tile_index][tile_pixel_row]
                    pixels, rgba = self._cgb_row_rgba(
                        row_code,
                        palette_data,
                        attributes & 0x07,
                        bool(attributes & 0x20),
                        row_cache,
                    )
                    if attributes & 0x80:
                        priority[screen_x:screen_x + 8] = priority_run
                        self._bg_priority_dirty = True
                else:
                    row_code = tile_row_codes[tile_index][tile_pixel_row]
                    pixels, rgba = self._cgb_palette0_row_rgba(
                        row_code,
                        palette_data,
                    )

                scanrow[screen_x:screen_x + 8] = pixels
                offset = screen_offset + screen_x * 4
                screen_data[offset:offset + 32] = rgba
                tile_col += 1
            if diagnostics_enabled:
                diagnostics['cgb_window_scanlines'] = (
                    diagnostics.get('cgb_window_scanlines', 0) + 1
                )
                diagnostics['cgb_window_seconds'] = (
                    diagnostics.get('cgb_window_seconds', 0.0)
                    + time.perf_counter()
                    - start_seconds
                )
            return

        while x < 160:
            map_index = map_row_offset + tile_col
            tile_id = memory[0x8000 + map_index]
            attributes = attr_vram[map_index]
            tile_pixel_row = base_tile_pixel_row
            if signed_addressing:
                tile_index = 256 + (tile_id - 256 if tile_id > 127 else tile_id)
            else:
                tile_index = tile_id
            if attributes and not (attributes & 0xF8):
                row_code = tile_row_codes[tile_index][tile_pixel_row]
                pixels, rgba = self._cgb_unflipped_row_rgba(
                    row_code,
                    palette_data,
                    attributes,
                    row_cache,
                )
                bg_priority = 0
            elif attributes:
                if attributes & 0x40:
                    tile_pixel_row = 7 - tile_pixel_row
                if attributes & 0x08:
                    tile_index += 512
                row_code = tile_row_codes[tile_index][tile_pixel_row]
                pixels, rgba = self._cgb_row_rgba(
                    row_code,
                    palette_data,
                    attributes & 0x07,
                    bool(attributes & 0x20),
                    row_cache,
                )
                bg_priority = 1 if attributes & 0x80 else 0
            else:
                row_code = tile_row_codes[tile_index][tile_pixel_row]
                pixels, rgba = self._cgb_palette0_row_rgba(
                    row_code,
                    palette_data,
                )
                bg_priority = 0

            if tile_pixel_col == 0 and x <= 152:
                run = 8
            else:
                run = min(8 - tile_pixel_col, 160 - x)
            end = tile_pixel_col + run
            scanrow[x:x + run] = pixels[tile_pixel_col:end]
            if bg_priority:
                priority[x:x + run] = priority_runs[run]
                self._bg_priority_dirty = True
            offset = screen_offset + x * 4
            screen_data[offset:offset + run * 4] = rgba[
                tile_pixel_col * 4:end * 4
            ]
            x += run

            tile_col += 1
            tile_pixel_col = 0

        if diagnostics_enabled:
            diagnostics['cgb_window_scanlines'] = (
                diagnostics.get('cgb_window_scanlines', 0) + 1
            )
            diagnostics['cgb_window_seconds'] = (
                diagnostics.get('cgb_window_seconds', 0.0)
                + time.perf_counter()
                - start_seconds
            )

    def _render_sprite_scanline(self, line, lcdc):
        """Composite the DMG's first ten eligible objects onto one scanline."""
        if self.cgb_mode:
            self._render_cgb_sprite_scanline(line, lcdc)
            return

        memory = self.sys_interface.raw_memory
        height = 16 if (lcdc & 0x04) else 8
        if self._sprite_cache_dirty or self._sprite_cache_height != height:
            self._rebuild_sprite_cache(height)
        objects = self._sprite_scanlines[line]
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

    def _render_cgb_sprite_scanline(self, line, lcdc):
        """Composite CGB objects with VRAM-bank and color-palette attributes."""
        diagnostics_enabled = self.diagnostics_enabled
        if diagnostics_enabled:
            start_seconds = time.perf_counter()
            diagnostics = self.diagnostics
        memory = self.sys_interface.raw_memory
        palette_data = self.sys_interface.cgb_obj_palette_rgb
        height = 16 if (lcdc & 0x04) else 8
        if self._sprite_cache_dirty or self._sprite_cache_height != height:
            self._rebuild_sprite_cache(height)
        objects = self._sprite_scanlines[line]
        claimed = self._sprite_claimed
        claimed[:] = self._empty_scanrow
        screen_data = self.screen_data
        screen_offset = line * 160 * 4

        for object_x, _, object_y, tile_index, attributes in objects:
            row = line - object_y
            if attributes & 0x40:
                row = height - 1 - row

            if height == 16:
                tile_index = (tile_index & 0xFE) + (row >> 3)
                row &= 7

            if attributes & 0x08:
                tile_index += 512
            tile_row = self.tile_set[tile_index][row]
            palette = palette_data[attributes & 0x07]

            for pixel in range(8):
                screen_x = object_x - 8 + pixel
                if not 0 <= screen_x < 160 or claimed[screen_x]:
                    continue

                tile_x = 7 - pixel if attributes & 0x20 else pixel
                color_index = tile_row[tile_x]
                if color_index == 0:
                    continue

                claimed[screen_x] = True
                if (
                    self._bg_priority[screen_x]
                    or (attributes & 0x80)
                ) and self._scanrow[screen_x] != 0:
                    continue

                red, green, blue = palette[color_index]
                offset = screen_offset + screen_x * 4
                screen_data[offset] = red
                screen_data[offset + 1] = green
                screen_data[offset + 2] = blue
                screen_data[offset + 3] = 255

        if diagnostics_enabled:
            diagnostics['cgb_sprite_scanlines'] = (
                diagnostics.get('cgb_sprite_scanlines', 0) + 1
            )
            diagnostics['cgb_sprite_seconds'] = (
                diagnostics.get('cgb_sprite_seconds', 0.0)
                + time.perf_counter()
                - start_seconds
            )

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
