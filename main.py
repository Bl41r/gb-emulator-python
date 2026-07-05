import argparse
import cProfile
from collections import deque
import json
import os
import pygame
import numpy as np
import pygame.surfarray
import pstats
from threading import Lock
import time

from pygame._sdl2 import INIT_AUDIO, init_subsystem
from pygame._sdl2.audio import (
    AUDIO_S16,
    AudioDevice,
    get_audio_device_names,
)

from apu import GbApu, SAMPLE_RATE
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
DMG_CLOCK_HZ = 4_194_304
DMG_CYCLES_PER_FRAME = 70_224
DMG_FRAME_SECONDS = DMG_CYCLES_PER_FRAME / DMG_CLOCK_HZ

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


def main(
    filename,
    trace=False,
    max_frames=None,
    max_seconds=None,
    no_display=False,
    frameskip=1,
    input_script=None,
    uncapped=False,
    audio=True,
    volume=10,
    opcode_stats=False,
):
    gb_memory = GbMemory(skip_bios=False, gb_doctor_test_mode=GB_DR_TEST_MODE)
    cpu = GbZ80Cpu(
        GB_DR_LOG_DUMP,
        gb_doctor_test_mode=GB_DR_TEST_MODE,
        trace_enabled=trace,
    )
    gpu = GbGpu()
    if opcode_stats:
        cpu.opcode_counts = [0] * 256
        cpu.cb_opcode_counts = [0] * 256
    audio_enabled = audio and not no_display and not uncapped
    apu = GbApu(gb_memory.memory) if audio_enabled else None

    if GB_DR_TEST_MODE:
        caption = f"GameBoy Emulator (TEST MODE) - {filename}"
        print("IN TEST MODE")
    else:
        caption = f"GameBoy Emulator - {filename}"

    sys_interface = GbSystemInterface(gb_memory, cpu, gpu, apu=apu)

    for component in [cpu, gpu]:
        component.sys_interface = sys_interface

    sys_interface.load_rom_image(filename)
    scripted_input = load_input_script(input_script) if input_script else {}

    window = None
    audio_output = None
    if not no_display:
        # Setup Pygame
        pygame.init()
        window = pygame.display.set_mode((SCREEN_WIDTH * SCALE, SCREEN_HEIGHT * SCALE))
        pygame.display.set_caption(caption)
        if audio_enabled:
            try:
                audio_output = PygameAudioOutput(volume / 100.0)
            except pygame.error as error:
                print(f"Audio disabled: {error}")
                audio_enabled = False

    stats = {
        'instructions': 0,
        'frames': 0,
        'drawn_frames': 0,
        'draw_seconds': 0.0,
        'sleep_seconds': 0.0,
        'start_seconds': time.perf_counter(),
        'last_caption_seconds': time.perf_counter(),
        'last_caption_frames': 0,
        'last_caption_drawn_frames': 0,
        'last_caption_instructions': 0,
    }
    stop_seconds = (
        stats['start_seconds'] + max_seconds
        if max_seconds is not None
        else None
    )
    execute_next_operation = cpu.execute_next_operation
    instructions = 0
    pace_frames = not no_display and not uncapped
    next_frame_deadline = stats['start_seconds'] + DMG_FRAME_SECONDS

    try:
        while True:
            instructions += execute_next_operation()

            if gpu.frame_ready:
                gpu.frame_ready = False
                stats['frames'] += 1
                stats['instructions'] = instructions
                apply_scripted_input(sys_interface, scripted_input, stats['frames'])
                if not no_display:
                    handle_events(sys_interface)
                    if audio_enabled:
                        audio_output.queue(apu.generate_frame())
                    if should_draw_frame(stats['frames'], frameskip):
                        draw_start = time.perf_counter()
                        draw_screen(gpu, window)
                        stats['draw_seconds'] += time.perf_counter() - draw_start
                        stats['drawn_frames'] += 1
                    if pace_frames:
                        next_frame_deadline, slept = pace_frame(
                            next_frame_deadline
                        )
                        stats['sleep_seconds'] += slept
                    update_caption(caption, stats)

                if max_frames is not None and stats['frames'] >= max_frames:
                    break
                if stop_seconds is not None and time.perf_counter() >= stop_seconds:
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
        stats['instructions'] = instructions
        sys_interface.flush_save_ram()
        if audio_output is not None:
            print(
                "Audio queue: "
                f"{audio_output.underruns} underruns, "
                f"{audio_output.callbacks} callbacks, "
                f"{audio_output.queued_milliseconds():.1f} ms queued"
            )
            audio_output.close()
        if not no_display:
            pygame.quit()
        print_run_stats(stats, no_display)
        if opcode_stats:
            print_opcode_stats(cpu)


def load_input_script(filename):
    """Load scripted button events keyed by frame number."""
    with open(filename, "r", encoding="utf-8") as f:
        events = json.load(f)

    by_frame = {}
    for event in events:
        frame = int(event["frame"])
        button = event["button"]
        pressed = bool(event["pressed"])
        if button not in {"right", "left", "up", "down", "a", "b", "select", "start"}:
            raise ValueError(f"unknown input script button: {button}")
        by_frame.setdefault(frame, []).append((button, pressed))
    return by_frame


def apply_scripted_input(sys_interface, scripted_input, frame):
    """Apply all scripted button changes scheduled for a completed frame."""
    for button, pressed in scripted_input.get(frame, ()):
        sys_interface.set_button(button, pressed)


def handle_events(sys_interface):
    """Handle pending pygame events once per displayed frame."""
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            raise ExecutionHalted()
        if event.type in (pygame.KEYDOWN, pygame.KEYUP):
            button = KEY_BINDINGS.get(event.key)
            if button:
                sys_interface.set_button(button, event.type == pygame.KEYDOWN)


class PygameAudioOutput(object):
    """Feed a continuous SDL audio stream from a thread-safe byte ring."""

    def __init__(self, volume=0.10):
        pygame.mixer.quit()
        init_subsystem(INIT_AUDIO)
        self.volume = volume
        device_names = get_audio_device_names(False)
        device_name = device_names[0] if device_names else None
        self.chunks = deque()
        self.chunk_offset = 0
        self.queued_bytes = 0
        self.lock = Lock()
        self.started = False
        self.underruns = 0
        self.callbacks = 0
        self.prebuffer_bytes = int(
            SAMPLE_RATE * DMG_FRAME_SECONDS * 8
        ) * 4
        self.device = AudioDevice(
            devicename=device_name,
            iscapture=False,
            frequency=SAMPLE_RATE,
            audioformat=AUDIO_S16,
            numchannels=2,
            chunksize=1024,
            allowed_changes=0,
            callback=self._callback,
        )

    def queue(self, samples):
        samples = np.ascontiguousarray(samples)
        if self.volume != 1.0:
            np.multiply(
                samples,
                self.volume,
                out=samples,
                casting="unsafe",
            )
        chunk = samples.tobytes()
        should_start = False
        with self.lock:
            self.chunks.append(chunk)
            self.queued_bytes += len(chunk)
            if not self.started and self.queued_bytes >= self.prebuffer_bytes:
                self.started = True
                should_start = True
        if should_start:
            self.device.pause(0)

    def _callback(self, device, output):
        del device
        output_offset = 0
        output_length = len(output)
        with self.lock:
            self.callbacks += 1
            while output_offset < output_length and self.chunks:
                chunk = self.chunks[0]
                available = len(chunk) - self.chunk_offset
                take = min(available, output_length - output_offset)
                end = self.chunk_offset + take
                output[output_offset:output_offset + take] = chunk[
                    self.chunk_offset:end
                ]
                output_offset += take
                self.chunk_offset = end
                self.queued_bytes -= take
                if self.chunk_offset == len(chunk):
                    self.chunks.popleft()
                    self.chunk_offset = 0

            if output_offset < output_length:
                output[output_offset:output_length] = bytes(
                    output_length - output_offset
                )
                if self.started:
                    self.underruns += 1

    def queued_milliseconds(self):
        with self.lock:
            queued_bytes = self.queued_bytes
        return queued_bytes / (SAMPLE_RATE * 4) * 1000

    def close(self):
        if self.started:
            self.device.pause(1)
        self.device.close()


def should_draw_frame(frame_number, frameskip):
    """Return True when this completed emulated frame should be displayed."""
    return (frame_number - 1) % frameskip == 0


def pace_frame(deadline):
    """Wait for the next DMG frame boundary without accumulating lag."""
    now = time.perf_counter()
    delay = deadline - now
    waited = 0.0
    if delay > 0:
        wait_start = now
        if delay > 0.002:
            time.sleep(delay - 0.001)
        now = time.perf_counter()
        while now < deadline:
            now = time.perf_counter()
        waited = now - wait_start

    deadline += DMG_FRAME_SECONDS
    if now - deadline > DMG_FRAME_SECONDS * 4:
        deadline = now + DMG_FRAME_SECONDS
    return deadline, waited


def update_caption(base_caption, stats):
    """Refresh the window title with recent performance once per second."""
    now = time.perf_counter()
    elapsed = now - stats['last_caption_seconds']
    if elapsed < 1.0:
        return

    frames = stats['frames'] - stats['last_caption_frames']
    drawn_frames = stats['drawn_frames'] - stats['last_caption_drawn_frames']
    instructions = stats['instructions'] - stats['last_caption_instructions']
    fps = frames / elapsed
    draw_fps = drawn_frames / elapsed
    instructions_per_second = instructions / elapsed

    pygame.display.set_caption(
        f"{base_caption} - {fps:.1f} emu FPS - {draw_fps:.1f} draw FPS - "
        f"{instructions_per_second:,.0f} instr/s"
    )
    stats['last_caption_seconds'] = now
    stats['last_caption_frames'] = stats['frames']
    stats['last_caption_drawn_frames'] = stats['drawn_frames']
    stats['last_caption_instructions'] = stats['instructions']


def print_run_stats(stats, no_display):
    elapsed = time.perf_counter() - stats['start_seconds']
    elapsed = max(elapsed, 0.000001)
    draw_seconds = stats['draw_seconds']
    sleep_seconds = stats['sleep_seconds']
    emulation_seconds = elapsed - draw_seconds - sleep_seconds
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
            f"{stats['drawn_frames']} drawn frames, "
            f"{draw_seconds:.2f}s drawing "
            f"({draw_seconds / elapsed * 100:.1f}% of elapsed), "
            f"{sleep_seconds:.2f}s pacing, "
            f"{emulation_seconds:.2f}s emulation/event loop"
        )


def print_opcode_stats(cpu, limit=20):
    """Print the most frequently executed base and CB-prefixed opcodes."""
    total = sum(cpu.opcode_counts)
    print(f"Top opcodes ({total:,} counted):")
    print(f"  HALT idle time: {cpu.halt_m_cycles:,} M-cycles")
    ranked = sorted(
        enumerate(cpu.opcode_counts),
        key=lambda item: item[1],
        reverse=True,
    )
    for opcode, count in ranked[:limit]:
        if not count:
            break
        handler, args = cpu.opcode_map[opcode]
        percent = count / total * 100 if total else 0
        print(
            f"  {opcode:02X} {handler.__name__:<18} "
            f"{count:>10,}  {percent:>5.2f}%  {args}"
        )

    cb_total = sum(cpu.cb_opcode_counts)
    if cb_total:
        print(f"Top CB opcodes ({cb_total:,} counted):")
        ranked_cb = sorted(
            enumerate(cpu.cb_opcode_counts),
            key=lambda item: item[1],
            reverse=True,
        )
        for opcode, count in ranked_cb[:limit]:
            if not count:
                break
            handler, args = cpu.cb_map[opcode]
            percent = count / cb_total * 100
            print(
                f"  CB {opcode:02X} {handler.__name__:<15} "
                f"{count:>10,}  {percent:>5.2f}%  {args}"
            )


def draw_screen(gpu, screen):
    """Draw the GPU buffer to the Pygame window using fast blitting."""
    # Create surface from the GPU's persistent RGB framebuffer.
    surface = pygame.surfarray.make_surface(
        np.transpose(gpu.screen['rgb'], (1, 0, 2))
    )

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
        "--max-seconds",
        type=float,
        help="exit automatically after running for this many real-time seconds",
    )
    parser.add_argument(
        "--no-display",
        action="store_true",
        help="run without opening a pygame window or drawing frames",
    )
    parser.add_argument(
        "--frameskip",
        type=int,
        default=1,
        help="draw every Nth completed frame; 1 draws every frame",
    )
    parser.add_argument(
        "--uncapped",
        action="store_true",
        help="run displayed gameplay without the normal 59.73 FPS speed limit",
    )
    parser.add_argument(
        "--no-audio",
        action="store_true",
        help="disable sound output",
    )
    parser.add_argument(
        "--volume",
        type=int,
        default=10,
        metavar="PERCENT",
        help="set output volume from 0 to 100 (default: 10)",
    )
    parser.add_argument(
        "--input-script",
        help="JSON file of frame-based button events for repeatable profiling",
    )
    parser.add_argument(
        "--profile",
        help="write cProfile stats to this file",
    )
    parser.add_argument(
        "--opcode-stats",
        action="store_true",
        help="count and print the most frequently executed opcodes",
    )
    args = parser.parse_args()
    if args.frameskip < 1:
        parser.error("--frameskip must be 1 or greater")
    if not 0 <= args.volume <= 100:
        parser.error("--volume must be between 0 and 100")

    if args.profile:
        profiler = cProfile.Profile()
        profiler.enable()
        try:
            main(
                args.rom,
                trace=args.trace,
                max_frames=args.max_frames,
                max_seconds=args.max_seconds,
                no_display=args.no_display,
                frameskip=args.frameskip,
                input_script=args.input_script,
                uncapped=args.uncapped,
                audio=not args.no_audio,
                volume=args.volume,
                opcode_stats=args.opcode_stats,
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
            max_seconds=args.max_seconds,
            no_display=args.no_display,
            frameskip=args.frameskip,
            input_script=args.input_script,
            uncapped=args.uncapped,
            audio=not args.no_audio,
            volume=args.volume,
            opcode_stats=args.opcode_stats,
        )
