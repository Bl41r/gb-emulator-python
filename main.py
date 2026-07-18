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
    cpu_diagnostics=False,
    gpu_diagnostics=False,
    audio_diagnostics=False,
    screenshot_dir=None,
    screenshot_start_seconds=0.0,
    screenshot_end_seconds=None,
    screenshot_interval_seconds=1.0,
    screenshot_start_frame=None,
    screenshot_end_frame=None,
    screenshot_interval_frames=60,
    gbc=False,
    bios=None,
    metrics_warmup_seconds=20.0,
    slow_diagnostics=False,
    slow_diagnostics_start_seconds=0.0,
    slow_diagnostics_end_seconds=None,
    slow_diagnostics_after_input_sequence=None,
    slow_diagnostics_input_window_seconds=8.0,
    slow_frame_threshold=1.25,
    slow_diagnostics_limit=12,
    phase_diagnostics=False,
    phase_diagnostics_seconds=5.0,
    pc_sample_range=None,
    pc_sample_limit=20,
):
    gb_memory = GbMemory(skip_bios=False, gb_doctor_test_mode=GB_DR_TEST_MODE)
    cpu = GbZ80Cpu(
        GB_DR_LOG_DUMP,
        gb_doctor_test_mode=GB_DR_TEST_MODE,
        trace_enabled=trace,
    )
    slow_diagnostics_waiting_for_input = (
        slow_diagnostics_after_input_sequence is not None
    )
    slow_diagnostics_sequence_index = 0
    slow_diagnostics_active = (
        slow_diagnostics
        and not slow_diagnostics_waiting_for_input
        and slow_diagnostics_start_seconds <= 0
        and (
            slow_diagnostics_end_seconds is None
            or slow_diagnostics_end_seconds > 0
        )
    )
    cpu.slow_diagnostics_enabled = slow_diagnostics_active
    gpu = GbGpu()
    gpu.diagnostics_enabled = gpu_diagnostics
    cpu.diagnostics_enabled = cpu_diagnostics
    if pc_sample_range is not None:
        cpu.diagnostics_enabled = True
        cpu.pc_sample_start, cpu.pc_sample_end = pc_sample_range
        cpu.pc_sample_limit = pc_sample_limit
    if opcode_stats:
        cpu.opcode_counts = [0] * 256
        cpu.cb_opcode_counts = [0] * 256
    audio_enabled = audio and not no_display and not uncapped
    apu = GbApu(gb_memory.memory) if audio_enabled else None
    if apu is not None:
        apu.diagnostics_enabled = audio_diagnostics

    if GB_DR_TEST_MODE:
        caption = build_window_caption(filename, test_mode=True)
        print("IN TEST MODE")
    else:
        caption = build_window_caption(filename)

    sys_interface = GbSystemInterface(
        gb_memory,
        cpu,
        gpu,
        apu=apu,
        force_cgb_mode=gbc,
        bios_path=bios,
    )

    for component in [cpu, gpu]:
        component.sys_interface = sys_interface

    sys_interface.load_rom_image(filename)
    scripted_input = load_input_script(input_script) if input_script else {}

    window = None
    frame_surface = None
    scaled_surface = None
    display_rgb_view = None
    audio_output = None
    if not no_display:
        # Setup Pygame
        pygame.init()
        window = pygame.display.set_mode((SCREEN_WIDTH * SCALE, SCREEN_HEIGHT * SCALE))
        frame_surface = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
        scaled_surface = pygame.Surface((SCREEN_WIDTH * SCALE, SCREEN_HEIGHT * SCALE))
        display_rgb_view = np.transpose(gpu.screen['rgb'], (1, 0, 2))
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
        'metrics_warmup_seconds': metrics_warmup_seconds,
        'measured_active': metrics_warmup_seconds <= 0,
        'measured_start_seconds': None,
        'measured_frames': 0,
        'measured_drawn_frames': 0,
        'measured_instructions': 0,
        'measured_draw_seconds': 0.0,
        'measured_sleep_seconds': 0.0,
        'audio_generated_frames': 0,
        'audio_queued_frames': 0,
        'audio_dropped_frames': 0,
        'audio_generate_seconds': 0.0,
        'audio_max_generate_seconds': 0.0,
    }
    if stats['measured_active']:
        stats['measured_start_seconds'] = stats['start_seconds']
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
    phase_snapshot = make_phase_snapshot(stats, audio_output)
    phase_start_seconds = stats['start_seconds']
    phase_index = 1
    slow_last_frame_seconds = stats['start_seconds']
    slow_last_underrun_events = 0
    slow_events_printed = 0
    slow_event_limit_reached = False
    if slow_diagnostics_active:
        cpu.reset_slow_diagnostics_window()

    try:
        while True:
            instructions += execute_next_operation()

            if gpu.frame_ready:
                completed_frames = gpu.frame_ready_count
                gpu.frame_ready_count = 0
                gpu.frame_ready = False
                stats['frames'] += completed_frames
                stats['instructions'] = instructions
                now = time.perf_counter()
                slow_frame_elapsed = 0.0
                slow_underrun_delta = 0
                frame_slow_diagnostics_active = slow_diagnostics_active
                if frame_slow_diagnostics_active:
                    slow_frame_elapsed = now - slow_last_frame_seconds
                    slow_last_frame_seconds = now
                    if audio_output is not None:
                        current_underrun_events = audio_output.underrun_events
                        slow_underrun_delta = (
                            current_underrun_events
                            - slow_last_underrun_events
                        )
                        slow_last_underrun_events = current_underrun_events
                slow_activated_this_frame = False
                if (
                    not stats['measured_active']
                    and now - stats['start_seconds'] >= metrics_warmup_seconds
                ):
                    stats['measured_active'] = True
                    slow_activated_this_frame = True
                    stats['measured_start_seconds'] = now
                    stats['measured_instructions'] = instructions
                    if cpu_diagnostics:
                        cpu.diagnostics = {}
                    if gpu_diagnostics:
                        gpu.diagnostics = {}
                    if audio_output is not None:
                        audio_output.reset_diagnostics(track_latency=True)
                    reset_audio_generation_diagnostics(stats)
                    if apu is not None and audio_diagnostics:
                        apu.diagnostics = {}
                    if frame_slow_diagnostics_active:
                        cpu.reset_slow_diagnostics_window()
                        slow_last_frame_seconds = now
                        if audio_output is not None:
                            slow_last_underrun_events = audio_output.underrun_events
                if stats['measured_active']:
                    stats['measured_frames'] += completed_frames
                if frame_slow_diagnostics_active:
                    slow_snapshot = cpu.consume_slow_diagnostics_window()
                    if stats['measured_active'] and not slow_activated_this_frame:
                        expected_seconds = DMG_FRAME_SECONDS * completed_frames
                        slow_ratio = (
                            slow_frame_elapsed / expected_seconds
                            if expected_seconds > 0 else 0.0
                        )
                        is_slow_frame = slow_ratio >= slow_frame_threshold
                        has_underrun = slow_underrun_delta > 0
                        if (
                            (is_slow_frame or has_underrun)
                            and slow_events_printed < slow_diagnostics_limit
                        ):
                            slow_events_printed += 1
                            print_slow_frame_diagnostic(
                                cpu,
                                sys_interface,
                                slow_snapshot,
                                frame=stats['frames'],
                                completed_frames=completed_frames,
                                elapsed_seconds=slow_frame_elapsed,
                                expected_seconds=expected_seconds,
                                underrun_events=slow_underrun_delta,
                                event_number=slow_events_printed,
                            )
                        elif (
                            (is_slow_frame or has_underrun)
                            and not slow_event_limit_reached
                        ):
                            slow_event_limit_reached = True
                            print(
                                "Slow diagnostics: event print limit reached; "
                                "suppressing additional frame snapshots"
                            )
                if slow_diagnostics and not slow_diagnostics_waiting_for_input:
                    elapsed_for_slow_diagnostics = now - stats['start_seconds']
                    next_slow_diagnostics_active = (
                        elapsed_for_slow_diagnostics
                        >= slow_diagnostics_start_seconds
                        and (
                            slow_diagnostics_end_seconds is None
                            or elapsed_for_slow_diagnostics
                            < slow_diagnostics_end_seconds
                        )
                    )
                    if next_slow_diagnostics_active != slow_diagnostics_active:
                        slow_diagnostics_active = next_slow_diagnostics_active
                        cpu.slow_diagnostics_enabled = slow_diagnostics_active
                        if slow_diagnostics_active:
                            cpu.reset_slow_diagnostics_window()
                            slow_last_frame_seconds = now
                            if audio_output is not None:
                                slow_last_underrun_events = (
                                    audio_output.underrun_events
                                )
                if screenshot_dir_path is not None:
                    elapsed = now - stats['start_seconds']
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
                if slow_diagnostics_waiting_for_input and pressed_buttons:
                    for button in pressed_buttons:
                        expected_button = slow_diagnostics_after_input_sequence[
                            slow_diagnostics_sequence_index
                        ]
                        if button == expected_button:
                            slow_diagnostics_sequence_index += 1
                            if slow_diagnostics_sequence_index == len(
                                slow_diagnostics_after_input_sequence
                            ):
                                trigger_elapsed = (
                                    time.perf_counter() - stats['start_seconds']
                                )
                                slow_diagnostics_start_seconds = trigger_elapsed
                                slow_diagnostics_end_seconds = (
                                    trigger_elapsed
                                    + slow_diagnostics_input_window_seconds
                                )
                                slow_diagnostics_waiting_for_input = False
                                slow_diagnostics_active = True
                                cpu.slow_diagnostics_enabled = True
                                cpu.reset_slow_diagnostics_window()
                                slow_last_frame_seconds = time.perf_counter()
                                if audio_output is not None:
                                    slow_last_underrun_events = (
                                        audio_output.underrun_events
                                    )
                                print(
                                    "Slow diagnostics armed after input "
                                    "sequence "
                                    f"{','.join(slow_diagnostics_after_input_sequence)} "
                                    f"at {trigger_elapsed:.2f}s"
                                )
                                break
                        elif button == slow_diagnostics_after_input_sequence[0]:
                            slow_diagnostics_sequence_index = 1
                        else:
                            slow_diagnostics_sequence_index = 0
                if not no_display:
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
                            audio_start = time.perf_counter()
                            apu.generate_frame()
                            record_audio_generation(
                                stats,
                                time.perf_counter() - audio_start,
                                queued=False,
                            )
                            next_audio_cycle += DMG_CYCLES_PER_FRAME
                        while cpu_cycle >= next_audio_cycle:
                            audio_start = time.perf_counter()
                            audio_output.queue(apu.generate_frame())
                            record_audio_generation(
                                stats,
                                time.perf_counter() - audio_start,
                                queued=True,
                            )
                            next_audio_cycle += DMG_CYCLES_PER_FRAME
                    if should_draw_frame(stats['frames'], frameskip):
                        draw_start = time.perf_counter()
                        draw_screen(
                            display_rgb_view,
                            window,
                            frame_surface,
                            scaled_surface,
                        )
                        draw_elapsed = time.perf_counter() - draw_start
                        stats['draw_seconds'] += draw_elapsed
                        stats['drawn_frames'] += 1
                        if stats['measured_active']:
                            stats['measured_draw_seconds'] += draw_elapsed
                            stats['measured_drawn_frames'] += 1
                    if pace_frames:
                        next_frame_deadline, slept = pace_frame(
                            next_frame_deadline,
                            completed_frames,
                        )
                        stats['sleep_seconds'] += slept
                        if stats['measured_active']:
                            stats['measured_sleep_seconds'] += slept
                    update_caption(caption, stats)

                if phase_diagnostics:
                    phase_now = time.perf_counter()
                    if phase_now - phase_start_seconds >= phase_diagnostics_seconds:
                        next_phase_snapshot = make_phase_snapshot(stats, audio_output)
                        print_phase_diagnostic(
                            phase_index,
                            phase_start_seconds - stats['start_seconds'],
                            phase_now - stats['start_seconds'],
                            phase_snapshot,
                            next_phase_snapshot,
                            no_display,
                            audio_output,
                        )
                        phase_snapshot = next_phase_snapshot
                        phase_start_seconds = phase_now
                        phase_index += 1

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
        if audio_diagnostics:
            print_audio_generation_diagnostics(stats)
            if apu is not None:
                print_apu_internal_diagnostics(apu)
        if not no_display:
            pygame.quit()
        print_run_stats(stats, no_display)
        if opcode_stats:
            print_opcode_stats(cpu)
        if cpu_diagnostics:
            print_cpu_diagnostics(cpu)
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

    def reset_diagnostics(self, track_latency=False):
        """Reset audio diagnostics while leaving queued audio intact."""
        with self.lock:
            self.underruns = 0
            self.callbacks = 0
            self.start_seconds = time.perf_counter()
            self.underrun_events = 0
            self.underrun_bytes = 0
            self.largest_underrun_bytes = 0
            self.consecutive_underruns = 0
            self.longest_underrun_streak = 0
            self.in_underrun = False
            self.underrun_event_times.clear()
            self.latency_tracking_started = track_latency
            self.latency_tracking_start_seconds = 0.0 if track_latency else None
            self.max_tracked_queued_bytes = (
                self.queued_bytes if track_latency else 0
            )

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


def reset_audio_generation_diagnostics(stats):
    """Reset APU generation timing counters at the measured warmup boundary."""
    stats['audio_generated_frames'] = 0
    stats['audio_queued_frames'] = 0
    stats['audio_dropped_frames'] = 0
    stats['audio_generate_seconds'] = 0.0
    stats['audio_max_generate_seconds'] = 0.0


def record_audio_generation(stats, elapsed, queued):
    """Track one generated APU frame for audio performance diagnostics."""
    stats['audio_generated_frames'] += 1
    if queued:
        stats['audio_queued_frames'] += 1
    else:
        stats['audio_dropped_frames'] += 1
    stats['audio_generate_seconds'] += elapsed
    if elapsed > stats['audio_max_generate_seconds']:
        stats['audio_max_generate_seconds'] = elapsed


def print_audio_generation_diagnostics(stats):
    """Print timing for APU frame generation."""
    generated = stats.get('audio_generated_frames', 0)
    print("Audio generation diagnostics:")
    if not generated:
        print("  no APU frames generated")
        return

    total_seconds = stats.get('audio_generate_seconds', 0.0)
    print(
        "  APU frames: "
        f"{generated:,} generated, "
        f"{stats.get('audio_queued_frames', 0):,} queued, "
        f"{stats.get('audio_dropped_frames', 0):,} dropped"
    )
    print(
        "  APU time: "
        f"{total_seconds:.3f}s total, "
        f"{total_seconds / generated * 1_000:.3f} ms/frame avg, "
        f"{stats.get('audio_max_generate_seconds', 0.0) * 1_000:.3f} ms max"
    )


def print_apu_internal_diagnostics(apu):
    """Print internal APU timing counters."""
    stats = apu.diagnostics
    frames = stats.get('frames', 0)
    if not frames:
        print("  APU internals: no measured frames")
        return

    total_seconds = stats.get('total_seconds', 0.0)
    mix_seconds = stats.get('mix_seconds', 0.0)
    high_pass_seconds = stats.get('high_pass_seconds', 0.0)
    samples = stats.get('samples', 0)
    events = stats.get('events_applied', 0)
    print(
        "  APU internals: "
        f"{samples:,} samples, "
        f"{events:,} register events, "
        f"{events / frames:.2f} events/frame"
    )
    print(
        "  APU split: "
        f"mix {mix_seconds:.3f}s "
        f"({mix_seconds / total_seconds * 100:.1f}%), "
        f"high-pass {high_pass_seconds:.3f}s "
        f"({high_pass_seconds / total_seconds * 100:.1f}%)"
    )
    active_masks = stats.get('active_masks', {})
    if active_masks:
        labels = ("ch1", "ch2", "ch3", "ch4")
        mask_text = []
        for mask, count in sorted(
            active_masks.items(),
            key=lambda item: item[1],
            reverse=True,
        )[:6]:
            active = "+".join(
                label for bit, label in enumerate(labels) if mask & (1 << bit)
            ) or "none"
            mask_text.append(f"{active} {count / frames * 100:.1f}%")
        print(f"  APU active masks: {', '.join(mask_text)}")


def should_draw_frame(frame_number, frameskip):
    """Return True when this completed emulated frame should be displayed."""
    return (frame_number - 1) % frameskip == 0


def pace_frame(deadline, frame_count=1):
    """Wait for the next DMG frame boundary without accumulating lag."""
    now = time.perf_counter()
    deadline += DMG_FRAME_SECONDS * (frame_count - 1)
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


def build_window_caption(filename, test_mode=False, max_rom_chars=32):
    """Return a compact base window title that leaves room for FPS stats."""
    rom_name = Path(filename).name
    if len(rom_name) > max_rom_chars:
        rom_name = rom_name[:max_rom_chars - 1] + "…"
    mode_suffix = " test" if test_mode else ""
    return f"gb-emu{mode_suffix} - {rom_name}"


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

    if drawn_frames != frames:
        fps_text = f"{fps:.1f} FPS / {draw_fps:.1f} drawn"
    else:
        fps_text = f"{fps:.1f} FPS"

    pygame.display.set_caption(
        f"{base_caption} - {fps_text} - {instructions_per_second:,.0f} instr/s"
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

    if not stats['measured_active']:
        print(
            "Measured stats: "
            f"warmup not completed ({stats['metrics_warmup_seconds']:.1f}s)"
        )
        return

    measured_elapsed = time.perf_counter() - stats['measured_start_seconds']
    measured_elapsed = max(measured_elapsed, 0.000001)
    measured_instructions = stats['instructions'] - stats['measured_instructions']
    measured_emulation_seconds = (
        measured_elapsed
        - stats['measured_draw_seconds']
        - stats['measured_sleep_seconds']
    )
    print(
        "Measured stats "
        f"(after {stats['metrics_warmup_seconds']:.1f}s warmup): "
        f"{stats['measured_frames']} frames, "
        f"{measured_instructions} instructions, "
        f"{measured_elapsed:.2f}s elapsed, "
        f"{stats['measured_frames'] / measured_elapsed:.2f} fps, "
        f"{measured_instructions / measured_elapsed:,.0f} instr/s"
    )
    if not no_display:
        print(
            "Measured rendering: "
            f"{stats['measured_drawn_frames']} drawn frames, "
            f"{stats['measured_draw_seconds']:.2f}s drawing "
            f"({stats['measured_draw_seconds'] / measured_elapsed * 100:.1f}% "
            "of measured), "
            f"{stats['measured_sleep_seconds']:.2f}s pacing, "
            f"{measured_emulation_seconds:.2f}s emulation/event loop"
        )


def make_phase_snapshot(stats, audio_output):
    """Return low-overhead counters for phase/bucket diagnostics."""
    return {
        'seconds': time.perf_counter(),
        'frames': stats['frames'],
        'drawn_frames': stats['drawn_frames'],
        'instructions': stats['instructions'],
        'draw_seconds': stats['draw_seconds'],
        'sleep_seconds': stats['sleep_seconds'],
        'audio_generated_frames': stats['audio_generated_frames'],
        'audio_queued_frames': stats['audio_queued_frames'],
        'audio_dropped_frames': stats['audio_dropped_frames'],
        'audio_generate_seconds': stats['audio_generate_seconds'],
        'audio_underruns': audio_output.underruns if audio_output is not None else 0,
        'audio_underrun_events': (
            audio_output.underrun_events if audio_output is not None else 0
        ),
        'audio_callbacks': audio_output.callbacks if audio_output is not None else 0,
    }


def print_phase_diagnostic(
    phase_index,
    start_elapsed,
    end_elapsed,
    start,
    end,
    no_display,
    audio_output,
):
    """Print low-overhead performance counters for one time bucket."""
    elapsed = max(end['seconds'] - start['seconds'], 0.000001)
    frames = end['frames'] - start['frames']
    drawn_frames = end['drawn_frames'] - start['drawn_frames']
    instructions = end['instructions'] - start['instructions']
    draw_seconds = end['draw_seconds'] - start['draw_seconds']
    sleep_seconds = end['sleep_seconds'] - start['sleep_seconds']
    emulation_seconds = elapsed - draw_seconds - sleep_seconds
    generated = end['audio_generated_frames'] - start['audio_generated_frames']
    queued = end['audio_queued_frames'] - start['audio_queued_frames']
    dropped = end['audio_dropped_frames'] - start['audio_dropped_frames']
    audio_seconds = end['audio_generate_seconds'] - start['audio_generate_seconds']
    underruns = end['audio_underruns'] - start['audio_underruns']
    underrun_events = end['audio_underrun_events'] - start['audio_underrun_events']
    callbacks = end['audio_callbacks'] - start['audio_callbacks']
    queue_ms = audio_output.queued_milliseconds() if audio_output is not None else 0.0
    audio_avg_ms = (audio_seconds / generated * 1000) if generated else 0.0
    print(
        "Phase diagnostic "
        f"#{phase_index} ({start_elapsed:.1f}-{end_elapsed:.1f}s): "
        f"{frames} frames, {frames / elapsed:.2f} fps, "
        f"{instructions / elapsed:,.0f} instr/s"
    )
    if not no_display:
        print(
            "  phase timing: "
            f"{drawn_frames} drawn, "
            f"{draw_seconds:.3f}s draw, "
            f"{sleep_seconds:.3f}s pace, "
            f"{emulation_seconds:.3f}s emu/event"
        )
    if generated or callbacks or underruns:
        print(
            "  phase audio: "
            f"{generated} generated ({queued} queued, {dropped} dropped), "
            f"{audio_avg_ms:.3f} ms/frame APU, "
            f"{underrun_events} underrun events, "
            f"{underruns} underrun callbacks, "
            f"{callbacks} callbacks, "
            f"{queue_ms:.1f} ms queued"
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


def print_slow_frame_diagnostic(
    cpu,
    sys_interface,
    snapshot,
    frame,
    completed_frames,
    elapsed_seconds,
    expected_seconds,
    underrun_events,
    event_number,
    limit=8,
):
    """Print the hot opcodes/PCs for one slow or underrun-adjacent frame."""
    opcode_counts = snapshot['opcode_counts']
    cb_opcode_counts = snapshot['cb_opcode_counts']
    pc_counts = snapshot['pc_counts']
    dispatches = snapshot['instructions']
    ratio = elapsed_seconds / expected_seconds if expected_seconds else 0.0
    reasons = []
    if ratio >= 1.0:
        reasons.append(f"{ratio:.2f}x frame budget")
    if underrun_events:
        reasons.append(f"{underrun_events} audio underrun event(s)")
    reason_text = ", ".join(reasons) if reasons else "manual snapshot"
    print(
        "Slow diagnostic "
        f"#{event_number}: frame {frame} "
        f"({completed_frames} completed), "
        f"{elapsed_seconds * 1000:.1f} ms elapsed vs "
        f"{expected_seconds * 1000:.1f} ms expected; "
        f"{dispatches:,} CPU dispatches; {reason_text}"
    )

    ranked_ops = sorted(
        enumerate(opcode_counts),
        key=lambda item: item[1],
        reverse=True,
    )
    if ranked_ops and ranked_ops[0][1]:
        print("  Hot opcodes in this frame:")
        for opcode, count in ranked_ops[:limit]:
            if not count:
                break
            print(f"    {format_slow_opcode(cpu, opcode):<28} {count:>8,}")

    ranked_cb = sorted(
        enumerate(cb_opcode_counts),
        key=lambda item: item[1],
        reverse=True,
    )
    if ranked_cb and ranked_cb[0][1]:
        print("  Hot CB opcodes in this frame:")
        for opcode, count in ranked_cb[:min(limit, 5)]:
            if not count:
                break
            handler, args = cpu.cb_map[opcode]
            print(
                f"    CB {opcode:02X} {handler.__name__:<15} "
                f"{count:>8,}  {args}"
            )

    ranked_pcs = sorted(
        pc_counts.items(),
        key=lambda item: item[1],
        reverse=True,
    )
    if ranked_pcs:
        print("  Hot PCs in this frame:")
        for pc, count in ranked_pcs[:limit]:
            print(
                f"    {pc:04X}: {count:>8,}  "
                f"{format_memory_window(sys_interface, pc)}"
            )


def format_slow_opcode(cpu, opcode):
    """Format normal and pseudo opcodes for slow-frame diagnostics."""
    if opcode < 0x100:
        handler, _args = cpu.opcode_map[opcode]
        return f"{opcode:02X} {handler.__name__}"
    if opcode >= 0x200:
        return f"{opcode:03X} HRAM poll pseudo"
    pseudo_index = opcode - 0x100
    if 0 <= pseudo_index < len(cpu.pseudo_opcode_table):
        return f"{opcode:03X} {cpu.pseudo_opcode_table[pseudo_index].__name__}"
    return f"{opcode:03X} pseudo"


def parse_pc_sample_range(value):
    """Parse an inclusive diagnostic PC range like 3A71-3A83."""
    try:
        start_text, end_text = value.split("-", 1)
        start = int(start_text, 16)
        end = int(end_text, 16)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "expected hex range like 3A71-3A83"
        ) from error
    if not 0 <= start <= 0xFFFF or not 0 <= end <= 0xFFFF or end < start:
        raise argparse.ArgumentTypeError(
            "expected an inclusive 16-bit hex range like 3A71-3A83"
        )
    return start, end


def parse_button_sequence(value):
    """Parse a comma-separated button sequence for diagnostics."""
    buttons = tuple(part.strip().lower() for part in value.split(","))
    valid_buttons = {"right", "left", "up", "down", "a", "b", "select", "start"}
    if not buttons or any(not button for button in buttons):
        raise argparse.ArgumentTypeError(
            "expected comma-separated buttons, for example start,a,a,a"
        )
    unknown = [button for button in buttons if button not in valid_buttons]
    if unknown:
        raise argparse.ArgumentTypeError(
            "unknown button(s): {}; expected one of {}".format(
                ", ".join(unknown),
                ", ".join(sorted(valid_buttons)),
            )
        )
    return buttons


def format_memory_window(sys_interface, pc, before=2, after=8):
    """Format live memory bytes around a hot PC without invoking MMIO reads."""
    start = max(0, pc - before)
    end = min(0x10000, pc + after)
    parts = []
    for address in range(start, end):
        byte = diagnostic_memory_byte(sys_interface, address)
        if address == pc:
            parts.append(f"[{byte:02X}]")
        else:
            parts.append(f"{byte:02X}")
    return f"{memory_region_name(pc):>6}  " + " ".join(parts)


def diagnostic_memory_byte(sys_interface, address):
    """Read bytes for diagnostics without triggering MMIO side effects."""
    if (
        sys_interface.boot_rom_enabled
        and sys_interface.boot_rom is not None
        and address < len(sys_interface.boot_rom)
    ):
        return sys_interface.boot_rom[address]
    if sys_interface.cartridge is not None and address < 0x8000:
        return sys_interface.cartridge.rom_window[address]
    return sys_interface.raw_memory[address]


def memory_region_name(address):
    """Return a compact Game Boy memory-region label for diagnostics."""
    if address < 0x4000:
        return "ROM0"
    if address < 0x8000:
        return "ROMX"
    if address < 0xA000:
        return "VRAM"
    if address < 0xC000:
        return "SRAM"
    if address < 0xE000:
        return "WRAM"
    if address < 0xFE00:
        return "ECHO"
    if address < 0xFEA0:
        return "OAM"
    if address < 0xFF00:
        return "BAD"
    if address < 0xFF80:
        return "IO"
    if address < 0xFFFF:
        return "HRAM"
    return "IE"


def print_cpu_diagnostics(cpu, limit=12):
    """Print opt-in CPU fast-path diagnostic counters."""
    stats = cpu.diagnostics
    print("CPU diagnostics:")

    ly_calls = stats.get('pseudo_ly_compare_b_calls', 0)
    if ly_calls:
        loops = stats.get('pseudo_ly_compare_b_loops', 0)
        batches = stats.get('pseudo_ly_compare_b_loop_batches', 0)
        m_cycles = stats.get('pseudo_ly_compare_b_m_cycles', 0)
        boundary_fallbacks = stats.get(
            'pseudo_ly_compare_b_boundary_fallbacks',
            0,
        )
        aggressive_batches = stats.get(
            'pseudo_ly_compare_b_aggressive_batches',
            0,
        )
        aggressive_blocked_irq = stats.get(
            'pseudo_ly_compare_b_aggressive_blocked_irq',
            0,
        )
        avg_loop_batch = loops / batches if batches else 0
        print(
            "  LY compare-B pseudo-op: "
            f"{ly_calls:,} calls, "
            f"{loops:,} folded loop iterations, "
            f"{avg_loop_batch:.1f} avg loops/batch, "
            f"{m_cycles:,} M-cycles folded/tracked, "
            f"{boundary_fallbacks:,} boundary fallbacks, "
            f"{aggressive_batches:,} aggressive batches, "
            f"{aggressive_blocked_irq:,} IRQ-blocked aggressive attempts"
        )
        ly_pcs = stats.get('pseudo_ly_compare_b_pcs', {})
        if ly_pcs:
            print("  Top LY compare-B pseudo-op PCs:")
            for pc, count in sorted(
                ly_pcs.items(),
                key=lambda item: item[1],
                reverse=True,
            )[:limit]:
                percent = count / ly_calls * 100
                print(f"    {pc:04X}: {count:>10,}  {percent:>5.2f}%")

    poll_calls = stats.get('pseudo_hram_poll_calls', 0)
    if poll_calls:
        print(
            "  HRAM poll pseudo-op: "
            f"{poll_calls:,} calls, "
            f"{stats.get('pseudo_hram_poll_instr', 0):,} folded instr, "
            f"{stats.get('pseudo_hram_poll_fallbacks', 0):,} fallbacks"
        )

    cp_hl_calls = stats.get('pseudo_cp_hl_calls', 0)
    if cp_hl_calls:
        print(f"  CP (HL) loop pseudo-op: {cp_hl_calls:,} calls")

    stat_poll_calls = stats.get('pseudo_stat_mode_poll_calls', 0)
    if stat_poll_calls:
        loops = stats.get('pseudo_stat_mode_poll_loops', 0)
        batches = stats.get('pseudo_stat_mode_poll_batches', 0)
        m_cycles = stats.get('pseudo_stat_mode_poll_m_cycles', 0)
        fallbacks = stats.get('pseudo_stat_mode_poll_fallbacks', 0)
        boundary_fallbacks = stats.get(
            'pseudo_stat_mode_poll_boundary_fallbacks',
            0,
        )
        exits = stats.get('pseudo_stat_mode_poll_exits', 0)
        avg_loops = loops / batches if batches else 0
        print(
            "  STAT mode poll pseudo-op: "
            f"{stat_poll_calls:,} calls, "
            f"{loops:,} folded loop iterations, "
            f"{avg_loops:.1f} avg loops/batch, "
            f"{m_cycles:,} M-cycles folded/tracked, "
            f"{exits:,} exits, "
            f"{fallbacks:,} fallbacks, "
            f"{boundary_fallbacks:,} boundary fallbacks"
        )

    ly_zero_calls = stats.get('pseudo_ly_zero_calls', 0)
    if ly_zero_calls:
        loops = stats.get('pseudo_ly_zero_loops', 0)
        batches = stats.get('pseudo_ly_zero_batches', 0)
        m_cycles = stats.get('pseudo_ly_zero_m_cycles', 0)
        exits = stats.get('pseudo_ly_zero_exits', 0)
        fallbacks = stats.get('pseudo_ly_zero_fallbacks', 0)
        boundary_fallbacks = stats.get('pseudo_ly_zero_boundary_fallbacks', 0)
        aggressive_batches = stats.get(
            'pseudo_ly_zero_aggressive_batches',
            0,
        )
        aggressive_blocked_irq = stats.get(
            'pseudo_ly_zero_aggressive_blocked_irq',
            0,
        )
        avg_loops = loops / batches if batches else 0
        print(
            "  LY zero pseudo-op: "
            f"{ly_zero_calls:,} calls, "
            f"{loops:,} folded loop iterations, "
            f"{avg_loops:.1f} avg loops/batch, "
            f"{m_cycles:,} M-cycles folded/tracked, "
            f"{exits:,} exits, "
            f"{fallbacks:,} fallbacks, "
            f"{boundary_fallbacks:,} boundary fallbacks, "
            f"{aggressive_batches:,} aggressive batches, "
            f"{aggressive_blocked_irq:,} IRQ-blocked aggressive attempts"
        )
        ly_zero_pcs = stats.get('pseudo_ly_zero_pcs', {})
        if ly_zero_pcs:
            print("  Top LY zero pseudo-op PCs:")
            for pc, count in sorted(
                ly_zero_pcs.items(),
                key=lambda item: item[1],
                reverse=True,
            )[:limit]:
                percent = count / ly_zero_calls * 100
                print(f"    {pc:04X}: {count:>10,}  {percent:>5.2f}%")

    dec_a_calls = stats.get('pseudo_dec_a_loop_calls', 0)
    if dec_a_calls:
        iterations = stats.get('pseudo_dec_a_loop_iterations', 0)
        m_cycles = stats.get('pseudo_dec_a_loop_m_cycles', 0)
        avg_iterations = iterations / dec_a_calls if dec_a_calls else 0
        print(
            "  DEC A loop pseudo-op: "
            f"{dec_a_calls:,} calls, "
            f"{iterations:,} iterations, "
            f"{avg_iterations:.1f} avg iterations/call, "
            f"{m_cycles:,} M-cycles folded/tracked"
        )

    bit_decode_calls = stats.get('pseudo_rom_bit_decode_calls', 0)
    if bit_decode_calls:
        iterations = stats.get('pseudo_rom_bit_decode_iterations', 0)
        m_cycles = stats.get('pseudo_rom_bit_decode_m_cycles', 0)
        avg_iterations = iterations / bit_decode_calls if bit_decode_calls else 0
        print(
            "  ROM bit-decode pseudo-op: "
            f"{bit_decode_calls:,} calls, "
            f"{iterations:,} decoder iterations, "
            f"{avg_iterations:.1f} avg iterations/call, "
            f"{m_cycles:,} M-cycles folded/tracked, "
            f"{stats.get('pseudo_rom_bit_decode_fallbacks', 0):,} fallbacks, "
            f"{stats.get('pseudo_rom_bit_decode_limit_exits', 0):,} limit exits"
        )

    cb46_count = stats.get('cb46_count', 0)
    if cb46_count:
        folded = stats.get('cb46_branch_folded', 0)
        print(
            f"  CB 46 BIT 0,(HL): {cb46_count:,} executions, "
            f"{folded:,} branch folds"
        )
        cb46_pcs = stats.get('cb46_pcs', {})
        if cb46_pcs:
            print(f"  Top CB 46 PCs:")
            for pc, count in sorted(
                cb46_pcs.items(),
                key=lambda item: item[1],
                reverse=True,
            )[:limit]:
                percent = count / cb46_count * 100
                print(f"    {pc:04X}: {count:>10,}  {percent:>5.2f}%")

    pc_sample_hits = stats.get('pc_sample_hits', 0)
    if pc_sample_hits:
        print(f"  PC sample range: {pc_sample_hits:,} hits")
        sampled_pcs = stats.get('pc_sample_pcs', {})
        if sampled_pcs:
            print("  Top sampled PCs:")
            for pc, count in sorted(
                sampled_pcs.items(),
                key=lambda item: item[1],
                reverse=True,
            )[:limit]:
                percent = count / pc_sample_hits * 100
                print(f"    {pc:04X}: {count:>10,}  {percent:>5.2f}%")
        samples = stats.get('pc_sample_registers', [])
        if samples:
            print("  Sampled register states:")
            for (
                pc,
                a,
                f,
                b,
                c,
                d,
                e,
                h,
                l,
                sp,
                ly,
                linemode,
            ) in samples:
                print(
                    f"    PC:{pc:04X} AF:{a:02X}{f:02X} "
                    f"BC:{b:02X}{c:02X} DE:{d:02X}{e:02X} "
                    f"HL:{h:02X}{l:02X} SP:{sp:04X} "
                    f"LY:{ly:02X} mode:{linemode}"
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
    sprite_scanlines = stats.get('cgb_sprite_scanlines', 0)
    if sprite_scanlines:
        sprite_seconds = stats.get('cgb_sprite_seconds', 0.0)
        empty_scanlines = stats.get('cgb_sprite_empty_scanlines', 0)
        object_rows = stats.get('cgb_sprite_object_rows', 0)
        print(
            "  CGB sprite scanlines: "
            f"{sprite_scanlines:,}, "
            f"{sprite_seconds / sprite_scanlines * 1_000_000:.1f} us/scanline, "
            f"{empty_scanlines / sprite_scanlines * 100:.1f}% empty, "
            f"{object_rows / sprite_scanlines:.2f} obj rows/line"
        )
    sprite_pixels = stats.get('cgb_sprite_pixels_tested', 0)
    if sprite_pixels:
        offscreen = stats.get('cgb_sprite_pixels_offscreen', 0)
        claimed = stats.get('cgb_sprite_pixels_claimed', 0)
        transparent = stats.get('cgb_sprite_pixels_transparent', 0)
        hidden = stats.get('cgb_sprite_pixels_priority_hidden', 0)
        drawn = stats.get('cgb_sprite_pixels_drawn', 0)
        print(
            "  CGB sprite pixels: "
            f"{sprite_pixels:,} tested; "
            f"{offscreen / sprite_pixels * 100:.1f}% offscreen, "
            f"{claimed / sprite_pixels * 100:.1f}% claimed, "
            f"{transparent / sprite_pixels * 100:.1f}% transparent, "
            f"{hidden / sprite_pixels * 100:.1f}% priority-hidden, "
            f"{drawn / sprite_pixels * 100:.1f}% drawn"
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
        redundant_vram = stats.get('cgb_vram_redundant_writes', 0)
        if redundant_vram:
            print(
                "  CGB redundant VRAM writes skipped: "
                f"{redundant_vram:,} total "
                f"({stats.get('cgb_tile_data_redundant_writes', 0):,} "
                "tile-data, "
                f"{stats.get('cgb_tilemap_redundant_writes', 0):,} tilemap)"
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


def draw_screen(display_rgb_view, screen, frame_surface, scaled_surface):
    """Draw the GPU buffer to the Pygame window using fast blitting."""
    pygame.surfarray.blit_array(
        frame_surface,
        display_rgb_view,
    )
    pygame.transform.scale(
        frame_surface,
        (SCREEN_WIDTH * SCALE, SCREEN_HEIGHT * SCALE),
        scaled_surface,
    )
    screen.blit(scaled_surface, (0, 0))
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
        "--metrics-warmup-seconds",
        type=float,
        default=20.0,
        help=(
            "ignore the first N real-time seconds in measured FPS/audio "
            "diagnostics (default: 20)"
        ),
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
        "--cpu-diagnostics",
        action="store_true",
        help="print opt-in CPU fast-path counters without disabling fast paths",
    )
    parser.add_argument(
        "--gpu-diagnostics",
        action="store_true",
        help="print opt-in GPU renderer counters and timing",
    )
    parser.add_argument(
        "--audio-diagnostics",
        action="store_true",
        help="print opt-in APU generation timing counters",
    )
    parser.add_argument(
        "--slow-diagnostics",
        action="store_true",
        help=(
            "print per-frame opcode/PC snapshots when a frame is slow or "
            "audio underruns"
        ),
    )
    parser.add_argument(
        "--slow-frame-threshold",
        type=float,
        default=1.25,
        help=(
            "slow diagnostic trigger as a multiple of one frame budget "
            "(default: 1.25)"
        ),
    )
    parser.add_argument(
        "--slow-diagnostics-start-seconds",
        type=float,
        default=0.0,
        help=(
            "elapsed runtime before collecting slow frame snapshots "
            "(default: 0)"
        ),
    )
    parser.add_argument(
        "--slow-diagnostics-end-seconds",
        type=float,
        help="elapsed runtime after which slow frame snapshots stop",
    )
    parser.add_argument(
        "--slow-diagnostics-after-input-sequence",
        type=parse_button_sequence,
        help=(
            "arm slow diagnostics after a comma-separated button sequence, "
            "for example start,a,a,a"
        ),
    )
    parser.add_argument(
        "--slow-diagnostics-input-window-seconds",
        type=float,
        default=8.0,
        help=(
            "seconds to collect after --slow-diagnostics-after-input-sequence "
            "fires (default: 8)"
        ),
    )
    parser.add_argument(
        "--slow-diagnostics-limit",
        type=int,
        default=12,
        help="maximum slow diagnostic frame snapshots to print (default: 12)",
    )
    parser.add_argument(
        "--phase-diagnostics",
        action="store_true",
        help=(
            "print low-overhead FPS/audio buckets for spotting front-loaded "
            "slowdowns"
        ),
    )
    parser.add_argument(
        "--phase-diagnostics-seconds",
        type=float,
        default=5.0,
        help="seconds per phase diagnostic bucket (default: 5)",
    )
    parser.add_argument(
        "--pc-sample-range",
        type=parse_pc_sample_range,
        help=(
            "inclusive hex PC range to sample in CPU diagnostics, "
            "for example 3A71-3A83"
        ),
    )
    parser.add_argument(
        "--pc-sample-limit",
        type=int,
        default=20,
        help="maximum register samples to keep for --pc-sample-range",
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
    parser.add_argument(
        "--bios",
        help=(
            "optional path to a 256-byte DMG or 2304-byte GBC boot ROM; "
            "a GBC boot ROM runs the game as GBC hardware"
        ),
    )
    args = parser.parse_args()
    if args.frameskip < 1:
        parser.error("--frameskip must be 1 or greater")
    if not 0 <= args.volume <= 100:
        parser.error("--volume must be between 0 and 100")
    if args.metrics_warmup_seconds < 0:
        parser.error("--metrics-warmup-seconds must be 0 or greater")
    if args.slow_frame_threshold <= 0:
        parser.error("--slow-frame-threshold must be greater than 0")
    if args.slow_diagnostics_start_seconds < 0:
        parser.error("--slow-diagnostics-start-seconds must be 0 or greater")
    if (
        args.slow_diagnostics_end_seconds is not None
        and args.slow_diagnostics_end_seconds
        <= args.slow_diagnostics_start_seconds
    ):
        parser.error(
            "--slow-diagnostics-end-seconds must be greater than "
            "--slow-diagnostics-start-seconds"
        )
    if args.slow_diagnostics_input_window_seconds <= 0:
        parser.error("--slow-diagnostics-input-window-seconds must be greater than 0")
    if args.slow_diagnostics_limit < 1:
        parser.error("--slow-diagnostics-limit must be 1 or greater")
    if args.phase_diagnostics_seconds <= 0:
        parser.error("--phase-diagnostics-seconds must be greater than 0")
    if args.pc_sample_limit < 1:
        parser.error("--pc-sample-limit must be 1 or greater")

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
                cpu_diagnostics=args.cpu_diagnostics,
                gpu_diagnostics=args.gpu_diagnostics,
                audio_diagnostics=args.audio_diagnostics,
                screenshot_dir=args.screenshot_dir,
                screenshot_start_seconds=args.screenshot_start_seconds,
                screenshot_end_seconds=args.screenshot_end_seconds,
                screenshot_interval_seconds=args.screenshot_interval_seconds,
                screenshot_start_frame=args.screenshot_start_frame,
                screenshot_end_frame=args.screenshot_end_frame,
                screenshot_interval_frames=args.screenshot_interval_frames,
                gbc=args.gbc,
                bios=args.bios,
                metrics_warmup_seconds=args.metrics_warmup_seconds,
                slow_diagnostics=args.slow_diagnostics,
                slow_diagnostics_start_seconds=(
                    args.slow_diagnostics_start_seconds
                ),
                slow_diagnostics_end_seconds=args.slow_diagnostics_end_seconds,
                slow_diagnostics_after_input_sequence=(
                    args.slow_diagnostics_after_input_sequence
                ),
                slow_diagnostics_input_window_seconds=(
                    args.slow_diagnostics_input_window_seconds
                ),
                slow_frame_threshold=args.slow_frame_threshold,
                slow_diagnostics_limit=args.slow_diagnostics_limit,
                phase_diagnostics=args.phase_diagnostics,
                phase_diagnostics_seconds=args.phase_diagnostics_seconds,
                pc_sample_range=args.pc_sample_range,
                pc_sample_limit=args.pc_sample_limit,
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
            cpu_diagnostics=args.cpu_diagnostics,
            gpu_diagnostics=args.gpu_diagnostics,
            audio_diagnostics=args.audio_diagnostics,
            screenshot_dir=args.screenshot_dir,
            screenshot_start_seconds=args.screenshot_start_seconds,
            screenshot_end_seconds=args.screenshot_end_seconds,
            screenshot_interval_seconds=args.screenshot_interval_seconds,
            screenshot_start_frame=args.screenshot_start_frame,
            screenshot_end_frame=args.screenshot_end_frame,
            screenshot_interval_frames=args.screenshot_interval_frames,
            gbc=args.gbc,
            bios=args.bios,
            metrics_warmup_seconds=args.metrics_warmup_seconds,
            slow_diagnostics=args.slow_diagnostics,
            slow_diagnostics_start_seconds=args.slow_diagnostics_start_seconds,
            slow_diagnostics_end_seconds=args.slow_diagnostics_end_seconds,
            slow_diagnostics_after_input_sequence=(
                args.slow_diagnostics_after_input_sequence
            ),
            slow_diagnostics_input_window_seconds=(
                args.slow_diagnostics_input_window_seconds
            ),
            slow_frame_threshold=args.slow_frame_threshold,
            slow_diagnostics_limit=args.slow_diagnostics_limit,
            phase_diagnostics=args.phase_diagnostics,
            phase_diagnostics_seconds=args.phase_diagnostics_seconds,
            pc_sample_range=args.pc_sample_range,
            pc_sample_limit=args.pc_sample_limit,
        )
