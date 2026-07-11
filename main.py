import argparse
import cProfile
from collections import deque
import json
import os
from pathlib import Path
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
    gpu_diagnostics=False,
    screenshot_dir=None,
    screenshot_start_seconds=0.0,
    screenshot_end_seconds=None,
    screenshot_interval_seconds=1.0,
    screenshot_start_frame=None,
    screenshot_end_frame=None,
    screenshot_interval_frames=60,
    gbc=False,
):
    gb_memory = GbMemory(skip_bios=False, gb_doctor_test_mode=GB_DR_TEST_MODE)
    cpu = GbZ80Cpu(
        GB_DR_LOG_DUMP,
        gb_doctor_test_mode=GB_DR_TEST_MODE,
        trace_enabled=trace,
    )
    gpu = GbGpu()
    gpu.diagnostics_enabled = gpu_diagnostics
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

    sys_interface = GbSystemInterface(
        gb_memory,
        cpu,
        gpu,
        apu=apu,
        force_cgb_mode=gbc,
    )

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
    screenshot_dir_path = Path(screenshot_dir) if screenshot_dir else None
    if screenshot_dir_path is not None:
        screenshot_dir_path.mkdir(parents=True, exist_ok=True)
    next_screenshot_seconds = screenshot_start_seconds
    next_screenshot_frame = screenshot_start_frame
    stop_seconds = (
        stats['start_seconds'] + max_seconds
        if max_seconds is not None
        else None
    )
    execute_next_operation = cpu.execute_next_operation
    instructions = 0
    pace_frames = not no_display and not uncapped
    next_frame_deadline = stats['start_seconds'] + DMG_FRAME_SECONDS
    next_audio_cycle = DMG_CYCLES_PER_FRAME

    try:
        while True:
            instructions += execute_next_operation()

            if gpu.frame_ready:
                gpu.frame_ready = False
                stats['frames'] += 1
                stats['instructions'] = instructions
                if screenshot_dir_path is not None:
                    elapsed = time.perf_counter() - stats['start_seconds']
                    if screenshot_start_frame is not None:
                        capture_allowed = stats['frames'] >= next_screenshot_frame
                        if (
                            screenshot_end_frame is not None
                            and stats['frames'] > screenshot_end_frame
                        ):
                            capture_allowed = False
                    else:
                        capture_allowed = elapsed >= next_screenshot_seconds
                        if (
                            screenshot_end_seconds is not None
                            and elapsed > screenshot_end_seconds
                        ):
                            capture_allowed = False
                    if capture_allowed:
                        save_gpu_screenshot(
                            gpu,
                            screenshot_dir_path,
                            stats['frames'],
                            elapsed,
                        )
                        if screenshot_start_frame is not None:
                            while next_screenshot_frame <= stats['frames']:
                                next_screenshot_frame += screenshot_interval_frames
                        else:
                            while next_screenshot_seconds <= elapsed:
                                next_screenshot_seconds += screenshot_interval_seconds
                pressed_buttons = apply_scripted_input(
                    sys_interface,
                    scripted_input,
                    stats['frames'],
                )
                if not no_display:
                    pressed_buttons.extend(handle_events(sys_interface))
                    if pressed_buttons and audio_output is not None:
                        audio_output.start_latency_tracking()
                    if audio_enabled and audio_output is not None:
                        cpu_cycle = cpu.clock['m'] * 4
                        frames_due = (
                            (cpu_cycle - next_audio_cycle)
                            // DMG_CYCLES_PER_FRAME
                            + 1
                        )
                        frames_to_drop = max(0, frames_due - 3)
                        for _ in range(frames_to_drop):
                            apu.generate_frame()
                            next_audio_cycle += DMG_CYCLES_PER_FRAME
                        while cpu_cycle >= next_audio_cycle:
                            audio_output.queue(apu.generate_frame())
                            next_audio_cycle += DMG_CYCLES_PER_FRAME
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
            audio_output.print_latency_diagnostics()
            audio_output.print_underrun_diagnostics()
            audio_output.close()
        if not no_display:
            pygame.quit()
        print_run_stats(stats, no_display)
        if opcode_stats:
            print_opcode_stats(cpu)
        if gpu_diagnostics:
            print_gpu_diagnostics(gpu)


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
    pressed_buttons = []
    for button, pressed in scripted_input.get(frame, ()):
        sys_interface.set_button(button, pressed)
        if pressed:
            pressed_buttons.append(button)
    return pressed_buttons


def handle_events(sys_interface):
    """Handle pending pygame events once per displayed frame."""
    pressed_buttons = []
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            raise ExecutionHalted()
        if event.type in (pygame.KEYDOWN, pygame.KEYUP):
            button = KEY_BINDINGS.get(event.key)
            if button:
                pressed = event.type == pygame.KEYDOWN
                sys_interface.set_button(button, pressed)
                if pressed:
                    pressed_buttons.append(button)
    return pressed_buttons


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
        self.start_seconds = time.perf_counter()
        self.underrun_events = 0
        self.underrun_bytes = 0
        self.largest_underrun_bytes = 0
        self.consecutive_underruns = 0
        self.longest_underrun_streak = 0
        self.in_underrun = False
        self.underrun_event_times = deque(maxlen=8)
        self.latency_tracking_started = False
        self.latency_tracking_start_seconds = None
        self.max_tracked_queued_bytes = 0
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
            if (
                self.latency_tracking_started
                and self.queued_bytes > self.max_tracked_queued_bytes
            ):
                self.max_tracked_queued_bytes = self.queued_bytes
            if not self.started and self.queued_bytes >= self.prebuffer_bytes:
                self.started = True
                should_start = True
        if should_start:
            self.device.pause(0)

    def start_latency_tracking(self):
        """Begin tracking maximum queued audio from gameplay input onward."""
        with self.lock:
            if self.latency_tracking_started:
                return
            self.latency_tracking_started = True
            self.latency_tracking_start_seconds = (
                time.perf_counter() - self.start_seconds
            )
            self.max_tracked_queued_bytes = self.queued_bytes

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
                missing_bytes = output_length - output_offset
                output[output_offset:output_length] = bytes(missing_bytes)
                if self.started:
                    self.underruns += 1
                    self.underrun_bytes += missing_bytes
                    self.largest_underrun_bytes = max(
                        self.largest_underrun_bytes,
                        missing_bytes,
                    )
                    self.consecutive_underruns += 1
                    self.longest_underrun_streak = max(
                        self.longest_underrun_streak,
                        self.consecutive_underruns,
                    )
                    if not self.in_underrun:
                        self.in_underrun = True
                        self.underrun_events += 1
                        self.underrun_event_times.append(
                            time.perf_counter() - self.start_seconds
                        )
            else:
                self.in_underrun = False
                self.consecutive_underruns = 0

    def queued_milliseconds(self):
        with self.lock:
            queued_bytes = self.queued_bytes
        return queued_bytes / (SAMPLE_RATE * 4) * 1000

    def print_underrun_diagnostics(self):
        with self.lock:
            events = self.underrun_events
            underrun_bytes = self.underrun_bytes
            largest_bytes = self.largest_underrun_bytes
            longest_streak = self.longest_underrun_streak
            event_times = tuple(self.underrun_event_times)

        if not events:
            print("Audio underrun diagnostics: no starvation detected")
            return

        bytes_per_millisecond = SAMPLE_RATE * 4 / 1000
        event_text = ", ".join(f"{seconds:.2f}s" for seconds in event_times)
        print(
            "Audio underrun diagnostics: "
            f"{events} events, "
            f"{underrun_bytes / bytes_per_millisecond:.1f} ms silence, "
            f"{largest_bytes / bytes_per_millisecond:.1f} ms largest callback, "
            f"{longest_streak} callback max streak"
        )
        print(f"Recent underrun event times: {event_text}")

    def print_latency_diagnostics(self):
        with self.lock:
            tracking_started = self.latency_tracking_started
            tracking_start_seconds = self.latency_tracking_start_seconds
            current_bytes = self.queued_bytes
            max_bytes = self.max_tracked_queued_bytes

        bytes_per_millisecond = SAMPLE_RATE * 4 / 1000
        if not tracking_started:
            print("Audio latency diagnostics: no gameplay input observed")
            return

        print(
            "Audio latency diagnostics: "
            f"tracking since {tracking_start_seconds:.2f}s, "
            f"{current_bytes / bytes_per_millisecond:.1f} ms queued now, "
            f"{max_bytes / bytes_per_millisecond:.1f} ms max queued"
        )

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


def print_gpu_diagnostics(gpu):
    """Print opt-in GPU hot-path diagnostic counters."""
    stats = gpu.diagnostics
    total_scanlines = stats.get('cgb_bg_scanlines', 0)
    print("GPU diagnostics:")
    if total_scanlines:
        bg_seconds = stats.get('cgb_bg_seconds', 0.0)
        sprite_seconds = stats.get('cgb_sprite_seconds', 0.0)
        window_seconds = stats.get('cgb_window_seconds', 0.0)
        print(
            "  CGB render time: "
            f"BG {bg_seconds:.3f}s, "
            f"window {window_seconds:.3f}s, "
            f"sprites {sprite_seconds:.3f}s"
        )
        print(
            "  CGB BG scanlines: "
            f"{total_scanlines:,}, "
            f"{bg_seconds / total_scanlines * 1_000_000:.1f} us/scanline"
        )
    tiles = stats.get('cgb_bg_tiles', 0)
    if tiles:
        simple = stats.get('cgb_bg_attr_zero', 0)
        palette = stats.get('cgb_bg_attr_palette_only', 0)
        bank = stats.get('cgb_bg_attr_bank', 0)
        xflip = stats.get('cgb_bg_attr_xflip', 0)
        yflip = stats.get('cgb_bg_attr_yflip', 0)
        priority = stats.get('cgb_bg_attr_priority', 0)
        print(
            "  CGB BG tiles: "
            f"{tiles:,}; "
            f"attr=0 {simple / tiles * 100:.1f}%, "
            f"palette-only {palette / tiles * 100:.1f}%, "
            f"bank {bank / tiles * 100:.1f}%, "
            f"xflip {xflip / tiles * 100:.1f}%, "
            f"yflip {yflip / tiles * 100:.1f}%, "
            f"priority {priority / tiles * 100:.1f}%"
        )
    row_hits = stats.get('cgb_row_cache_hits', 0)
    row_misses = stats.get('cgb_row_cache_misses', 0)
    palette0_hits = stats.get('cgb_palette0_cache_hits', 0)
    palette0_misses = stats.get('cgb_palette0_cache_misses', 0)
    row_total = row_hits + row_misses
    palette0_total = palette0_hits + palette0_misses
    if row_total or palette0_total:
        row_rate = row_hits / row_total * 100 if row_total else 0
        palette0_rate = (
            palette0_hits / palette0_total * 100 if palette0_total else 0
        )
        print(
            "  CGB row cache: "
            f"general {row_hits:,}/{row_total:,} hits "
            f"({row_rate:.1f}%), "
            f"palette0 {palette0_hits:,}/{palette0_total:,} hits "
            f"({palette0_rate:.1f}%)"
        )
    vram_writes = stats.get('cgb_vram_writes', 0)
    palette_invalidations = (
        stats.get('cgb_bg_palette_invalidations', 0)
        + stats.get('cgb_obj_palette_invalidations', 0)
    )
    if vram_writes or palette_invalidations:
        bg_palette_writes = stats.get('cgb_bg_palette_writes', 0)
        obj_palette_writes = stats.get('cgb_obj_palette_writes', 0)
        bg_redundant = stats.get('cgb_bg_palette_redundant_writes', 0)
        obj_redundant = stats.get('cgb_obj_palette_redundant_writes', 0)
        bg_redundant_pct = (
            bg_redundant / bg_palette_writes * 100
            if bg_palette_writes else 0
        )
        obj_redundant_pct = (
            obj_redundant / obj_palette_writes * 100
            if obj_palette_writes else 0
        )
        print(
            "  CGB invalidation pressure: "
            f"{vram_writes:,} VRAM writes "
            f"({stats.get('cgb_tile_data_writes', 0):,} tile-data, "
            f"{stats.get('cgb_tilemap_writes', 0):,} tilemap), "
            f"{stats.get('cgb_bg_palette_invalidations', 0):,} BG palette "
            f"and {stats.get('cgb_obj_palette_invalidations', 0):,} OBJ "
            "palette invalidations"
        )
        print(
            "  CGB palette writes: "
            f"BG {bg_palette_writes:,} writes "
            f"({bg_redundant:,} redundant, {bg_redundant_pct:.1f}%), "
            f"OBJ {obj_palette_writes:,} writes "
            f"({obj_redundant:,} redundant, {obj_redundant_pct:.1f}%)"
        )
        print(
            "  CGB VRAM writes by PPU mode: "
            f"mode0 {stats.get('cgb_vram_writes_mode0', 0):,}, "
            f"mode1 {stats.get('cgb_vram_writes_mode1', 0):,}, "
            f"mode2 {stats.get('cgb_vram_writes_mode2', 0):,}, "
            f"mode3 {stats.get('cgb_vram_writes_mode3', 0):,}"
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


def save_gpu_screenshot(gpu, directory, frame, elapsed_seconds):
    """Save the current RGB framebuffer as a PNG for visual diagnostics."""
    filename = f"frame_{frame:06d}_{elapsed_seconds:06.2f}s.png"
    surface = pygame.image.frombuffer(
        gpu.screen['rgb'].tobytes(),
        (SCREEN_WIDTH, SCREEN_HEIGHT),
        "RGB",
    )
    pygame.image.save(surface, str(directory / filename))


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
    parser.add_argument(
        "--gpu-diagnostics",
        action="store_true",
        help="print opt-in GPU renderer counters and timing",
    )
    parser.add_argument(
        "--screenshot-dir",
        help="write diagnostic framebuffer PNGs to this directory",
    )
    parser.add_argument(
        "--screenshot-start-seconds",
        type=float,
        default=0.0,
        help="start writing screenshots after this elapsed runtime",
    )
    parser.add_argument(
        "--screenshot-end-seconds",
        type=float,
        help="stop writing screenshots after this elapsed runtime",
    )
    parser.add_argument(
        "--screenshot-interval-seconds",
        type=float,
        default=1.0,
        help="seconds between diagnostic screenshots",
    )
    parser.add_argument(
        "--screenshot-start-frame",
        type=int,
        help="start writing screenshots at this completed emulated frame",
    )
    parser.add_argument(
        "--screenshot-end-frame",
        type=int,
        help="stop writing screenshots after this completed emulated frame",
    )
    parser.add_argument(
        "--screenshot-interval-frames",
        type=int,
        default=60,
        help="completed emulated frames between diagnostic screenshots",
    )
    parser.add_argument(
        "--gbc",
        action="store_true",
        help=(
            "run as Game Boy Color hardware; CGB-only ROMs enable this "
            "automatically"
        ),
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
                gpu_diagnostics=args.gpu_diagnostics,
                screenshot_dir=args.screenshot_dir,
                screenshot_start_seconds=args.screenshot_start_seconds,
                screenshot_end_seconds=args.screenshot_end_seconds,
                screenshot_interval_seconds=args.screenshot_interval_seconds,
                screenshot_start_frame=args.screenshot_start_frame,
                screenshot_end_frame=args.screenshot_end_frame,
                screenshot_interval_frames=args.screenshot_interval_frames,
                gbc=args.gbc,
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
            gpu_diagnostics=args.gpu_diagnostics,
            screenshot_dir=args.screenshot_dir,
            screenshot_start_seconds=args.screenshot_start_seconds,
            screenshot_end_seconds=args.screenshot_end_seconds,
            screenshot_interval_seconds=args.screenshot_interval_seconds,
            screenshot_start_frame=args.screenshot_start_frame,
            screenshot_end_frame=args.screenshot_end_frame,
            screenshot_interval_frames=args.screenshot_interval_frames,
            gbc=args.gbc,
        )
