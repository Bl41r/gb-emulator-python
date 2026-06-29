"""Run the Blargg cpu_instrs ROMs against Gameboy Doctor reference traces."""

import argparse
import builtins
import pathlib
import sys
import time
import zipfile

from cpu import GbZ80Cpu
from gpu import GbGpu
from memory import GbMemory
from system_interface import GbSystemInterface


PROJECT_ROOT = pathlib.Path(__file__).resolve().parent
DEFAULT_ROM_DIR = (
    PROJECT_ROOT
    / "test-roms"
    / "gb-test-roms"
    / "cpu_instrs"
    / "individual"
)
DEFAULT_TRUTH_DIR = (
    PROJECT_ROOT
    / "test-roms"
    / "gameboy-doctor"
    / "truth"
    / "zipped"
    / "cpu_instrs"
)


class TraceComplete(Exception):
    """Raised when every reference state has matched."""


class TraceMismatch(Exception):
    """Raised at the first CPU state that differs from the reference."""


class DoctorTrace:
    """List-like sink that compares CPU log entries as they are produced."""

    LINE_LENGTH = 73

    def __init__(self, archive_path):
        self.archive = zipfile.ZipFile(str(archive_path))
        members = self.archive.namelist()
        if len(members) != 1:
            raise ValueError(
                "{} should contain exactly one trace".format(archive_path)
            )
        self.reference = self.archive.open(members[0])
        self.line_number = 0

    def append(self, actual):
        """Compare an emulator log entry with the next reference entry."""
        expected = self.reference.readline().strip()
        if not expected:
            raise TraceComplete()

        self.line_number += 1
        actual_bytes = actual[:self.LINE_LENGTH].encode("ascii")
        if actual_bytes.lower() != expected.lower():
            raise TraceMismatch(
                "line {:,}\n"
                "  expected: {}\n"
                "  actual:   {}".format(
                    self.line_number,
                    expected.decode("ascii"),
                    actual_bytes.decode("ascii"),
                )
            )

    def close(self):
        self.reference.close()
        self.archive.close()


def find_rom(rom_dir, number):
    matches = list(rom_dir.glob("{:02d}-*.gb".format(number)))
    if len(matches) != 1:
        raise FileNotFoundError(
            "expected one ROM matching {:02d}-*.gb in {}".format(
                number, rom_dir
            )
        )
    return matches[0]


def run_rom(number, rom_dir, truth_dir):
    """Run one ROM until its trace passes, diverges, or the emulator errors."""
    rom_path = find_rom(rom_dir, number)
    truth_path = truth_dir / "{}.zip".format(number)
    trace = DoctorTrace(truth_path)

    memory = GbMemory(skip_bios=False, gb_doctor_test_mode=True)
    cpu = GbZ80Cpu(trace, gb_doctor_test_mode=True)
    gpu = GbGpu()
    interface = GbSystemInterface(memory, cpu, gpu)
    cpu.sys_interface = interface
    gpu.sys_interface = interface

    original_print = builtins.print
    builtins.print = lambda *args, **kwargs: None
    started = time.time()
    try:
        interface.load_rom_image(str(rom_path))
        while True:
            cpu.execute_next_operation()
    except TraceComplete:
        status = "PASS"
        detail = ""
    except TraceMismatch as error:
        status = "FAIL"
        detail = str(error)
    except Exception as error:
        status = "ERROR"
        detail = "{} after trace line {:,}: {}: {}".format(
            rom_path.name,
            trace.line_number,
            type(error).__name__,
            error,
        )
    finally:
        builtins.print = original_print
        trace.close()

    return {
        "detail": detail,
        "elapsed": time.time() - started,
        "lines": trace.line_number,
        "name": rom_path.name,
        "status": status,
    }


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Run Blargg's individual cpu_instrs ROMs headlessly and compare "
            "each CPU state with Gameboy Doctor."
        )
    )
    parser.add_argument(
        "rom",
        nargs="*",
        type=int,
        default=list(range(1, 12)),
        help="ROM numbers to run (default: 1 through 11)",
    )
    parser.add_argument(
        "--rom-dir",
        type=pathlib.Path,
        default=DEFAULT_ROM_DIR,
        help="directory containing the individual cpu_instrs ROMs",
    )
    parser.add_argument(
        "--truth-dir",
        type=pathlib.Path,
        default=DEFAULT_TRUTH_DIR,
        help="directory containing Gameboy Doctor's numbered trace ZIPs",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    invalid = [number for number in args.rom if number not in range(1, 12)]
    if invalid:
        print("ROM numbers must be between 1 and 11: {}".format(invalid))
        return 2

    results = []
    for number in args.rom:
        try:
            result = run_rom(number, args.rom_dir, args.truth_dir)
        except (FileNotFoundError, ValueError, zipfile.BadZipFile) as error:
            print("[SETUP ERROR] {}".format(error))
            return 2

        results.append(result)
        print(
            "[{}] {:02d} {:<27} {:>9,} lines {:>6.1f}s".format(
                result["status"],
                number,
                result["name"],
                result["lines"],
                result["elapsed"],
            ),
            flush=True,
        )
        if result["detail"]:
            print(result["detail"], flush=True)

    passed = sum(result["status"] == "PASS" for result in results)
    failed = len(results) - passed
    print("\nSummary: {} passed, {} failed".format(passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
