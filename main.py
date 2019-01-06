"""Gameboy emulator.

github.com/bl41r/gb-emulator-python
2019
"""

"""Gameboy emulator.

github.com/bl41r/gb-emulator-python
2019
"""

import sys
from memory import GbMemory
from cpu import GbZ80Cpu, ExecutionHalted


LOG_DUMP = []   # append debug messages here


def main(filename):
    """Main."""
    gb_memory = GbMemory()
    gb_memory.load_rom_image(filename)
    cpu = GbZ80Cpu(gb_memory)

    try:
        while True:
            cpu.execute_next_instruction()

    except ExecutionHalted:     # raised by trap_halt (expected exit)
        print("\nShutting down...")
        sys.exit(0)

    except (Exception, KeyboardInterrupt) as e:
        dump_logs(gb_memory.memory, cpu)
        raise e


# Debugging

def dump_logs(memory, cpu):
    """Print all messages in LOG_DUMP."""
    print("\n\nLOG DUMP:")
    for item in LOG_DUMP:
        print(item)
    print()
    # print_mem_map(memory)
    print("Registers:", cpu.registers)


def print_mem_map(memory):
    """Print all non-zero values in memory."""
    for i in range(2**16):
        if memory[i] != 0:
            print("val: {}  index: {}".format(memory[i], i))


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("usage: python3 main.py <rom_filename>")
        sys.exit(1)
    main(sys.argv[1])
