"""Capture visual reference sheets from this emulator and PyBoy.

Example:
    python tools/visual_compare.py roms/Zelda_IV_ZX.gb --gbc \
        --start-frame 1494 --end-frame 2094 --interval-frames 60 \
        --output-dir captures/zelda_beach_compare
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pygame
import pygame.surfarray
from pyboy import PyBoy


SCREEN_WIDTH = 160
SCREEN_HEIGHT = 144
DEFAULT_FPS = 59.7275


def parse_args():
    parser = argparse.ArgumentParser(
        description="Capture emulator/PyBoy visual comparison contact sheets",
    )
    parser.add_argument("rom", help="path to the ROM to capture")
    parser.add_argument(
        "--gbc",
        action="store_true",
        help="legacy shortcut: compare ours-cgb against pyboy-cgb",
    )
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=("ours-dmg", "ours-cgb", "pyboy-dmg", "pyboy-cgb"),
        help=(
            "capture these exact comparison rows; defaults to ours/pyboy "
            "in DMG mode, or CGB mode when --gbc is set"
        ),
    )
    parser.add_argument(
        "--start-frame",
        type=int,
        required=True,
        help="first completed emulated frame to capture",
    )
    parser.add_argument(
        "--end-frame",
        type=int,
        required=True,
        help="last completed emulated frame to capture",
    )
    parser.add_argument(
        "--interval-frames",
        type=int,
        default=60,
        help="frame interval between captures",
    )
    parser.add_argument(
        "--output-dir",
        default="captures/visual_compare",
        help="directory for generated screenshots and contact sheets",
    )
    parser.add_argument(
        "--scale",
        type=int,
        default=4,
        help="contact-sheet image scale",
    )
    parser.add_argument(
        "--keep-existing",
        action="store_true",
        help="do not delete the output directory before capturing",
    )
    parser.add_argument(
        "--skip-capture",
        action="store_true",
        help="reuse existing captures and only rebuild sheets/motion artifacts",
    )
    parser.add_argument(
        "--crop",
        type=int,
        nargs=4,
        metavar=("X", "Y", "WIDTH", "HEIGHT"),
        help="optional crop rectangle for motion comparison output",
    )
    parser.add_argument(
        "--make-gif",
        action="store_true",
        help=(
            "write side-by-side motion frames and, if imageio is installed, "
            "an animated GIF"
        ),
    )
    parser.add_argument(
        "--gif-fps",
        type=float,
        default=12.0,
        help="animated GIF playback FPS",
    )
    parser.add_argument(
        "--gif-scale",
        type=int,
        default=3,
        help="motion frame/GIF image scale",
    )
    parser.add_argument(
        "--motion-metrics",
        action="store_true",
        help="print simple ours-vs-PyBoy pixel and frame-to-frame motion metrics",
    )
    return parser.parse_args()


def frame_set(start_frame, end_frame, interval_frames):
    if start_frame < 1:
        raise ValueError("--start-frame must be at least 1")
    if end_frame < start_frame:
        raise ValueError("--end-frame must be >= --start-frame")
    if interval_frames < 1:
        raise ValueError("--interval-frames must be at least 1")
    return set(range(start_frame, end_frame + 1, interval_frames))


def prepare_output(root, keep_existing):
    root = Path(root)
    if root.exists() and not keep_existing:
        shutil.rmtree(root)
    return root


def selected_modes(args):
    if args.modes:
        return args.modes
    if args.gbc:
        return ["ours-cgb", "pyboy-cgb"]
    return ["ours-dmg", "pyboy-dmg"]


def mode_label(mode):
    labels = {
        "ours-dmg": "Our emulator DMG",
        "ours-cgb": "Our emulator CGB",
        "pyboy-dmg": "PyBoy DMG",
        "pyboy-cgb": "PyBoy CGB",
    }
    return labels[mode]


def mode_is_cgb(mode):
    return mode.endswith("-cgb")


def mode_is_ours(mode):
    return mode.startswith("ours-")


def capture_ours(args, root, mode):
    mode_dir = root / mode
    mode_dir.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "main.py",
        args.rom,
        "--no-display",
        "--max-frames",
        str(args.end_frame),
        "--screenshot-dir",
        str(mode_dir),
        "--screenshot-start-frame",
        str(args.start_frame),
        "--screenshot-end-frame",
        str(args.end_frame),
        "--screenshot-interval-frames",
        str(args.interval_frames),
    ]
    if mode_is_cgb(mode):
        command.append("--gbc")
    subprocess.run(command, check=True)


def save_rgb_array(rgb, path):
    surface = pygame.image.frombuffer(
        rgb[:, :, :3].tobytes(),
        (SCREEN_WIDTH, SCREEN_HEIGHT),
        "RGB",
    )
    pygame.image.save(surface, str(path))


def capture_pyboy(args, root, frames, mode):
    mode_dir = root / mode
    mode_dir.mkdir(parents=True, exist_ok=True)
    pyboy = PyBoy(args.rom, window="null", cgb=mode_is_cgb(mode))
    try:
        for frame in range(1, args.end_frame + 1):
            pyboy.tick()
            if frame in frames:
                seconds = frame / DEFAULT_FPS
                filename = f"{mode}_frame_{frame:06d}_{seconds:06.2f}s.png"
                save_rgb_array(pyboy.screen.ndarray, mode_dir / filename)
    finally:
        pyboy.stop()


def make_contact_sheet(folder, output, scale):
    files_by_frame = capture_files_by_frame(folder)
    if files_by_frame:
        files = [files_by_frame[frame] for frame in sorted(files_by_frame)]
    else:
        files = sorted(p for p in Path(folder).glob("*.png"))
    if not files:
        raise ValueError(f"no PNG captures found in {folder}")
    label_h = 18
    cols = min(3, len(files))
    rows = (len(files) + cols - 1) // cols
    font = pygame.font.Font(None, 16)
    sheet = pygame.Surface(
        (cols * SCREEN_WIDTH * scale, rows * (SCREEN_HEIGHT * scale + label_h))
    )
    sheet.fill((30, 30, 30))
    for index, path in enumerate(files):
        image = pygame.image.load(str(path))
        image = pygame.transform.scale(
            image,
            (SCREEN_WIDTH * scale, SCREEN_HEIGHT * scale),
        )
        x = (index % cols) * SCREEN_WIDTH * scale
        y = (index // cols) * (SCREEN_HEIGHT * scale + label_h)
        sheet.blit(image, (x, y + label_h))
        label = font.render(path.stem, True, (255, 255, 255))
        sheet.blit(label, (x + 4, y + 2))
    pygame.image.save(sheet, str(output))
    return output


def make_combined_sheet(sheets, output):
    loaded = [(mode, pygame.image.load(str(sheet))) for mode, sheet in sheets]
    width = max(sheet.get_width() for _, sheet in loaded)
    gap = 24
    font = pygame.font.Font(None, 24)
    header_h = 28
    height = sum(sheet.get_height() + header_h for _, sheet in loaded)
    height += gap * (len(loaded) - 1)
    combined = pygame.Surface((width, height))
    combined.fill((20, 20, 20))
    y = 0
    for mode, sheet in loaded:
        label = font.render(mode_label(mode), True, (255, 255, 255))
        combined.blit(label, (8, y + 4))
        y += header_h
        combined.blit(sheet, (0, y))
        y += sheet.get_height() + gap
    pygame.image.save(combined, str(output))
    return output


def apply_crop(surface, crop):
    if crop is None:
        return surface
    x, y, width, height = crop
    if width < 1 or height < 1:
        raise ValueError("--crop WIDTH and HEIGHT must be at least 1")
    if x < 0 or y < 0 or x + width > surface.get_width() or y + height > surface.get_height():
        raise ValueError(
            f"--crop {crop} is outside a {surface.get_width()}x{surface.get_height()} image"
        )
    return surface.subsurface(pygame.Rect(x, y, width, height)).copy()


def load_motion_image(path, scale, crop):
    image = pygame.image.load(str(path))
    image = apply_crop(image, crop)
    if scale != 1:
        image = pygame.transform.scale(
            image,
            (image.get_width() * scale, image.get_height() * scale),
        )
    return image


def make_motion_frame(frame_paths, scale, crop):
    images = [
        (mode, load_motion_image(path, scale, crop))
        for mode, path in frame_paths
    ]
    gap = 8
    label_h = 20
    width = sum(image.get_width() for _, image in images) + gap * (len(images) - 1)
    height = max(image.get_height() for _, image in images) + label_h
    frame = pygame.Surface((width, height))
    frame.fill((20, 20, 20))
    font = pygame.font.Font(None, 18)
    x = 0
    for mode, image in images:
        frame.blit(font.render(mode_label(mode), True, (255, 255, 255)), (x + 4, 3))
        frame.blit(image, (x, label_h))
        x += image.get_width() + gap
    return frame


def surface_to_rgb_array(surface):
    array = pygame.surfarray.array3d(surface)
    return array.transpose((1, 0, 2))


def make_motion_comparison(root, modes, scale, crop, gif_fps):
    files_by_mode = {
        mode: capture_files_by_frame(root / mode)
        for mode in modes
    }
    common_frames = sorted(
        set.intersection(*(set(files) for files in files_by_mode.values()))
    )
    if not common_frames:
        raise ValueError("no matching frame captures found for motion comparison")
    if any(len(common_frames) != len(files) for files in files_by_mode.values()):
        counts = ", ".join(f"{mode}={len(files)}" for mode, files in files_by_mode.items())
        raise ValueError(
            "capture frame mismatch: "
            f"{counts}, matched={len(common_frames)}"
        )

    motion_dir = root / "motion_frames"
    motion_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for index, frame_number in enumerate(common_frames, start=1):
        frame = make_motion_frame(
            [
                (mode, files_by_mode[mode][frame_number])
                for mode in modes
            ],
            scale,
            crop,
        )
        frame_path = motion_dir / f"motion_{index:04d}.png"
        pygame.image.save(frame, str(frame_path))
        frames.append(frame)

    viewer_path = make_motion_viewer(motion_dir, root / "motion_viewer.html", gif_fps)
    gif_path = root / "motion_compare.gif"
    try:
        import imageio.v2 as imageio
    except ImportError:
        return motion_dir, viewer_path, None

    imageio.mimsave(
        gif_path,
        [surface_to_rgb_array(frame) for frame in frames],
        duration=1.0 / gif_fps,
    )
    return motion_dir, viewer_path, gif_path


def make_motion_viewer(motion_dir, output, fps):
    frame_paths = sorted(motion_dir.glob("*.png"))
    frame_urls = [
        path.relative_to(output.parent).as_posix()
        for path in frame_paths
    ]
    frame_list = ",\n        ".join(f'"{url}"' for url in frame_urls)
    frame_delay_ms = max(1, round(1000.0 / fps))
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Game Boy visual motion comparison</title>
  <style>
    body {{ background: #111; color: #eee; font-family: sans-serif; margin: 20px; }}
    img {{ image-rendering: pixelated; border: 1px solid #444; max-width: 100%; }}
    button {{ margin-right: 8px; }}
  </style>
</head>
<body>
  <h1>Game Boy visual motion comparison</h1>
  <p>Frame <span id="frame-number">1</span> / {len(frame_urls)} at {fps:g} FPS</p>
  <p>
    <button id="play">Pause</button>
    <button id="prev">Previous</button>
    <button id="next">Next</button>
  </p>
  <img id="frame" src="{frame_urls[0] if frame_urls else ''}" alt="motion comparison frame">
  <script>
    const frames = [
        {frame_list}
    ];
    let index = 0;
    let playing = true;
    const image = document.getElementById("frame");
    const frameNumber = document.getElementById("frame-number");
    const playButton = document.getElementById("play");

    function showFrame(nextIndex) {{
      index = (nextIndex + frames.length) % frames.length;
      image.src = frames[index];
      frameNumber.textContent = index + 1;
    }}

    playButton.addEventListener("click", () => {{
      playing = !playing;
      playButton.textContent = playing ? "Pause" : "Play";
    }});
    document.getElementById("prev").addEventListener("click", () => showFrame(index - 1));
    document.getElementById("next").addEventListener("click", () => showFrame(index + 1));
    window.setInterval(() => {{
      if (playing && frames.length > 0) showFrame(index + 1);
    }}, {frame_delay_ms});
  </script>
</body>
</html>
"""
    output.write_text(html, encoding="utf-8")
    return output


def surface_rgb_array(path, crop):
    surface = pygame.image.load(str(path))
    surface = apply_crop(surface, crop)
    return pygame.surfarray.array3d(surface).transpose((1, 0, 2)).astype("int16")


def print_motion_metrics(root, modes, crop):
    files_by_mode = {
        mode: capture_files_by_frame(root / mode)
        for mode in modes
    }
    pairs = [
        ("ours-cgb", "pyboy-cgb"),
        ("ours-dmg", "pyboy-dmg"),
    ]
    printed = False
    for ours_mode, pyboy_mode in pairs:
        if ours_mode not in files_by_mode or pyboy_mode not in files_by_mode:
            continue
        common_frames = sorted(set(files_by_mode[ours_mode]) & set(files_by_mode[pyboy_mode]))
        if not common_frames:
            continue

        pixel_diffs = []
        motion_deltas = []
        prev_ours = None
        prev_pyboy = None
        for frame in common_frames:
            ours = surface_rgb_array(files_by_mode[ours_mode][frame], crop)
            pyboy = surface_rgb_array(files_by_mode[pyboy_mode][frame], crop)
            pixel_diffs.append(abs(ours - pyboy).mean())
            if prev_ours is not None:
                ours_motion = abs(ours - prev_ours).mean()
                pyboy_motion = abs(pyboy - prev_pyboy).mean()
                motion_deltas.append(abs(ours_motion - pyboy_motion))
            prev_ours = ours
            prev_pyboy = pyboy

        avg_pixel_diff = sum(pixel_diffs) / len(pixel_diffs)
        avg_motion_delta = (
            sum(motion_deltas) / len(motion_deltas)
            if motion_deltas
            else 0.0
        )
        print(
            f"Motion metrics {ours_mode} vs {pyboy_mode}: "
            f"avg pixel diff {avg_pixel_diff:.3f}, "
            f"avg motion delta {avg_motion_delta:.3f}, "
            f"frames {len(common_frames)}"
        )
        printed = True
    if not printed:
        print("Motion metrics skipped: no ours/PyBoy CGB or DMG pairs found")


def capture_files_by_frame(folder):
    files_by_frame = {}
    for path in sorted(Path(folder).glob("*.png")):
        match = re.search(r"frame_(\d+)_", path.name)
        if match:
            files_by_frame[int(match.group(1))] = path
    return files_by_frame


def main():
    args = parse_args()
    modes = selected_modes(args)
    frames = frame_set(args.start_frame, args.end_frame, args.interval_frames)
    root = prepare_output(args.output_dir, args.keep_existing or args.skip_capture)

    pygame.init()
    if not args.skip_capture:
        for mode in modes:
            if mode_is_ours(mode):
                capture_ours(args, root, mode)
            else:
                capture_pyboy(args, root, frames, mode)

    sheets = []
    for mode in modes:
        sheet = make_contact_sheet(
            root / mode,
            root / f"{mode}_contact_sheet.png",
            args.scale,
        )
        sheets.append((mode, sheet))
        print(f"{mode_label(mode)} sheet: {sheet}")
    combined = make_combined_sheet(sheets, root / "combined_contact_sheet.png")
    print(f"Combined sheet: {combined}")
    if args.make_gif:
        motion_dir, viewer_path, gif_path = make_motion_comparison(
            root,
            modes,
            args.gif_scale,
            args.crop,
            args.gif_fps,
        )
        print(f"Motion comparison frames: {motion_dir}")
        print(f"Motion comparison viewer: {viewer_path}")
        if gif_path is None:
            print("Animated GIF skipped: install optional dependency imageio to enable GIF output")
        else:
            print(f"Animated GIF: {gif_path}")
    if args.motion_metrics:
        print_motion_metrics(root, modes, args.crop)


if __name__ == "__main__":
    main()
