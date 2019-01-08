"""Gameboy emulator.

github.com/bl41r/gb-emulator-python
2019
"""


import sys
from memory import GbMemory
from cpu import GbZ80Cpu, ExecutionHalted
from gpu import GbGpu
from memory_interface import GbMemInterface


LOG_DUMP = []   # append debug messages here


def main(filename):
    """Main."""
    # gb_memory.load_rom_image(filename)
    gb_memory = GbMemory()
    cpu = GbZ80Cpu()
    gpu = GbGpu()

    mem_interface = GbMemInterface(gb_memory, cpu, gpu)     # comm. layer
    for component in [cpu, gpu]:
        component.memory_interface = mem_interface

    mem_interface.load_rom_image(filename)

    try:
        while True:
            cpu.execute_next_operation()

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
    dump_mem_map(memory)
    print("Registers:", cpu.registers)


def dump_mem_map(memory):
    """Print all non-zero values in memory."""
    dump = ['address : value']
    for i in range(2**16):
        if memory[i] != 0:
            dump.append("{} : {}".format(str(hex(i)), memory[i]))

    with open('memdump.txt', 'w') as f:
        for line in dump:
            f.write(line + '\n')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("usage: python3 main.py <rom_filename>")
        sys.exit(1)
    main(sys.argv[1])
