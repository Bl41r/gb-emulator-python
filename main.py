"""Gameboy emulator.

github.com/bl41r/gb-emulator-python
2019
"""

import sys


def main(filename):
    """Main."""
    pass


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("usage: python3 main.py <rom_filename>")
        sys.exit(1)
    main(sys.argv[1])
