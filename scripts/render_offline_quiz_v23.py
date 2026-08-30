from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import random
import shutil
import struct
import subprocess
import sys
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import quiz_pipeline as qp  # noqa: E402


OUT_W, OUT_H = 1024, 1536
RENDER_SCALE = 2


def _seed(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16)


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def _gradient(size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    w, h = size
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    for y in range(h):
        t = y / max(1, h - 1)
        arr[y, :, :] = _mix(top, bottom, t)
    return Image.fromarray(arr, "RGB")


def _leaf(draw: ImageDraw.ImageDraw, x: int, y: int, r: int,
          color: tuple[int, int, int, int], angle: float = 0.0) -> None:
    ca, sa = math.cos(angle), math.sin(angle)
    points = []
    for px, py in ((-r, 0), (0, -r // 2), (r, 0), (0, r // 2)):
        points.append((x + int(px * ca - py * sa), y + int(px * sa + py * ca)))
    draw.polygon(points, fill=color)


def _scene(habitat: str, size: tuple[int, int] = (OUT_W, OUT_H)) -> Image.Image:
    """Create a layered cinematic habitat. Identical habitat text yields identical pixels."""
    w, h = size
    rng = random.Random(_seed(habitat))
    rainforest = any(word in habitat.lower() for word in ("riverbank", "rainforest", "amazon", "wet"))
    if rainforest:
        image = _gradient(size, (94, 169, 155), (22, 67, 44)).convert("RGBA")
        mist = (188, 229, 211, 44)
        trunk = (48, 71, 49, 255)
        far = (52, 104, 73, 130)
        leaf_colors = [(40, 109, 62, 255), (57, 137, 72, 255), (77, 158, 83, 255), (26, 86, 55, 255)]
    else:
        image = _gradient(size, (173, 186, 126), (34, 70, 45)).convert("RGBA")
        mist = (237, 222, 171, 38)
        trunk = (72, 69, 47, 255)
        far = (72, 113, 67, 125)
        leaf_colors = [(52, 101, 51, 255), (79, 128, 60, 255), (108, 145, 66, 255), (37, 78, 45, 255)]

    draw = ImageDraw.Draw(image, "RGBA")
    # Atmospheric light shafts.
    for i in range(5):
        x = int(w * (0.13 + i * 0.19)) + rng.randint(-35, 35)
        draw.polygon([(x, 0), (x + rng.randint(80, 150), 0),
                      (x + rng.randint(250, 360), int(h * 0.78)),
                      (x + rng.randint(90, 150), int(h * 0.78))], fill=mist)

    # Distant canopy and trees.
    for _ in range(26):
        x = rng.randint(-50, w + 50)
        y = rng.randint(int(h * 0.18), int(h * 0.62))
        r = rng.randint(55, 155)
        draw.ellipse((x - r, y - r // 2, x + r, y + r // 2), fill=far)
    for _ in range(12):
        x = rng.randint(-50, w + 50)
        width = rng.randint(22, 62)
        lean = rng.randint(-45, 45)
        draw.polygon([(x, -30), (x + width, -30),
                      (x + width + lean, int(h * 0.92)), (x + lean, int(h * 0.92))], fill=trunk)

    # Middle ground clearing and river/forest floor.
    if rainforest:
        draw.ellipse((-180, int(h * 0.61), w + 220, int(h * 1.08)), fill=(43, 106, 93, 255))
        draw.ellipse((-220, int(h * 0.72), w + 260, int(h * 1.12)), fill=(71, 124, 103, 255))
        for _ in range(22):
            x = rng.randint(0, w)
            y = rng.randint(int(h * 0.72), h)
            draw.line((x, y, x + rng.randint(-12, 12), y - rng.randint(45, 120)),
                      fill=(71, 133, 73, 190), width=rng.randint(3, 8))
    else:
        draw.ellipse((-200, int(h * 0.66), w + 200, int(h * 1.12)), fill=(76, 91, 50, 255))
        draw.polygon([(0, int(h * 0.70)), (w, int(h * 0.64)), (w, h), (0, h)],
                     fill=(91, 83, 53, 190))

    # Layered foliage along edges, leaving a searchable center.
    foliage = Image.new("RGBA", size, (0, 0, 0, 0))
    fd = ImageDraw.Draw(foliage, "RGBA")
    for side in (-1, 1):
        for _ in range(54):
            x = rng.randint(-45, int(w * 0.30)) if side < 0 else rng.randint(int(w * 0.70), w + 45)
            y = rng.randint(20, h - 80)
            r = rng.randint(28, 90)
            color = rng.choice(leaf_colors)
            _leaf(fd, x, y, r, color, rng.uniform(-1.2, 1.2))
    foliage = foliage.filter(ImageFilter.GaussianBlur(radius=1.2))
    image = Image.alpha_composite(image, foliage)

    # Fine grain and vignette make the procedural scene feel less flat.
    arr = np.asarray(image.convert("RGB"), dtype=np.int16)
    noise_rng = np.random.default_rng(_seed(habitat + "grain"))
    noise = noise_rng.normal(0, 3.2, arr.shape[:2])[..., None]
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    image = Image.fromarray(arr, "RGB").convert("RGBA")
    vignette = Image.new("L", size, 0)
    vd = ImageDraw.Draw(vignette)
    vd.ellipse((-int(w * .30), -int(h * .15), int(w * 1.30), int(h * 1.12)), fill=205)
    vignette = vignette.filter(ImageFilter.GaussianBlur(radius=int(w * .20)))
    dark = Image.new("RGBA", size, (0, 14, 8, 95))
    image = Image.composite(image, Image.alpha_composite(image, dark), vignette)
    return image


def _shape_helpers(canvas_size: tuple[int, int]):
    art = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    mask = Image.new("L", canvas_size, 0)
    ad = ImageDraw.Draw(art, "RGBA")
    md = ImageDraw.Draw(mask)

    def ellipse(box, fill, outline=None, width=1):
        ad.ellipse(box, fill=fill, outline=outline, width=width)
        md.ellipse(box, fill=255)

    def polygon(points, fill, outline=None, width=1):
        ad.polygon(points, fill=fill)
        md.polygon(points, fill=255)
        if outline:
            ad.line(points + [points[0]], fill=outline, width=width, joint="curve")

    def rounded(box, radius, fill, outline=None, width=1):
        ad.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)
        md.rounded_rectangle(box, radius=radius, fill=255)

    return art, mask, ad, ellipse, polygon, rounded


def _capybara() -> tuple[Image.Image, Image.Image]:
    art, mask, d, ellipse, polygon, rounded = _shape_helpers((1000, 650))
    dark = (72, 48, 32, 255); body = (151, 101, 61, 255); light = (194, 139, 88, 220)
    rounded((205, 455, 310, 620), 42, (102, 67, 43, 255), dark, 12)
    rounded((570, 450, 680, 620), 42, (101, 66, 42, 255), dark, 12)
    ellipse((105, 170, 745, 545), body, dark, 16)
    ellipse((225, 205, 590, 365), light)
    ellipse((620, 155, 905, 430), (166, 111, 67, 255), dark, 15)
    ellipse((790, 285, 970, 450), (188, 131, 82, 255), dark, 12)
    ellipse((650, 118, 715, 195), (112, 73, 48, 255), dark, 9)
    ellipse((780, 112, 850, 200), (112, 73, 48, 255), dark, 9)
    d.ellipse((807, 238, 832, 263), fill=(18, 18, 15, 255))
    d.ellipse((815, 241, 823, 249), fill=(255, 255, 235, 255))
    d.ellipse((920, 365, 950, 390), fill=(36, 24, 20, 255))
    d.arc((836, 345, 930, 425), start=20, end=130, fill=(88, 48, 34, 255), width=7)
    return art, mask


def _okapi() -> tuple[Image.Image, Image.Image]:
    art, mask, d, ellipse, polygon, rounded = _shape_helpers((1000, 760))
    dark = (54, 35, 31, 255); body = (116, 58, 45, 255); red = (154, 78, 55, 255)
    # Legs first.
    legs = [(250, 460, 335, 730), (400, 455, 485, 730), (610, 440, 690, 725), (705, 430, 785, 720)]
    for box in legs:
        rounded(box, 25, (85, 55, 46, 255), dark, 10)
    ellipse((125, 235, 700, 555), body, dark, 16)
    ellipse((210, 245, 570, 375), red)
    polygon([(600, 300), (690, 85), (790, 100), (730, 385)], body, dark, 15)
    ellipse((690, 40, 940, 235), (130, 72, 54, 255), dark, 14)
    polygon([(715, 65), (680, 0), (750, 32)], (128, 73, 55, 255), dark, 9)
    polygon([(850, 65), (900, 2), (895, 92)], (128, 73, 55, 255), dark, 9)
    rounded((770, 6, 790, 64), 7, (73, 49, 40, 255), dark, 5)
    rounded((824, 8, 844, 67), 7, (73, 49, 40, 255), dark, 5)
    polygon([(115, 310), (45, 360), (128, 388)], (74, 44, 36, 255), dark, 9)
    # White zebra-like leg bars—the reveal payoff.
    for x0, _, x1, _ in legs:
        for y in (495, 555, 615):
            d.rounded_rectangle((x0 + 4, y, x1 - 4, y + 24), radius=10,
                                fill=(230, 226, 205, 245))
            d.rounded_rectangle((x0 + 6, y + 28, x1 - 6, y + 42), radius=7,
                                fill=(44, 34, 32, 245))
    d.ellipse((825, 102, 849, 126), fill=(15, 14, 13, 255))
    d.ellipse((833, 105, 840, 112), fill=(255, 250, 225, 255))
    d.ellipse((904, 160, 930, 180), fill=(30, 23, 22, 255))
    return art, mask


def _tapir() -> tuple[Image.Image, Image.Image]:
    art, mask, d, ellipse, polygon, rounded = _shape_helpers((1000, 650))
    dark = (45, 38, 34, 255); body = (83, 67, 55, 255); light = (139, 114, 90, 220)
    rounded((215, 445, 325, 620), 38, (58, 48, 41, 255), dark, 11)
    rounded((565, 440, 675, 620), 38, (58, 48, 41, 255), dark, 11)
    ellipse((105, 175, 730, 535), body, dark, 16)
    ellipse((210, 205, 570, 340), light)
    ellipse((615, 185, 875, 445), (96, 78, 64, 255), dark, 14)
    polygon([(820, 300), (985, 330), (940, 420), (815, 410)], (103, 83, 67, 255), dark, 12)
    ellipse((642, 135, 710, 225), (52, 43, 38, 255), dark, 9)
    ellipse((755, 140, 825, 230), (52, 43, 38, 255), dark, 9)
    d.ellipse((798, 250, 824, 276), fill=(15, 14, 13, 255))
    d.ellipse((806, 253, 814, 261), fill=(255, 250, 225, 255))
    d.ellipse((942, 354, 972, 378), fill=(25, 21, 19, 255))
    return art, mask


_ANIMAL_BUILDERS = {
    "CAPYBARA": _capybara,
    "OKAPI": _okapi,
    "TAPIR": _tapir,
}


def _place_animal(scene: Image.Image, answer: str, difficulty: str) -> tuple[Image.Image, Image.Image]:
    art, mask = _ANIMAL_BUILDERS[answer]()
    sizes = {
        "medium": (600, 420),
        "hard": (455, 350),
        "expert": (375, 275),
    }
    target = sizes[difficulty]
    art = art.resize(target, Image.Resampling.LANCZOS)
    mask = mask.resize(target, Image.Resampling.LANCZOS)
    positions = {
        "CAPYBARA": (222, 845),
        "OKAPI": (305, 805),
        "TAPIR": (390, 930),
    }
    x, y = positions[answer]

    reveal = scene.copy().convert("RGBA")
    shadow = Image.new("RGBA", reveal.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow, "RGBA")
    sd.ellipse((x + int(target[0] * .10), y + int(target[1] * .74),
                x + int(target[0] * .91), y + int(target[1] * .96)), fill=(0, 0, 0, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=18))
    reveal = Image.alpha_composite(reveal, shadow)
    reveal.alpha_composite(art, (x, y))

    clue = scene.copy().convert("RGBA")
    black = Image.new("RGBA", target, (0, 0, 0, 255))
    clue.paste(black, (x, y), mask)

    # Foreground vegetation partially screens harder rounds but never breaks the outline entirely.
    if difficulty in {"hard", "expert"}:
        fg = Image.new("RGBA", reveal.size, (0, 0, 0, 0))
        fd = ImageDraw.Draw(fg, "RGBA")
        rng = random.Random(_seed(answer + difficulty))
        count = 18 if difficulty == "hard" else 26
        for _ in range(count):
            bx = rng.randint(x - 45, x + target[0] + 35)
            by = rng.randint(y + int(target[1] * .55), y + target[1] + 80)
            height = rng.randint(55, 170)
            fd.line((bx, by, bx + rng.randint(-28, 28), by - height),
                    fill=(32, 91, 49, 225), width=rng.randint(5, 11))
            _leaf(fd, bx + rng.randint(-18, 18), by - height,
                  rng.randint(18, 38), (46, 118, 58, 235), rng.uniform(-1, 1))
        fg = fg.filter(ImageFilter.GaussianBlur(radius=0.7))
        reveal = Image.alpha_composite(reveal, fg)
        clue = Image.alpha_composite(clue, fg)

    return clue.convert("RGB"), reveal.convert("RGB")


def _local_habitat_pair(answer, habitat, pose, clue_dst, reveal_dst, size, cost_sink,
                        scene_ref="", difficulty="medium"):
    del pose, size, cost_sink, scene_ref
    answer = str(answer).strip().upper()
    if answer not in _ANIMAL_BUILDERS:
        raise RuntimeError(f"Unsupported deterministic animal: {answer}")
    scene = _scene(str(habitat))
    clue, reveal = _place_animal(scene, answer, str(difficulty).lower())
    Path(clue_dst).parent.mkdir(parents=True, exist_ok=True)
    clue.save(clue_dst, quality=95)
    reveal.save(reveal_dst, quality=95)
    return "deterministic_habitat_pair", True


def _quiz() -> dict:
    shared = ("a lush Amazon rainforest riverbank at dawn, pale mist above calm water, "
              "layered emerald foliage and soft shafts of sunlight")
    return {
        "title": "Can You Spot All 3 Hidden Animals?",
        "category": "wild animals",
        "hook": "Find all three.",
        "outro": "",
        "items": [
            {
                "subject": "capybara", "answer": "CAPYBARA", "difficulty": "medium",
                "clue_visual": "solid black silhouette of a capybara in profile",
                "reveal_visual": "a capybara in the same pose", "habitat": shared,
                "pose": "standing side-on on the riverbank", "color": "teal",
                "confusables": ["beaver", "wombat"],
                "reaction": "Warm-up!", "fact": "Capybaras are the world's largest rodents.",
            },
            {
                "subject": "okapi", "answer": "OKAPI", "difficulty": "hard",
                "clue_visual": "solid black silhouette of an okapi angled through forest grass",
                "reveal_visual": "an okapi in the same pose", "habitat": (
                    "a sun-dappled Congo rainforest path, tall tree trunks, amber haze and dense ferns"),
                "pose": "angled slightly away in the middle distance", "color": "amber",
                "confusables": ["deer", "horse", "zebra"],
                "reaction": "No hints!", "fact": "Okapis are the closest living relatives of giraffes.",
            },
            {
                "subject": "South American tapir", "answer": "TAPIR", "difficulty": "expert",
                "clue_visual": "solid black silhouette of a tapir partly screened by riverbank plants",
                "reveal_visual": "a tapir in the same pose", "habitat": shared,
                "pose": "head lowered near the water, angled toward camera", "color": "teal",
                "confusables": ["wild boar", "capybara", "anteater"],
                "reaction": "Final boss!", "fact": "Tapirs use their short flexible snouts to grasp leaves.",
            },
        ],
    }


def _tts(text: str, output_path: str, voice: str = "echo", **kwargs) -> str:
    del voice, kwargs
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    edge = shutil.which("edge-tts")
    if edge:
        command = [edge, "--voice", "en-US-AriaNeural", "--rate", "+8%",
                   "--text", text, "--write-media", str(output)]
        run = subprocess.run(command, capture_output=True, text=True)
        if run.returncode == 0 and output.is_file() and output.stat().st_size > 1000:
            return str(output)
    wav_path = output.with_suffix(".wav")
    espeak = shutil.which("espeak-ng") or shutil.which("espeak")
    if not espeak:
        raise RuntimeError("Neither edge-tts nor espeak is available")
    subprocess.run([espeak, "-v", "en-us", "-s", "185", "-p", "52", "-a", "165",
                    "-w", str(wav_path), text], check=True)
    subprocess.run([qp.FF, "-y", "-v", "error", "-i", str(wav_path),
                    "-codec:a", "libmp3lame", "-q:a", "2", str(output)], check=True)
    wav_path.unlink(missing_ok=True)
    return str(output)


def _music(path: Path, seconds: float = 16.0) -> Path:
    sample_rate = 48000
    count = int(sample_rate * seconds)
    t = np.arange(count, dtype=np.float64) / sample_rate
    audio = np.zeros(count, dtype=np.float64)
    notes = [261.63, 329.63, 392.00, 523.25, 392.00, 329.63, 293.66, 392.00]
    beat = 0.30
    for i in range(int(seconds / beat) + 1):
        start = int(i * beat * sample_rate)
        end = min(count, start + int(beat * sample_rate))
        if start >= count:
            break
        local = np.arange(end - start, dtype=np.float64) / sample_rate
        freq = notes[i % len(notes)]
        env = np.exp(-local * 7.0) * np.minimum(1.0, local * 35.0)
        tone = (np.sin(2 * np.pi * freq * local)
                + .35 * np.sin(2 * np.pi * freq * 2 * local)) * env
        audio[start:end] += tone * .20
        # Soft kick every two beats.
        if i % 2 == 0:
            kick = np.sin(2 * np.pi * (72 - 28 * local) * local) * np.exp(-local * 15)
            audio[start:end] += kick * .16
    # Airy shaker.
    rng = np.random.default_rng(20260830)
    noise = rng.normal(0, 1, count)
    gate = ((np.sin(2 * np.pi * (1 / beat) * 2 * t) > .82).astype(float))
    audio += noise * gate * .018
    audio = np.clip(audio, -0.95, 0.95)
    pcm = (audio * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())
    return path


def _description(category, title, items, hook, output_dir, cost_sink=None):
    del category, hook, cost_sink
    answers = ", ".join(str(item.get("answer", "")).title() for item in items)
    text = (
        f"{title}\n\nThree animals are hiding in their real habitats. The rounds climb from "
        "warm-up to no-hints to final boss—lock your guess before the shadow fills with color.\n\n"
        f"Answers: {answers}. How many did you spot before the reveal?\n\n"
        "#shorts #quiz #animals #trivia #spottheanimal\n"
    )
    path = Path(output_dir) / "youtube_description.txt"
    path.write_text(text, encoding="utf-8")
    return str(path)


def _install_offline_contract(output_dir: Path) -> None:
    legacy = qp._legacy
    legacy.HABITAT = True
    legacy.FAL_OPENER = False
    legacy.generate_quiz = lambda category, n_items=3, cost_sink=None, operator_direction="": _quiz()
    legacy.factcheck_quiz = lambda quiz, cost_sink=None: (quiz, [])
    legacy._habitat_pair = _local_habitat_pair
    legacy.grade_quiz_visuals = lambda *args, **kwargs: {
        "too_easy": False,
        "reveal_matches_answer": True,
        "anatomy_ok": True,
        "first_guess": "uncertain",
        "first_crop_confidence": 25,
    }
    legacy.quiz_readability_issues = lambda *args, **kwargs: []
    legacy.generate_quiz_description = _description
    legacy.ep.generate_tts = _tts

    music_path = _music(output_dir / "offline_upbeat.wav")
    legacy.get_music_path = lambda *args, **kwargs: str(music_path)

    def forbidden(*args, **kwargs):
        raise RuntimeError("Offline Quiz V2.3 attempted an external generation call")

    legacy.ep.generate_image = forbidden
    legacy.ep._claude = forbidden


def main() -> None:
    output_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "qa_render").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    _install_offline_contract(output_dir)

    result = qp.run_quiz_pipeline(
        "wild animals",
        str(output_dir),
        n_items=3,
        voice="echo",
        operator_direction="Deterministic mascot-free post-merge Quiz V2.3 verification render.",
        progress_cb=lambda message: print(message, flush=True),
        variants=("a",),
        primary_variant="a",
    )
    result_path = output_dir / "result.json"
    result_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "output_path": result.get("output_path"),
        "duration_sec": result.get("duration_sec"),
        "status": result.get("status"),
        "degraded_reasons": result.get("degraded_reasons"),
        "actual_cost": result.get("actual_cost"),
        "quiz_creative": result.get("quiz_creative"),
        "items": result.get("items"),
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()
