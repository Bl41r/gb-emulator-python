"""Cpu Tests."""

from cpu import Z80Cpu


def test_cpu_1():
    """blah."""
    cpu = Z80Cpu([])
    cpu.execute_specific_instruction(0)
    cpu.execute_specific_instruction(120)

