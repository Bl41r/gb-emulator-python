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
o be moved relative to the screeen. The GPU achieves this by defining a
point in the background that corresponds to the top-left of the screen:
by moving this point between frames, the background is made to scroll on
the screen. For this reason, the definition of the top-left corner is held
by two GPU registers: Scroll X and Scroll Y.

Palettes
Each pixel is two bits.
Value   Pixel   Emulated colour
0   Off [255, 255, 255]
1   33% on  [192, 192, 192]
2   66% on  [96, 96, 96]
3   On  [0, 0, 0]

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
        self.memory_interface = None    # Set after interface instantiated

    def step(self, m):
        """Perform one step."""
        self.mode_clock += m
        self._mode_funcs[self.mode]()

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

    def reset_screen(self):
        """Reset screen to white."""
        self.screen_data = [255 for i in range(160 * 144 * 4)]

    def _create_tile_set(self):
        return [
            [
                [0] * 8, [0] * 8, [0] * 8, [0] * 8, [0] * 8, [0] * 8, [0] * 8, [0] * 8
            ] for i in range(512)
        ]

    def _h_blank_render_screen(self):
        """Horizontal blank, and render screen data."""
        if (self._mode_clock >= 204):
            self._mode_clock = 0
            self._line += 1

            if self._line == 143:
                self._mode = 1
                self.put_image_data(self.screen, 0, 0)
            else:
                self._mode = 2

    def _v_blank(self):
        """."""
        if self._mode_clock >= 456:
            self._mode_clock = 0
            self._line += 1

            if self._line > 153:
                self._mode = 2
                self._line = 0

    def _oam_read_mode(self):
        """OAM read."""
        if (self._mode_clock >= 80):
            self._mode_clock = 0
            self._mode = 3

    def _vram_read_mode(self):
        """VRAM read."""
        if self._mode_clock >= 172:
            self._mode_clock = 0
            self._mode = 0
            self._renderscan()

    def renderscan(self):
        """Render scan."""
        print("renderscan called")

        # VRAM offset for the tile map
        mapoffs = 0x1C00 if self._bgmap else 0x1800

        # Which line of tiles to use in the map
        mapoffs += ((self._line + self._scy) & 255) >> 3

        # Which tile to start with in the map line
        lineoffs = (self._scx >> 3)

        # Which line of pixels to use in the tiles
        y = (self._line + self._scy) & 7

        # Where in the tileline to start
        x = self._scx & 7

        # Where to render on the canvas
        canvasoffs = self._line * 160 * 4

        # Read tile index from the background map
        tile = self._vram[mapoffs + lineoffs]

        # If the tile data set in use is #1, the
        # indices are signed; calculate a real tile offset
        if (self._bgtile == 1) and (tile < 128):
            tile += 256

        for i in range(160):
            # Re-map the tile pixel through the palette
            color = self._pal[self._tileset[tile][y][x]]

            # Plot the pixel to canvas
            self._scrn.data[canvasoffs + 0] = color[0]
            self._scrn.data[canvasoffs + 1] = color[1]
            self._scrn.data[canvasoffs + 2] = color[2]
            self._scrn.data[canvasoffs + 3] = color[3]
            canvasoffs += 4

            x += 1
            if x == 8:
                x = 0
                lineoffs = (lineoffs + 1) & 31
                tile = self._vram[mapoffs + lineoffs]
                if (self._bgtile == 1 and tile < 128):
                    tile += 256






