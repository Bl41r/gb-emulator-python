"""Game Boy joypad matrix exposed through the P1/JOYP register."""


ACTION_BITS = {
    "a": 0,
    "b": 1,
    "select": 2,
    "start": 3,
}

DIRECTION_BITS = {
    "right": 0,
    "left": 1,
    "up": 2,
    "down": 3,
}

BUTTONS = set(ACTION_BITS) | set(DIRECTION_BITS)


class Joypad:
    """Track eight buttons and the two active-low selected rows."""

    def __init__(self):
        self.select = 0x30
        self.pressed = set()

    def read(self):
        """Return the active-low JOYP register value."""
        low = 0x0F

        if not (self.select & 0x20):
            low &= self._row_value(ACTION_BITS)
        if not (self.select & 0x10):
            low &= self._row_value(DIRECTION_BITS)

        return 0xC0 | self.select | low

    def write(self, value):
        """Select action and/or direction rows; return falling-edge status."""
        before = self.read() & 0x0F
        self.select = value & 0x30
        after = self.read() & 0x0F
        return bool(before & ~after)

    def set_button(self, button, is_pressed):
        """Update a button; return whether a selected input fell low."""
        if button not in BUTTONS:
            raise KeyError("unknown joypad button: {}".format(button))

        before = self.read() & 0x0F
        if is_pressed:
            self.pressed.add(button)
        else:
            self.pressed.discard(button)
        after = self.read() & 0x0F
        return bool(before & ~after)

    def _row_value(self, mapping):
        value = 0x0F
        for button, bit in mapping.items():
            if button in self.pressed:
                value &= ~(1 << bit)
        return value
