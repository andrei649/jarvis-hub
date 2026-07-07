"""Render the Jarvis Hub alpha-testing hook video.

The output is intentionally deterministic and footage-free: it creates a short
caption-first vertical MP4 suitable for muted social feeds and direct messages.
"""

from __future__ import annotations

import math
import os
import shutil
import stat
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parent
FRAME_DIR = ROOT / "_frames"
OUT_MP4 = ROOT / "jarvis-alpha-hook-vertical.mp4"
OUT_THUMB = ROOT / "jarvis-alpha-hook-thumbnail.png"

WIDTH = 720
HEIGHT = 1280
FPS = 24
DURATION = 22.0
TOTAL_FRAMES = int(FPS * DURATION)

VOID = (4, 7, 14)
INK = (238, 241, 245)
MUTED = (148, 163, 184)
CYAN = (43, 184, 240)
CYAN_LIGHT = (143, 224, 255)
GREEN = (65, 245, 155)
AMBER = (255, 178, 63)
VIOLET = (167, 139, 250)


SCENES = [
    {
        "start": 0.0,
        "end": 3.2,
        "kicker": "ALPHA TEST",
        "headline": "Caut 2-3 oameni care sa testeze Jarvis Hub pe bune.",
        "body": "Nu lansare publica. Test real, feedback sincer.",
        "chips": ["2-4 saptamani", "suport direct"],
        "accent": CYAN,
    },
    {
        "start": 3.2,
        "end": 6.8,
        "kicker": "LOCAL-FIRST",
        "headline": "Un asistent AI local-first: pe calculatorul tau sau cu cheia ta API.",
        "body": "Datele nu trebuie sa traiasca in cloud ca sa ai un asistent util.",
        "chips": ["LM Studio", "Ollama", "API optional"],
        "accent": GREEN,
    },
    {
        "start": 6.8,
        "end": 10.6,
        "kicker": "GOVERNED",
        "headline": "Actiunile importante se opresc pentru aprobare.",
        "body": "Preview, queue de aprobare, audit log tamper-evident.",
        "chips": ["approve", "audit", "kill switch"],
        "accent": AMBER,
    },
    {
        "start": 10.6,
        "end": 14.2,
        "kicker": "NOT A TOY DEMO",
        "headline": "17 agenti, memorie vie, cockpit, mobil si canale reale.",
        "body": "Pre-1.0. Destul de real ca sa fie util, destul de devreme ca feedbackul tau conteaza.",
        "chips": ["17 agenti", "local memory", "mobile queue"],
        "accent": VIOLET,
    },
    {
        "start": 14.2,
        "end": 18.0,
        "kicker": "CINE SE POTRIVESTE",
        "headline": "Ai Windows 11/Linux si GPU 8GB VRAM sau cheie API?",
        "body": "Plus 15 minute pe zi si un check-in saptamanal.",
        "chips": ["RTX 3060+", "OpenAI/Anthropic/Gemini", "2-4 saptamani"],
        "accent": CYAN,
    },
    {
        "start": 18.0,
        "end": 22.0,
        "kicker": "DM",
        "headline": "Vrei in alpha? Scrie-mi: Jarvis alpha",
        "body": "Iti trimit intrebarile de screening si ghidul de instalare.",
        "chips": ["Jarvis Hub", "alpha testing"],
        "accent": GREEN,
    },
]


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        Path("C:/Windows/Fonts") / name,
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


FONT_HEAD = font("segoeuib.ttf", 48)
FONT_BODY = font("segoeui.ttf", 27)
FONT_KICKER = font("consolab.ttf", 22)
FONT_CHIP = font("consola.ttf", 20)
FONT_SMALL = font("consola.ttf", 18)


def ease(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 1 - pow(1 - x, 3)


def clamp_alpha(x: float) -> int:
    return int(max(0, min(255, x)))


def find_scene(t: float) -> dict:
    for scene in SCENES:
        if scene["start"] <= t < scene["end"]:
            return scene
    return SCENES[-1]


def wrap(draw: ImageDraw.ImageDraw, text: str, font_obj: ImageFont.ImageFont,
         max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font_obj) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def draw_text_block(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str,
                    font_obj: ImageFont.ImageFont, fill: tuple[int, int, int, int],
                    max_width: int, line_gap: int) -> int:
    x, y = xy
    for line in wrap(draw, text, font_obj, max_width):
        draw.text((x, y), line, font=font_obj, fill=fill)
        bbox = draw.textbbox((x, y), line, font=font_obj)
        y += (bbox[3] - bbox[1]) + line_gap
    return y


def add_glow(base: Image.Image, center: tuple[int, int], color: tuple[int, int, int],
             radius: int, strength: int) -> None:
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    x, y = center
    draw.ellipse((x - radius, y - radius, x + radius, y + radius),
                 fill=(*color, strength))
    layer = layer.filter(ImageFilter.GaussianBlur(radius // 2))
    base.alpha_composite(layer)


def background(t: float) -> Image.Image:
    img = Image.new("RGBA", (WIDTH, HEIGHT), (*VOID, 255))
    px = img.load()
    for y in range(HEIGHT):
        blend = y / HEIGHT
        r = int(VOID[0] + 6 * blend)
        g = int(VOID[1] + 12 * blend)
        b = int(VOID[2] + 24 * blend)
        for x in range(WIDTH):
            px[x, y] = (r, g, b, 255)

    add_glow(img, (620, 190), CYAN, 260, 85)
    add_glow(img, (90, 1030), VIOLET, 230, 45)

    grid = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(grid)
    offset = int((t * 22) % 72)
    for x in range(-72 + offset, WIDTH, 72):
        draw.line((x, 0, x, HEIGHT), fill=(143, 224, 255, 20), width=1)
    for y in range(-72 + offset, HEIGHT, 72):
        draw.line((0, y, WIDTH, y), fill=(143, 224, 255, 14), width=1)
    img.alpha_composite(grid)
    return img


def draw_network(draw: ImageDraw.ImageDraw, t: float, accent: tuple[int, int, int]) -> None:
    cx, cy = 360, 360
    nodes = []
    for i in range(17):
        ring = 118 + (i % 3) * 42
        angle = (i / 17) * math.tau + t * 0.22 * ((i % 2) * 2 - 1)
        x = cx + int(math.cos(angle) * ring)
        y = cy + int(math.sin(angle) * ring * 0.72)
        nodes.append((x, y))
    for i, a in enumerate(nodes):
        for j, b in enumerate(nodes):
            if j <= i:
                continue
            if (i * 7 + j * 3) % 11 in (0, 1):
                draw.line((*a, *b), fill=(*accent, 42), width=1)
    for i, (x, y) in enumerate(nodes):
        r = 4 + (i % 3)
        draw.ellipse((x - r, y - r, x + r, y + r), fill=(*INK, 210))
    draw.ellipse((cx - 35, cy - 35, cx + 35, cy + 35), outline=(*accent, 180), width=3)
    draw.text((cx - 18, cy - 13), "17", font=FONT_CHIP, fill=(*accent, 240))


def draw_phone_card(draw: ImageDraw.ImageDraw, scene: dict, progress: float) -> None:
    accent = scene["accent"]
    x0 = 86
    y0 = 850 + int((1 - ease(progress)) * 24)
    x1 = WIDTH - 86
    y1 = 1142
    draw.rounded_rectangle((x0, y0, x1, y1), radius=28,
                           fill=(9, 15, 28, 230), outline=(*accent, 120), width=2)
    draw.text((x0 + 28, y0 + 28), "COADA DE APROBARE", font=FONT_SMALL,
              fill=(*MUTED, 230))
    draw.rounded_rectangle((x0 + 28, y0 + 70, x1 - 28, y0 + 148), radius=18,
                           fill=(15, 25, 45, 230), outline=(238, 241, 245, 36), width=1)
    draw.text((x0 + 52, y0 + 92), "Trimite draftul?", font=FONT_BODY,
              fill=(*INK, 235))
    draw.rounded_rectangle((x0 + 28, y0 + 178, x0 + 220, y0 + 232), radius=18,
                           fill=(*accent, 230))
    draw.text((x0 + 74, y0 + 192), "APROBA", font=FONT_CHIP,
              fill=(4, 7, 14, 255))
    draw.rounded_rectangle((x0 + 242, y0 + 178, x0 + 434, y0 + 232), radius=18,
                           fill=(255, 90, 82, 210))
    draw.text((x0 + 284, y0 + 192), "RESPINGE", font=FONT_CHIP,
              fill=(4, 7, 14, 255))
    draw.text((x0 + 28, y1 - 54), "local-first / governed / auditable",
              font=FONT_SMALL, fill=(*MUTED, 220))


def render_frame(frame_index: int) -> Image.Image:
    t = frame_index / FPS
    scene = find_scene(t)
    local = (t - scene["start"]) / (scene["end"] - scene["start"])
    fade_in = ease(min(local * 4, 1))
    fade_out = ease(min((1 - local) * 4, 1))
    alpha = clamp_alpha(255 * min(fade_in, fade_out))

    img = background(t)
    draw = ImageDraw.Draw(img, "RGBA")
    accent = scene["accent"]

    draw_network(draw, t, accent)

    panel_y = 452 + int((1 - ease(local)) * 28)
    draw.rounded_rectangle((54, panel_y, WIDTH - 54, 770), radius=30,
                           fill=(7, 12, 23, 218), outline=(*accent, 110), width=2)
    draw.text((82, panel_y + 36), scene["kicker"], font=FONT_KICKER,
              fill=(*accent, alpha))
    y = draw_text_block(draw, (82, panel_y + 78), scene["headline"], FONT_HEAD,
                        (*INK, alpha), WIDTH - 164, 8)
    draw_text_block(draw, (82, y + 20), scene["body"], FONT_BODY,
                    (*MUTED, alpha), WIDTH - 164, 6)

    chip_x = 82
    chip_y = 790
    for chip in scene["chips"]:
        w = int(draw.textlength(chip, font=FONT_CHIP)) + 38
        if chip_x + w > WIDTH - 82:
            chip_x = 82
            chip_y += 52
        draw.rounded_rectangle((chip_x, chip_y, chip_x + w, chip_y + 38),
                               radius=17, fill=(*accent, 34),
                               outline=(*accent, 110), width=1)
        draw.text((chip_x + 19, chip_y + 8), chip, font=FONT_CHIP,
                  fill=(*INK, alpha))
        chip_x += w + 14

    draw_phone_card(draw, scene, local)

    draw.text((54, 1184), "JARVIS HUB", font=FONT_CHIP, fill=(*INK, 210))
    draw.text((54, 1218), "private alpha testing", font=FONT_SMALL, fill=(*MUTED, 210))
    progress_w = int((frame_index + 1) / TOTAL_FRAMES * (WIDTH - 108))
    draw.rounded_rectangle((54, 1244, WIDTH - 54, 1252), radius=4,
                           fill=(238, 241, 245, 30))
    draw.rounded_rectangle((54, 1244, 54 + progress_w, 1252), radius=4,
                           fill=(*accent, 230))

    return img.convert("RGB")


def remove_tree(path: Path) -> None:
    """Remove generated frames, including Windows read-only temp directories."""

    if not path.exists():
        return

    def clear_readonly(func, target, exc_info):
        del exc_info
        os.chmod(target, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
        func(target)

    shutil.rmtree(path, onexc=clear_readonly)


def main() -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg not found on PATH")

    if FRAME_DIR.exists():
        remove_tree(FRAME_DIR)
    FRAME_DIR.mkdir(parents=True)

    thumb_saved = False
    for idx in range(TOTAL_FRAMES):
        frame = render_frame(idx)
        frame.save(FRAME_DIR / f"frame_{idx:04d}.jpg", quality=92, optimize=True)
        if not thumb_saved and idx >= int(1.4 * FPS):
            frame.save(OUT_THUMB)
            thumb_saved = True

    cmd = [
        ffmpeg,
        "-y",
        "-framerate",
        str(FPS),
        "-i",
        str(FRAME_DIR / "frame_%04d.jpg"),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-an",
        str(OUT_MP4),
    ]
    subprocess.run(cmd, check=True)
    remove_tree(FRAME_DIR)
    print(f"Wrote {OUT_MP4}")
    print(f"Wrote {OUT_THUMB}")


if __name__ == "__main__":
    main()
