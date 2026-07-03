"""DMG audio processing unit implementation."""

from array import array

import numpy as np


DMG_CLOCK_HZ = 4_194_304
DMG_CYCLES_PER_FRAME = 70_224
SAMPLE_RATE = 48_000
FRAME_SEQUENCER_HZ = 512

NR10 = 0xFF10
NR11 = 0xFF11
NR12 = 0xFF12
NR13 = 0xFF13
NR14 = 0xFF14
NR21 = 0xFF16
NR22 = 0xFF17
NR23 = 0xFF18
NR24 = 0xFF19
NR30 = 0xFF1A
NR31 = 0xFF1B
NR32 = 0xFF1C
NR33 = 0xFF1D
NR34 = 0xFF1E
NR41 = 0xFF20
NR42 = 0xFF21
NR43 = 0xFF22
NR44 = 0xFF23
NR50 = 0xFF24
NR51 = 0xFF25
NR52 = 0xFF26
WAVE_RAM_START = 0xFF30
WAVE_RAM_END = 0xFF3F

DUTY_RATIOS = (0.125, 0.25, 0.5, 0.75)
NOISE_DIVISORS = (0.5, 1, 2, 3, 4, 5, 6, 7)


def _create_noise_jump_tables(width_mode):
    """Build compact LFSR lookup tables for jumps of 1, 2, 4, ... ticks."""
    first = array('H')
    append = first.append
    for lfsr in range(0x8000):
        feedback = (lfsr ^ (lfsr >> 1)) & 1
        advanced = (lfsr >> 1) | (feedback << 14)
        if width_mode:
            advanced = (advanced & ~(1 << 6)) | (feedback << 6)
        append(advanced)

    tables = [first]
    for _ in range(5):
        previous = tables[-1]
        tables.append(array(
            'H',
            (previous[previous[lfsr]] for lfsr in range(0x8000)),
        ))
    return tuple(tables)


NOISE_JUMP_TABLES_15BIT = _create_noise_jump_tables(False)
NOISE_JUMP_TABLES_7BIT = _create_noise_jump_tables(True)


class SquareChannel(object):
    """One DMG pulse channel."""

    def __init__(self, duty_address, envelope_address, frequency_low, control):
        self.duty_address = duty_address
        self.envelope_address = envelope_address
        self.frequency_low = frequency_low
        self.control = control
        self.enabled = False
        self.phase = 0.0
        self.phase_step = 0.0
        self.length_counter = 0
        self.volume = 0
        self.envelope_period = 0
        self.envelope_timer = 0
        self.envelope_increase = False
        self.duty_ratio = DUTY_RATIOS[0]

    def refresh(self, memory):
        """Refresh frequency and duty values that can change while playing."""
        duty_value = memory[self.duty_address]
        self.duty_ratio = DUTY_RATIOS[(duty_value >> 6) & 0x03]
        frequency = (
            memory[self.frequency_low]
            | ((memory[self.control] & 0x07) << 8)
        )
        denominator = 2048 - frequency
        self.phase_step = (
            131_072.0 / denominator / SAMPLE_RATE
            if denominator > 0
            else 0.0
        )

    def trigger(self, memory):
        """Restart the channel from its current register settings."""
        envelope = memory[self.envelope_address]
        if not envelope & 0xF8:
            self.enabled = False
            return

        self.enabled = True
        self.phase = 0.0
        self.length_counter = 64 - (memory[self.duty_address] & 0x3F)
        if self.length_counter == 0:
            self.length_counter = 64
        self.volume = envelope >> 4
        self.envelope_increase = bool(envelope & 0x08)
        self.envelope_period = envelope & 0x07
        self.envelope_timer = self.envelope_period or 8
        self.refresh(memory)

    def clock_length(self, memory):
        if (
            self.enabled
            and memory[self.control] & 0x40
            and self.length_counter > 0
        ):
            self.length_counter -= 1
            if self.length_counter == 0:
                self.enabled = False

    def clock_envelope(self):
        if not self.enabled or self.envelope_period == 0:
            return

        self.envelope_timer -= 1
        if self.envelope_timer > 0:
            return
        self.envelope_timer = self.envelope_period

        if self.envelope_increase and self.volume < 15:
            self.volume += 1
        elif not self.envelope_increase and self.volume > 0:
            self.volume -= 1

    def sample(self):
        if not self.enabled or self.volume == 0:
            return 0

        value = self.volume if self.phase < self.duty_ratio else -self.volume
        self.phase += self.phase_step
        if self.phase >= 1.0:
            self.phase -= int(self.phase)
        return value


class WaveChannel(object):
    """DMG programmable 32-sample wave channel."""

    def __init__(self):
        self.enabled = False
        self.phase = 0.0
        self.phase_step = 0.0
        self.length_counter = 0

    def refresh(self, memory):
        frequency = memory[NR33] | ((memory[NR34] & 0x07) << 8)
        denominator = 2048 - frequency
        self.phase_step = (
            2_097_152.0 / denominator / SAMPLE_RATE
            if denominator > 0
            else 0.0
        )

    def trigger(self, memory):
        if not memory[NR30] & 0x80:
            self.enabled = False
            return
        self.enabled = True
        self.phase = 0.0
        self.length_counter = 256 - memory[NR31]
        if self.length_counter == 0:
            self.length_counter = 256
        self.refresh(memory)

    def clock_length(self, memory):
        if (
            self.enabled
            and memory[NR34] & 0x40
            and self.length_counter > 0
        ):
            self.length_counter -= 1
            if self.length_counter == 0:
                self.enabled = False

    def sample(self, memory):
        if not self.enabled:
            return 0

        phase = self.phase
        sample_index = int(phase) & 31
        packed = memory[WAVE_RAM_START + (sample_index >> 1)]
        sample = packed >> 4 if not (sample_index & 1) else packed & 0x0F
        phase += self.phase_step
        if phase >= 32.0:
            phase %= 32.0
        self.phase = phase

        level = (memory[NR32] >> 5) & 0x03
        if level == 0:
            return 0
        return (sample * 2 - 15) >> (level - 1)


class NoiseChannel(object):
    """DMG pseudo-random noise channel."""

    def __init__(self):
        self.enabled = False
        self.phase = 0.0
        self.phase_step = 0.0
        self.length_counter = 0
        self.volume = 0
        self.envelope_period = 0
        self.envelope_timer = 0
        self.envelope_increase = False
        self.lfsr = 0x7FFF
        self.width_mode = False

    def refresh(self, memory):
        polynomial = memory[NR43]
        divisor = NOISE_DIVISORS[polynomial & 0x07]
        shift = polynomial >> 4
        frequency = 524_288.0 / divisor / (2 ** (shift + 1))
        self.phase_step = frequency / SAMPLE_RATE
        self.width_mode = bool(polynomial & 0x08)

    def trigger(self, memory):
        envelope = memory[NR42]
        if not envelope & 0xF8:
            self.enabled = False
            return

        self.enabled = True
        self.phase = 0.0
        self.lfsr = 0x7FFF
        self.length_counter = 64 - (memory[NR41] & 0x3F)
        if self.length_counter == 0:
            self.length_counter = 64
        self.volume = envelope >> 4
        self.envelope_increase = bool(envelope & 0x08)
        self.envelope_period = envelope & 0x07
        self.envelope_timer = self.envelope_period or 8
        self.refresh(memory)

    def clock_length(self, memory):
        if (
            self.enabled
            and memory[NR44] & 0x40
            and self.length_counter > 0
        ):
            self.length_counter -= 1
            if self.length_counter == 0:
                self.enabled = False

    def clock_envelope(self):
        if not self.enabled or self.envelope_period == 0:
            return
        self.envelope_timer -= 1
        if self.envelope_timer > 0:
            return
        self.envelope_timer = self.envelope_period
        if self.envelope_increase and self.volume < 15:
            self.volume += 1
        elif not self.envelope_increase and self.volume > 0:
            self.volume -= 1

    def sample(self):
        if not self.enabled:
            return 0

        phase = self.phase + self.phase_step
        steps = int(phase)
        if not steps:
            self.phase = phase
            if self.volume == 0:
                return 0
            return self.volume if not (self.lfsr & 1) else -self.volume

        phase -= steps
        lfsr = self.lfsr
        tables = (
            NOISE_JUMP_TABLES_7BIT
            if self.width_mode
            else NOISE_JUMP_TABLES_15BIT
        )
        jump = 0
        while steps:
            if steps & 1:
                lfsr = tables[jump][lfsr]
            steps >>= 1
            jump += 1
        self.phase = phase
        self.lfsr = lfsr
        if self.volume == 0:
            return 0
        return self.volume if not (lfsr & 1) else -self.volume


class GbApu(object):
    """DMG APU with four channels and stereo sample generation."""

    def __init__(self, memory):
        self.memory = memory
        self.audio_memory = bytearray(0x10000)
        self.channel1 = SquareChannel(NR11, NR12, NR13, NR14)
        self.channel2 = SquareChannel(NR21, NR22, NR23, NR24)
        self.channel3 = WaveChannel()
        self.channel4 = NoiseChannel()
        self.sweep_shadow_frequency = 0
        self.sweep_timer = 0
        self.sweep_enabled = False
        self.enabled = False
        self.live_master_enabled = False
        self.live_channel1_enabled = False
        self.live_channel2_enabled = False
        self.live_channel3_enabled = False
        self.live_channel4_enabled = False
        self.events = []
        self.frame_start_cycle = 0
        self.frame_sequencer_remainder = 0
        self.frame_sequencer_step = 0

    def write_register(self, address, value, cycle=0):
        """Record a register write and update CPU-visible channel status."""
        self.events.append((cycle, address, value))

        if address == NR52:
            self.live_master_enabled = bool(value & 0x80)
            if not self.live_master_enabled:
                self.live_channel1_enabled = False
                self.live_channel2_enabled = False
                self.live_channel3_enabled = False
                self.live_channel4_enabled = False
                for register in range(NR10, NR52):
                    self.memory[register] = 0
            self._update_live_status()
            return

        if not self.live_master_enabled:
            return

        if address == NR12 and not value & 0xF8:
            self.live_channel1_enabled = False
        elif address == NR22 and not value & 0xF8:
            self.live_channel2_enabled = False
        elif address == NR30 and not value & 0x80:
            self.live_channel3_enabled = False
        elif address == NR42 and not value & 0xF8:
            self.live_channel4_enabled = False
        elif address == NR14 and value & 0x80 and self.memory[NR12] & 0xF8:
            self.live_channel1_enabled = True
        elif address == NR24 and value & 0x80 and self.memory[NR22] & 0xF8:
            self.live_channel2_enabled = True
        elif address == NR34 and value & 0x80 and self.memory[NR30] & 0x80:
            self.live_channel3_enabled = True
        elif address == NR44 and value & 0x80 and self.memory[NR42] & 0xF8:
            self.live_channel4_enabled = True
        self._update_live_status()

    def generate_frame(self):
        """Render one frame, applying register writes at cycle-derived samples."""
        frame_start = self.frame_start_cycle
        frame_end = frame_start + DMG_CYCLES_PER_FRAME
        start_sample = frame_start * SAMPLE_RATE // DMG_CLOCK_HZ
        end_sample = frame_end * SAMPLE_RATE // DMG_CLOCK_HZ
        sample_count = end_sample - start_sample
        samples = np.zeros((sample_count, 2), dtype=np.int16)
        events = self.events
        event_index = 0
        event_count = len(events)
        apply_register = self._apply_register
        sample_channel1 = self.channel1.sample
        sample_channel2 = self.channel2.sample
        sample_channel3 = self.channel3.sample
        sample_channel4 = self.channel4.sample
        sequencer_remainder = self.frame_sequencer_remainder
        sequencer_step = self.frame_sequencer_step
        channel1 = self.channel1
        channel2 = self.channel2
        channel3 = self.channel3
        channel4 = self.channel4
        memory = self.audio_memory
        routing = memory[NR51]
        volume = memory[NR50]
        right_scale = ((volume & 0x07) + 1) * 64
        left_scale = (((volume >> 4) & 0x07) + 1) * 64
        right_routes = (
            bool(routing & 0x01),
            bool(routing & 0x02),
            bool(routing & 0x04),
            bool(routing & 0x08),
        )
        left_routes = (
            bool(routing & 0x10),
            bool(routing & 0x20),
            bool(routing & 0x40),
            bool(routing & 0x80),
        )
        all_routes = routing == 0xFF
        shared_routes = (routing & 0x0F) == (routing >> 4)

        for index, sample_number in enumerate(
            range(start_sample, end_sample)
        ):
            mixer_changed = False
            if event_index < event_count:
                sample_cycle_scaled = sample_number * DMG_CLOCK_HZ
                while (
                    event_index < event_count
                    and events[event_index][0] * SAMPLE_RATE
                    <= sample_cycle_scaled
                ):
                    _, address, value = events[event_index]
                    apply_register(address, value)
                    mixer_changed |= address in (NR50, NR51)
                    event_index += 1
            if mixer_changed:
                routing = memory[NR51]
                volume = memory[NR50]
                right_scale = ((volume & 0x07) + 1) * 64
                left_scale = (((volume >> 4) & 0x07) + 1) * 64
                right_routes = (
                    bool(routing & 0x01),
                    bool(routing & 0x02),
                    bool(routing & 0x04),
                    bool(routing & 0x08),
                )
                left_routes = (
                    bool(routing & 0x10),
                    bool(routing & 0x20),
                    bool(routing & 0x40),
                    bool(routing & 0x80),
                )
                all_routes = routing == 0xFF
                shared_routes = (routing & 0x0F) == (routing >> 4)

            sample1 = sample_channel1()
            sample2 = sample_channel2()
            sample3 = sample_channel3(memory)
            sample4 = sample_channel4()
            if all_routes:
                right = left = sample1 + sample2 + sample3 + sample4
            elif shared_routes:
                right = left = (
                    sample1 * right_routes[0]
                    + sample2 * right_routes[1]
                    + sample3 * right_routes[2]
                    + sample4 * right_routes[3]
                )
            else:
                right = (
                    sample1 * right_routes[0]
                    + sample2 * right_routes[1]
                    + sample3 * right_routes[2]
                    + sample4 * right_routes[3]
                )
                left = (
                    sample1 * left_routes[0]
                    + sample2 * left_routes[1]
                    + sample3 * left_routes[2]
                    + sample4 * left_routes[3]
                )
            samples[index, 0] = left * left_scale
            samples[index, 1] = right * right_scale
            sequencer_remainder += FRAME_SEQUENCER_HZ
            if sequencer_remainder >= SAMPLE_RATE:
                sequencer_remainder -= SAMPLE_RATE
                if sequencer_step in (0, 2, 4, 6):
                    channel1.clock_length(memory)
                    channel2.clock_length(memory)
                    channel3.clock_length(memory)
                    channel4.clock_length(memory)
                if sequencer_step in (2, 6):
                    self._clock_sweep()
                if sequencer_step == 7:
                    channel1.clock_envelope()
                    channel2.clock_envelope()
                    channel4.clock_envelope()
                sequencer_step = (sequencer_step + 1) & 7

        if event_index:
            del events[:event_index]
        self.frame_start_cycle = frame_end
        self.frame_sequencer_remainder = sequencer_remainder
        self.frame_sequencer_step = sequencer_step

        # Keep status reads useful after length/envelope processing. Any
        # writes queued just beyond this frame will update it on their own.
        self.live_channel1_enabled = self.channel1.enabled
        self.live_channel2_enabled = self.channel2.enabled
        self.live_channel3_enabled = self.channel3.enabled
        self.live_channel4_enabled = self.channel4.enabled
        self._update_live_status()
        return samples

    def _apply_register(self, address, value):
        """Apply one timestamped write to the audio-rendering state."""
        memory = self.audio_memory
        memory[address] = value

        if address == NR52:
            self.enabled = bool(value & 0x80)
            if not self.enabled:
                self.channel1.enabled = False
                self.channel2.enabled = False
                self.channel3.enabled = False
                self.channel4.enabled = False
                self.sweep_enabled = False
                for register in range(NR10, NR52):
                    memory[register] = 0
            return

        if not self.enabled:
            return

        if address in (NR11, NR13):
            self.channel1.refresh(memory)
        elif address == NR12:
            if not value & 0xF8:
                self.channel1.enabled = False
        elif address == NR14:
            if value & 0x80:
                self.channel1.trigger(memory)
                self._trigger_sweep()
            else:
                self.channel1.refresh(memory)
        elif address in (NR21, NR23):
            self.channel2.refresh(memory)
        elif address == NR22:
            if not value & 0xF8:
                self.channel2.enabled = False
        elif address == NR24:
            if value & 0x80:
                self.channel2.trigger(memory)
            else:
                self.channel2.refresh(memory)
        elif address in (NR30, NR31, NR32, NR33):
            if address == NR30 and not value & 0x80:
                self.channel3.enabled = False
            if address == NR33:
                self.channel3.refresh(memory)
        elif address == NR34:
            if value & 0x80:
                self.channel3.trigger(memory)
            else:
                self.channel3.refresh(memory)
        elif address in (NR41, NR42, NR43):
            if address == NR42 and not value & 0xF8:
                self.channel4.enabled = False
            if address == NR43:
                self.channel4.refresh(memory)
        elif address == NR44:
            if value & 0x80:
                self.channel4.trigger(memory)
        elif WAVE_RAM_START <= address <= WAVE_RAM_END:
            pass

    def _clock_frame_sequencer(self):
        self.frame_sequencer_remainder += FRAME_SEQUENCER_HZ
        if self.frame_sequencer_remainder < SAMPLE_RATE:
            return
        self.frame_sequencer_remainder -= SAMPLE_RATE

        step = self.frame_sequencer_step
        if step in (0, 2, 4, 6):
            self.channel1.clock_length(self.audio_memory)
            self.channel2.clock_length(self.audio_memory)
            self.channel3.clock_length(self.audio_memory)
            self.channel4.clock_length(self.audio_memory)
        if step in (2, 6):
            self._clock_sweep()
        if step == 7:
            self.channel1.clock_envelope()
            self.channel2.clock_envelope()
            self.channel4.clock_envelope()
        self.frame_sequencer_step = (step + 1) & 7

    def _trigger_sweep(self):
        memory = self.audio_memory
        self.sweep_shadow_frequency = (
            memory[NR13] | ((memory[NR14] & 0x07) << 8)
        )
        period = (memory[NR10] >> 4) & 0x07
        shift = memory[NR10] & 0x07
        self.sweep_timer = period or 8
        self.sweep_enabled = bool(period or shift)
        if shift and self._calculate_sweep_frequency() > 2047:
            self.channel1.enabled = False

    def _calculate_sweep_frequency(self):
        offset = self.sweep_shadow_frequency >> (
            self.audio_memory[NR10] & 0x07
        )
        if self.audio_memory[NR10] & 0x08:
            return self.sweep_shadow_frequency - offset
        return self.sweep_shadow_frequency + offset

    def _clock_sweep(self):
        if self.sweep_timer > 0:
            self.sweep_timer -= 1
        if self.sweep_timer > 0:
            return

        period = (self.audio_memory[NR10] >> 4) & 0x07
        self.sweep_timer = period or 8
        if not self.sweep_enabled or period == 0:
            return

        shift = self.audio_memory[NR10] & 0x07
        if shift == 0:
            return
        frequency = self._calculate_sweep_frequency()
        if frequency > 2047:
            self.channel1.enabled = False
            return

        self.sweep_shadow_frequency = frequency
        self.audio_memory[NR13] = frequency & 0xFF
        self.audio_memory[NR14] = (
            (self.audio_memory[NR14] & 0xF8)
            | ((frequency >> 8) & 0x07)
        )
        self.channel1.refresh(self.audio_memory)
        if self._calculate_sweep_frequency() > 2047:
            self.channel1.enabled = False

    def _update_live_status(self):
        status = 0x70
        if self.live_master_enabled:
            status |= 0x80
        if self.live_channel1_enabled:
            status |= 0x01
        if self.live_channel2_enabled:
            status |= 0x02
        if self.live_channel3_enabled:
            status |= 0x04
        if self.live_channel4_enabled:
            status |= 0x08
        self.memory[NR52] = status
