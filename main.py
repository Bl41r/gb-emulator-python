import sys, os
import pygame
import numpy as np
import pygame.surfarray

from memory import GbMemory
from cpu import GbZ80Cpu, ExecutionHalted
from gpu import GbGpu
from system_interface import GbSystemInterface

GB_DR_TEST_MODE = False
GB_DR_LOG_DUMP = []

# Screen settings
SCREEN_WIDTH = 160
SCREEN_HEIGHT = 144
SCALE = 3

def main(filename):
    gb_memory = GbMemory(skip_bios=False, gb_doctor_test_mode=GB_DR_TEST_MODE)
    cpu = GbZ80Cpu(GB_DR_LOG_DUMP, gb_doctor_test_mode=GB_DR_TEST_MODE)
    gpu = GbGpu()

    if GB_DR_TEST_MODE:
        caption = f"GameBoy Emulator (TEST MODE) - {filename}"
        print("IN TEST MODE")
    else:
        caption = f"GameBoy Emulator - {filename}"

    sys_interface = GbSystemInterface(gb_memory, cpu, gpu)

    for component in [cpu, gpu]:
        component.sys_interface = sys_interface

    sys_interface.load_rom_image(filename)

    # Setup Pygame
    pygame.init()
    window = pygame.display.set_mode((SCREEN_WIDTH * SCALE, SCREEN_HEIGHT * SCALE))
    pygame.display.set_caption(caption)

    clock = pygame.time.Clock()

    try:
        while True:
            # Handle window events
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    raise ExecutionHalted()

            cpu.execute_next_operation()

            # Check if we just hit the V-Blank mode
            if gpu.linemode == 1 and gpu.read_reg('curr_line') == 144:
                draw_screen(gpu, window)
                # clock.tick(60)  # cap at ~60 FPS

    except Exception as e:
        print("\nShutting down...")
        if GB_DR_TEST_MODE:
            dump_logs(gb_memory.memory, cpu)
        pygame.quit()
        raise e


def draw_screen(gpu, screen):
    """Draw the GPU buffer to the Pygame window using fast blitting."""
    # Convert 160x144x4 flat list into 3D NumPy array
    buffer = np.array(gpu.screen['data'], dtype=np.uint8).reshape((144, 160, 4))

    # Remove alpha channel (RGB only)
    rgb_buffer = buffer[:, :, :3]

    # print("Sample pixel RGB:", rgb_buffer[0, 0])

    # Create surface from array
    surface = pygame.surfarray.make_surface(np.transpose(rgb_buffer, (1, 0, 2)))  # Transpose to (width, height, 3)

    # Scale it
    surface = pygame.transform.scale(surface, (SCREEN_WIDTH * SCALE, SCREEN_HEIGHT * SCALE))

    screen.blit(surface, (0, 0))
    pygame.display.flip()


def dump_logs(memory, cpu):
    dump_mem_map(memory)

    print("Registers:", cpu.registers)
    if os.path.exists('cpu_log.txt'):
        os.remove('cpu_log.txt')
    with open('cpu_log.txt', 'w') as f:
        for entry in GB_DR_LOG_DUMP:
            f.write(entry + '\n')


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
