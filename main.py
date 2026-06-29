import argparse
import cProfile
import os
import pygame
import numpy as np
import pygame.surfarray
import pstats
import time

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

KEY_BINDINGS = {
    pygame.K_RIGHT: "right",
    pygame.K_LEFT: "left",
    pygame.K_UP: "up",
    pygame.K_DOWN: "down",
    pygame.K_z: "a",
    pygame.K_x: "b",
    pygame.K_BACKSPACE: "select",
    pygame.K_RETURN: "start",
    pygame.K_KP_ENTER: "start",
}


def main(filename, trace=False, max_frames=None, no_display=False):
    gb_memory = GbMemory(skip_bios=False, gb_doctor_test_mode=GB_DR_TEST_MODE)
    cpu = GbZ80Cpu(
        GB_DR_LOG_DUMP,
        gb_doctor_test_mode=GB_DR_TEST_MODE,
        trace_enabled=trace,
    )
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

    window = None
    if not no_display:
        # Setup Pygame
        pygame.init()
        window = pygame.display.set_mode((SCREEN_WIDTH * SCALE, SCREEN_HEIGHT * SCALE))
        pygame.display.set_caption(caption)

    stats = {
        'instructions': 0,
        'frames': 0,
        'draw_seconds': 0.0,
        'start_seconds': time.perf_counter(),
    }

    try:
        while True:
            if not no_display:
                # Handle window events
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        raise ExecutionHalted()
                    if event.type in (pygame.KEYDOWN, pygame.KEYUP):
                        button = KEY_BINDINGS.get(event.key)
                        if button:
                            sys_interface.set_button(
                                button, event.type == pygame.KEYDOWN
                            )

            cpu.execute_next_operation()
            stats['instructions'] += 1

            if gpu.consume_frame_ready():
                stats['frames'] += 1
                if not no_display:
                    draw_start = time.perf_counter()
                    draw_screen(gpu, window)
                    stats['draw_seconds'] += time.perf_counter() - draw_start

                if max_frames is not None and stats['frames'] >= max_frames:
                    break

    except ExecutionHalted:
        pass
    except Exception as e:
        print("\nShutting down...")
        if GB_DR_TEST_MODE:
            dump_logs(gb_memory.memory, cpu)
        if not no_display:
            pygame.quit()
        raise e
    finally:
        if not no_display:
            pygame.quit()
        print_run_stats(stats, no_display)


def print_run_stats(stats, no_display):
    elapsed = time.perf_counter() - stats['start_seconds']
    elapsed = max(elapsed, 0.000001)
    draw_seconds = stats['draw_seconds']
    emulation_seconds = elapsed - draw_seconds
    print(
        "Run stats: "
        f"{stats['frames']} frames, "
        f"{stats['instructions']} instructions, "
        f"{elapsed:.2f}s elapsed, "
        f"{stats['frames'] / elapsed:.2f} fps, "
        f"{stats['instructions'] / elapsed:,.0f} instr/s"
    )
    if not no_display:
        print(
            "Rendering: "
            f"{draw_seconds:.2f}s drawing "
            f"({draw_seconds / elapsed * 100:.1f}% of elapsed), "
            f"{emulation_seconds:.2f}s emulation/event loop"
        )


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
    parser = argparse.ArgumentParser(description="Run the Game Boy emulator")
    parser.add_argument("rom", help="path to a Game Boy ROM")
    parser.add_argument(
        "--trace",
        action="store_true",
        help="print each executed instruction and interrupt",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        help="exit automatically after rendering this many frames",
    )
    parser.add_argument(
        "--no-display",
        action="store_true",
        help="run without opening a pygame window or drawing frames",
    )
    parser.add_argument(
        "--profile",
        help="write cProfile stats to this file",
    )
    args = parser.parse_args()

    if args.profile:
        profiler = cProfile.Profile()
        profiler.enable()
        try:
            main(
                args.rom,
                trace=args.trace,
                max_frames=args.max_frames,
                no_display=args.no_display,
            )
        finally:
            profiler.disable()
            profiler.dump_stats(args.profile)
            print(f"Profile written to {args.profile}")
            stats = pstats.Stats(profiler).sort_stats('cumulative')
            stats.print_stats(25)
    else:
        main(
            args.rom,
            trace=args.trace,
            max_frames=args.max_frames,
            no_display=args.no_display,
        )
