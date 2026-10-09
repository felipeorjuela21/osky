"""Cuts the Osky astronaut (celuweb.com Astro-1.png) into animatable layers.

Each layer keeps the full canvas size, so in the browser every part is stacked
at the same position and only rotated around its joint (pivot).

Usage (from the repo root, with Pillow and numpy installed):
    python frontend/scripts/build_rig.py path/to/Astro-1.png

Writes frontend/public/oski-rig/*.png and prints the pivots (in %) for CSS.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "public" / "oski-rig"
SRC_SIZE = 1080
OUT_SIZE = 720

# Coordinates on the 1080x1080 source image.
PARTS = {
    # name: polygon, pivot (joint), blend radii (r0, r1): near the joint the part
    # fades into the body so rotating it never opens a gap.
    "arm-left": {
        "polygon": [(40, 185), (175, 180), (255, 245), (245, 330), (300, 352), (345, 358), (380, 372),
                    (405, 405), (428, 445), (428, 525), (380, 535), (300, 505), (200, 472), (120, 442),
                    (85, 395), (40, 340)],
        "pivot": (405, 455), "blend": (45, 120),
    },
    "hand-left": {  # glove only, cut at the cuff (a natural seam); child of arm-left
        "polygon": [(40, 185), (175, 180), (255, 245), (238, 318), (218, 342), (150, 350), (108, 336), (40, 332)],
        "pivot": (178, 338), "blend": None,
    },
    "arm-right": {
        "polygon": [(612, 330), (700, 308), (830, 308), (900, 282), (962, 286), (1018, 332), (1015, 362),
                    (942, 398), (862, 408), (830, 414), (760, 428), (700, 442), (640, 444), (612, 420)],
        "pivot": (628, 380), "blend": (40, 130),
    },
    "leg-front": {
        "polygon": [(745, 595), (900, 555), (952, 535), (1062, 598), (1060, 685), (1002, 702), (995, 792),
                    (905, 818), (822, 795), (765, 762), (735, 700)],
        "pivot": (745, 690), "blend": (60, 150),
    },
    "leg-back": {
        "polygon": [(545, 770), (640, 765), (722, 805), (800, 812), (852, 830), (892, 940), (874, 978),
                    (812, 965), (700, 962), (600, 932), (560, 862)],
        "pivot": (595, 785), "blend": (60, 150),
    },
}
HELMET = {"center": (448, 305), "radius": 130}
# Gold sun visor (slightly tilted ellipse); lifts up to reveal Osky's face.
VISOR = {"center": (445, 326), "rx": 109, "ry": 98, "angle": -12}

def polygon_mask(points, blur=2.5, grow=0) -> np.ndarray:
    mask = Image.new("L", (SRC_SIZE, SRC_SIZE), 0)
    ImageDraw.Draw(mask).polygon(points, fill=255)
    if grow:  # margin so soft edges and shadows travel with the part
        mask = mask.filter(ImageFilter.MaxFilter(grow * 2 + 1))
    return np.asarray(mask.filter(ImageFilter.GaussianBlur(blur)), dtype=np.float32) / 255

def circle_mask(center, radius, blur=1.5) -> np.ndarray:
    mask = Image.new("L", (SRC_SIZE, SRC_SIZE), 0)
    cx, cy = center
    ImageDraw.Draw(mask).ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=255)
    return np.asarray(mask.filter(ImageFilter.GaussianBlur(blur)), dtype=np.float32) / 255

def ellipse_mask(center, rx, ry, angle, blur=1.5) -> np.ndarray:
    y, x = np.mgrid[0:SRC_SIZE, 0:SRC_SIZE].astype(np.float32)
    a = np.deg2rad(angle)
    dx, dy = x - center[0], y - center[1]
    u = dx * np.cos(a) + dy * np.sin(a)
    v = -dx * np.sin(a) + dy * np.cos(a)
    inside = ((u / rx) ** 2 + (v / ry) ** 2 <= 1).astype(np.uint8) * 255
    mask = Image.fromarray(inside, "L").filter(ImageFilter.GaussianBlur(blur))
    return np.asarray(mask, dtype=np.float32) / 255

def ramp(pivot, r0, r1) -> np.ndarray:
    """0 at the joint, 1 beyond r1 (smoothstep on the distance to the pivot)."""
    y, x = np.mgrid[0:SRC_SIZE, 0:SRC_SIZE].astype(np.float32)
    d = np.hypot(x - pivot[0], y - pivot[1])
    t = np.clip((d - r0) / (r1 - r0), 0, 1)
    return t * t * (3 - 2 * t)

def save(rgba: np.ndarray, alpha: np.ndarray, name: str) -> None:
    out = rgba.copy()
    out[..., 3] = np.clip(rgba[..., 3] * alpha, 0, 255)
    image = Image.fromarray(out.astype(np.uint8), "RGBA").resize((OUT_SIZE, OUT_SIZE), Image.LANCZOS)
    image.save(OUT / f"{name}.png", optimize=True)

def main(src: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rgba = np.asarray(Image.open(src).convert("RGBA").resize((SRC_SIZE, SRC_SIZE)), dtype=np.float32)
    base_keep = np.ones((SRC_SIZE, SRC_SIZE), np.float32)

    hand = polygon_mask(PARTS["hand-left"]["polygon"], blur=1.5)
    for name, part in PARTS.items():
        mask = polygon_mask(part["polygon"], grow=0 if name == "hand-left" else 12)
        if name == "hand-left":
            layer = mask
        else:
            r0, r1 = part["blend"]
            # The layer starts a bit before the body lets go, so they overlap at rest.
            layer = mask * ramp(part["pivot"], r0 - 25, r1 - 25)
            base_keep *= 1 - mask * ramp(part["pivot"], r0, r1)
            if name == "arm-left":
                layer *= 1 - hand  # the glove lives in its own layer
        save(rgba, layer, name)

    base_keep = np.maximum(base_keep, 0)
    save(rgba, base_keep, "body")
    helmet = circle_mask(HELMET["center"], HELMET["radius"])
    save(rgba, helmet, "helmet")
    save(rgba, helmet * ellipse_mask(VISOR["center"], VISOR["rx"], VISOR["ry"], VISOR["angle"]), "visor")

    pct = lambda v: round(v / SRC_SIZE * 100, 2)
    rig = {name: {"pivot": [pct(p["pivot"][0]), pct(p["pivot"][1])]} for name, p in PARTS.items()}
    rig["helmet"] = {"pivot": [pct(HELMET["center"][0]), pct(HELMET["center"][1])]}
    rig["visor"] = {"center": [pct(VISOR["center"][0]), pct(VISOR["center"][1])], "top": pct(VISOR["center"][1] - VISOR["ry"])}
    print(json.dumps(rig, indent=2))

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "Astro-1.png")
