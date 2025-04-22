import sys
import pygame
from memory import GbMemory
from cpu import GbZ80Cpu, ExecutionHalted
from gpu import GbGpu
from system_interface import GbSystemInterface

LOG_DUMP = []

SCREEN_WIDTH = 160
SCREEN_HEIGHT = 144
SCALE = 3


def draw_screen(gpu, screen):
    """Draw screen buffer to pygame window."""
    for y in range(SCREEN_HEIGHT):
        for x in range(SCREEN_WIDTH):
            offset = (y * SCREEN_WIDTH + x) * 4
            color_val = gpu.screen['data'][offset]
            pygame.draw.rect(screen,
                             (color_val, color_val, color_val),
                             pygame.Rect(x * SCALE, y * SCALE, SCALE, SCALE))
    pygame.display.flip()


def main(filename):
    gb_memory = GbMemory()
    cpu = GbZ80Cpu()
    gpu = GbGpu()
    sys_interface = GbSystemInterface(gb_memory, cpu, gpu)

    for component in [cpu, gpu]:
        component.sys_interface = sys_interface

    sys_interface.load_rom_image(filename)

    # Setup Pygame
    pygame.init()
    window = pygame.display.set_mode((SCREEN_WIDTH * SCALE, SCREEN_HEIGHT * SCALE))
    pygame.display.set_caption("Game Boy Emulator")

    clock = pygame.time.Clock()

    try:
        while True:
            # Handle window events
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    raise ExecutionHalted()

            cpu.execute_next_operation()

            # Check if we just hit the V-Blank mode
            if gpu._mode == 1 and gpu.read_reg('curr_line') == 144:
                print('hit v-blank mode')
                draw_screen(gpu, window)
                clock.tick(60)  # cap at ~60 FPS

    except ExecutionHalted:
        print("\nShutting down...")
        pygame.quit()
        sys.exit(0)

    except Exception as e:
        pygame.quit()
        print('\ncpu clock:', sys_interface.cpu.clock['m'])
        dump_logs(gb_memory.memory, cpu)
        raise e


def dump_logs(memory, cpu):
    print("\n\nLOG DUMP:")
    for item in LOG_DUMP:
        print(item)
    print()
    dump_mem_map(memory)
    print("Registers:", cpu.registers)


def dump_mem_map(memory):
    dump = ['address : value']
    for i in range(2**16):
        if memory[i] != 0:
            dump.append(f"{hex(i)} : {memory[i]}")

    with open('memdump.txt', 'w') as f:
        for line in dump:
            f.write(line + '\n')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("usage: python3 main.py <rom_filename>")
        sys.exit(1)
    main(sys.argv[1])
