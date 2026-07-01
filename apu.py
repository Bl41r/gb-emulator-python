"""Initial DMG audio processing unit implementation.

This first slice implements the two square-wave channels, their length and
volume envelopes, and the DMG stereo mixer. Sweep, wave, and noise channels
will be added separately.
"""

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
NR50 = 0xFF24
NR51 = 0xFF25
NR52 = 0xFF26

DUTY_RATIOS = (0.125, 0.25, 0.5, 0.75)


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


class GbApu(object):
    """DMG APU with square channels and stereo sample generation."""

    def __init__(self, memory):
        self.memory = memory
        self.audio_memory = bytearray(0x10000)
        self.channel1 = SquareChannel(NR11, NR12, NR13, NR14)
        self.channel2 = SquareChannel(NR21, NR22, NR23, NR24)
        self.enabled = False
        self.live_master_enabled = False
        self.live_channel1_enabled = False
        self.live_channel2_enabled = False
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
        elif address == NR14 and value & 0x80 and self.memory[NR12] & 0xF8:
            self.live_channel1_enabled = True
        elif address == NR24 and value & 0x80 and self.memory[NR22] & 0xF8:
            self.live_channel2_enabled = True
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

        for index, sample_number in enumerate(
            range(start_sample, end_sample)
        ):
            sample_cycle_scaled = sample_number * DMG_CLOCK_HZ
            while (
                event_index < len(events)
                and events[event_index][0] * SAMPLE_RATE
                <= sample_cycle_scaled
            ):
                _, address, value = events[event_index]
                self._apply_register(address, value)
                event_index += 1

            channel1 = self.channel1.sample()
            channel2 = self.channel2.sample()
            memory = self.audio_memory
            routing = memory[NR51]
            volume = memory[NR50]
            right_volume = (volume & 0x07) + 1
            left_volume = ((volume >> 4) & 0x07) + 1
            right = (
                (channel1 if routing & 0x01 else 0)
                + (channel2 if routing & 0x02 else 0)
            )
            left = (
                (channel1 if routing & 0x10 else 0)
                + (channel2 if routing & 0x20 else 0)
            )
            samples[index, 0] = left * left_volume * 64
            samples[index, 1] = right * right_volume * 64
            self._clock_frame_sequencer()

        if event_index:
            del events[:event_index]
        self.frame_start_cycle = frame_end

        # Keep status reads useful after length/envelope processing. Any
        # writes queued just beyond this frame will update it on their own.
        self.live_channel1_enabled = self.channel1.enabled
        self.live_channel2_enabled = self.channel2.enabled
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

    def _clock_frame_sequencer(self):
        self.frame_sequencer_remainder += FRAME_SEQUENCER_HZ
        if self.frame_sequencer_remainder < SAMPLE_RATE:
            return
        self.frame_sequencer_remainder -= SAMPLE_RATE

        step = self.frame_sequencer_step
        if step in (0, 2, 4, 6):
            self.channel1.clock_length(self.audio_memory)
            self.channel2.clock_length(self.audio_memory)
        if step == 7:
            self.channel1.clock_envelope()
            self.channel2.clock_envelope()
        self.frame_sequencer_step = (step + 1) & 7

    def _update_live_status(self):
        status = 0x70
        if self.live_master_enabled:
            status |= 0x80
        if self.live_channel1_enabled:
            status |= 0x01
        if self.live_channel2_enabled:
            status |= 0x02
        self.memory[NR52] = status
