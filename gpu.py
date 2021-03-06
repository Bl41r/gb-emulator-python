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


class GbGpu(object):
    """GPU unit for the gameboy."""

    def __init__(self):
        """Init."""
        self._line = 0
        self._curscan = 0
        self._mode = 0
        self._mode_clock = 0
        self._mode_funcs = {
            0: self._h_blank_render_screen,
            1: self._v_blank,
            2: self._oam_read_mode,
            3: self._vram_read_mode,
        }
        self.screen_data = [255 for i in range(160 * 144 * 4)]
        self.tile_set = self._create_tile_set()
        self.sys_interface = None    # Set after interface instantiated
        self.register_map = {
            'lcd_gpu_ctrl': 0xFF40,
            'scroll_y': 0xFF42,
            'scroll_x': 0xFF43,
            'curr_line': 0xFF44,
            'raster': 0xFF45,
            'oam_dma': 0xFF46,
            'bgrnd_palette': 0xFF47
        }
        self._linemode = 0

    def step(self, m):
        """Perform one step."""
        self._mode_clock += m
        print("linemode:", self._mode_funcs[self._linemode].__name__)
        self._mode_funcs[self._linemode]()

    def update_tile(self, addr, val):
        """Update a tile.

        Called when a value written to VRAM, and updates the
        internal tile set.
        """
        base_addr = addr & 0x1FFE
        tile = (base_addr >> 4) & 511
        y = (base_addr >> 1) & 7
        for i in range(8):
            sx = 1 << (7 - i)   # Find bit index for this pixel
            t1 = 1 if self.memory_interface.read_byte(addr) & sx else 0
            t2 = 2 if self.memory_interface.read_byte(addr + 1) & sx else 0
            self.tile_set[tile][y][i] = t1 + t2

    def get_gpu_ctrl_reg(self, reg_name):
        """Return on/off (bit value or 0) for the LCD/GPU control register bit.

        Bit  Function               When 0  When 1
        0   Background: on/off      Off     On
        1   Sprites: on/off         Off     On
        2   Sprites: size (pixels)  8x8     8x16
        3   Background: tile map    #0      #1
        4   Background: tile set    #0      #1
        5   Window: on/off          Off     On
        6   Window: tile map        #0      #1
        7   Display: on/off         Off     On
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

    @staticmethod
    def _create_tile_set():
        return [
            [
                [0] * 8, [0] * 8, [0] * 8, [0] * 8,
                [0] * 8, [0] * 8, [0] * 8, [0] * 8
            ] for i in range(512)
        ]

    def reset_screen(self):
        """Reset screen to white."""
        self.screen_data = [255 for i in range(160 * 144 * 4)]

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

    def _h_blank_render_screen(self):
        """Horizontal blank, and render screen data."""
        if self._mode_clock >= 51:

            if self.read_register('curr_line') == 143:
                self._mode = 1
                # self.put_image_data(self.screen, 0, 0)
                # memory._interrupt_flag |= 1
            else:
                self._mode = 2

            self.write_reg('curr_line', self.read_reg('curr_line') + 1)
            self.curscan += 640
            self._mode_clock = 0

    def _v_blank(self):
        """."""
        if self._mode_clock >= 114:
            self._mode_clock = 0
            self.write_reg('curr_line', self.read_reg('curr_line') + 1)

            if self.read_reg('curr_line') > 153:
                self.write_reg('curr_line', 0)
                self._curscan = 0
                self._mode = 2

    def _oam_read_mode(self):
        """OAM read."""
        if self._mode_clock >= 20:
            self._mode_clock = 0
            self._mode = 3

    def _vram_read_mode(self):
        """VRAM read."""
        if self._mode_clock >= 43:
            self._mode_clock = 0
            self._mode = 0
            self._renderscan()

    def _renderscan(self):
        """Render scan."""
        print("_renderscan called!")
