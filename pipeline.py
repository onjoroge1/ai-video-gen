"""
YouTube Video Generation Pipeline
Stages: Script (Claude) → Audio (Google TTS) → Visuals (Pexels + DALL-E) → Assembly (MoviePy)
"""

import os
import json
import asyncio
import tempfile
import textwrap
from pathlib import Path
from typing import Optional, Callable
import anthropic
import requests
import numpy as np
from PIL import Image
import io

# ─── System Prompts ────────────────────────────────────────────────────────────

_SCRIPT_JSON_SCHEMA = """
Return ONLY valid JSON with this exact structure:
{
  "title": "YouTube-optimized video title (under 70 chars)",
  "description": "YouTube description (2-3 paragraphs, SEO-friendly)",
  "tags": ["tag1", "tag2", ...],
  "hook": "Opening 5-second hook line (must grab attention instantly)",
  "scenes": [
    {
      "id": 1,
      "narration": "Spoken narration text for this scene",
      "on_screen_text": "Short text to display on screen (5 words max, or null)",
      "visual_cue": "Detailed description of what should be shown visually",
      "search_terms": ["keyword1", "keyword2"],
      "duration_seconds": 8
    }
  ],
  "outro": "Final call-to-action sentence"
}"""

EXPLAINER_SYSTEM_PROMPT = f"""You are a YouTube video scriptwriter. Given a topic prompt, generate a complete, \
engaging video script structured as JSON. Be specific, punchy, and optimized for viewer retention.
{_SCRIPT_JSON_SCHEMA}

Guidelines:
- Hook scene should be 3-5 seconds
- Regular scenes 5-15 seconds each
- Total duration should match the requested minutes
- visual_cue should be vivid and specific for image/video search
- search_terms should be 2-3 keywords great for stock footage search"""

PROMO_SYSTEM_PROMPT = f"""You are a promotional video and ad scriptwriter. Given a product, brand, or campaign \
prompt, generate a punchy, high-conversion video script structured as JSON. Think like a top agency creative director.
{_SCRIPT_JSON_SCHEMA}

Guidelines — STRICT:
- Follow this exact arc: Hook (3-5s) → Problem (5-8s) → Solution (5-8s) → Payoff (5-8s) → CTA (3-5s)
- Each scene MUST be 5-8 seconds max. Keep it tight and punchy.
- Hook: Create urgency, curiosity, or a bold claim in under 5 seconds
- Problem: Articulate a pain point the viewer immediately recognizes
- Solution: Name the product/service explicitly, show it in action
- Payoff: Social proof, results, transformation — make the viewer want it
- CTA: Single clear next step (subscribe, sign up, visit, download)
- visual_cue should describe bold, commercial-grade, cinematic imagery
- search_terms should target premium stock footage or AI video prompts
- Total duration should match the requested minutes
- Tone: confident, aspirational, direct — no filler"""

CUSTOM_SCRIPT_SYSTEM_PROMPT = f"""You are a video production assistant. You will receive raw voiceover/narration text.
Your job is to:
1. Split the text into logical scenes (each 5-15 seconds of narration when spoken aloud)
2. For each scene, generate: visual_cue, search_terms, on_screen_text, duration_seconds
3. Generate overall: title, description, tags, hook (from the opening), outro (from the closing)
{_SCRIPT_JSON_SCHEMA}

Important rules:
- The narration field must contain the EXACT text from the user input, split into scenes
- Do NOT rewrite, embellish, or rephrase the narration — preserve it verbatim
- Only add visual metadata (visual_cue, search_terms, on_screen_text) around the original text
- Estimate duration_seconds based on typical speech rate (~150 words/minute)"""


# ─── Script Generation ─────────────────────────────────────────────────────────

def _parse_script_json(raw: str) -> dict:
    """Strip markdown fences and parse JSON from Claude's response."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()
    return json.loads(raw)


async def generate_script(prompt: str, duration_minutes: int = 3, video_type: str = "explainer") -> dict:
    """Use Claude to generate a structured video script."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    system = PROMO_SYSTEM_PROMPT if video_type == "promo" else EXPLAINER_SYSTEM_PROMPT

    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=4000,
        system=system,
        messages=[{
            "role": "user",
            "content": f"Create a {duration_minutes}-minute YouTube video script about: {prompt}"
        }]
    )

    return _parse_script_json(response.content[0].text)


async def process_custom_script(custom_text: str, duration_minutes: int = 3) -> dict:
    """Accept raw voiceover text — Claude splits into scenes and adds visual metadata."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=8000,   # long scripts (10-15 min) overflow 4000 -> truncated JSON
        system=CUSTOM_SCRIPT_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": (
                f"Split this voiceover text into scenes for a {duration_minutes}-minute video "
                f"and add visual metadata:\n\n{custom_text}"
            )
        }]
    )

    return _parse_script_json(response.content[0].text)


# ─── Audio Generation (Google Cloud TTS) ───────────────────────────────────────

async def generate_audio(scenes: list, output_dir: str, progress_cb: Optional[Callable] = None) -> list:
    """Generate MP3 audio for each scene using Google Cloud TTS."""
    from google.cloud import texttospeech

    client = texttospeech.TextToSpeechClient()
    audio_files = []

    voice = texttospeech.VoiceSelectionParams(
        language_code="en-US",
        name="en-US-Journey-D",          # Natural, engaging voice
        ssml_gender=texttospeech.SsmlVoiceGender.MALE,
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=0.95,              # Slightly slower = easier to follow
        pitch=0.0,
    )

    for i, scene in enumerate(scenes):
        text = scene.get("narration", "")
        if not text:
            audio_files.append(None)
            continue

        synthesis_input = texttospeech.SynthesisInput(text=text)
        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config,
        )

        path = os.path.join(output_dir, f"audio_scene_{i:03d}.mp3")
        with open(path, "wb") as f:
            f.write(response.audio_content)
        audio_files.append(path)

        if progress_cb:
            progress_cb(f"Generated audio for scene {i+1}/{len(scenes)}")

    return audio_files


# ─── Visual Fetching (Pexels + DALL-E) ─────────────────────────────────────────

def _fetch_pexels_image(search_terms: list, output_path: str) -> bool:
    """Try to fetch a relevant image from Pexels."""
    api_key = os.environ.get("PEXELS_API_KEY", "")
    if not api_key:
        return False

    query = " ".join(search_terms[:2])
    url = "https://api.pexels.com/v1/search"
    headers = {"Authorization": api_key}
    params = {"query": query, "per_page": 5, "orientation": "landscape"}

    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        data = r.json()
        photos = data.get("photos", [])
        if not photos:
            return False
        # Pick the best resolution landscape image
        photo = photos[0]
        img_url = photo["src"]["large2x"]
        img_r = requests.get(img_url, timeout=15)
        with open(output_path, "wb") as f:
            f.write(img_r.content)
        return True
    except Exception:
        return False


def _fetch_pexels_video(search_terms: list, output_path: str) -> bool:
    """Try to fetch a short video clip from Pexels."""
    api_key = os.environ.get("PEXELS_API_KEY", "")
    if not api_key:
        return False

    query = " ".join(search_terms[:2])
    url = "https://api.pexels.com/videos/search"
    headers = {"Authorization": api_key}
    params = {"query": query, "per_page": 5, "orientation": "landscape"}

    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        data = r.json()
        videos = data.get("videos", [])
        if not videos:
            return False
        video = videos[0]
        # Get HD file
        files = sorted(video.get("video_files", []),
                       key=lambda x: x.get("width", 0), reverse=True)
        hd_files = [f for f in files if f.get("width", 0) <= 1920]
        if not hd_files:
            return False
        vid_url = hd_files[0]["link"]
        vid_r = requests.get(vid_url, timeout=30, stream=True)
        with open(output_path, "wb") as f:
            for chunk in vid_r.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except Exception:
        return False


def _generate_dalle_image(visual_cue: str, output_path: str) -> bool:
    """Generate an image using DALL-E 3."""
    from openai import OpenAI
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return False

    client = OpenAI(api_key=api_key)
    prompt = (
        f"Cinematic, photorealistic YouTube video visual: {visual_cue}. "
        "16:9 aspect ratio, high quality, professional lighting, no text or watermarks."
    )
    try:
        response = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1792x1024",
            quality="standard",
            n=1,
        )
        img_url = response.data[0].url
        img_r = requests.get(img_url, timeout=20)
        with open(output_path, "wb") as f:
            f.write(img_r.content)
        return True
    except Exception:
        return False


def _create_fallback_image(text: str, output_path: str, scene_id: int):
    """Create a simple solid-color placeholder image with text."""
    colors = [
        (30, 30, 50), (40, 20, 40), (20, 40, 40),
        (50, 30, 20), (20, 30, 50), (40, 40, 20),
    ]
    bg = colors[scene_id % len(colors)]
    img = Image.new("RGB", (1920, 1080), bg)
    img.save(output_path, "PNG")


async def _generate_runway_video(visual_cue: str, output_path: str, timeout: int = 300) -> bool:
    """Generate a ~5-second video clip using Runway ML Gen-3 Alpha Turbo."""
    api_key = os.environ.get("RUNWAYML_API_SECRET", "")
    if not api_key:
        return False

    headers = {
        "Authorization": f"Bearer {api_key}",
        "X-Runway-Version": "2024-11-06",
        "Content-Type": "application/json",
    }

    prompt = (
        f"Cinematic, smooth camera motion, professional lighting: {visual_cue}. "
        "16:9 aspect ratio, photorealistic, no text or watermarks."
    )

    # Step 1: Submit generation task
    try:
        submit_resp = requests.post(
            "https://api.dev.runwayml.com/v1/image_to_video",
            headers=headers,
            json={
                "model": "gen3a_turbo",
                "promptText": prompt,
                "duration": 5,
                "ratio": "16:9",
                "watermark": False,
            },
            timeout=30,
        )
        submit_resp.raise_for_status()
        task_id = submit_resp.json()["id"]
    except Exception:
        return False

    # Step 2: Poll for completion
    poll_url = f"https://api.dev.runwayml.com/v1/tasks/{task_id}"
    elapsed = 0
    poll_interval = 5

    while elapsed < timeout:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
        try:
            poll_resp = requests.get(poll_url, headers=headers, timeout=10)
            poll_resp.raise_for_status()
            task = poll_resp.json()
            status = task.get("status")

            if status == "SUCCEEDED":
                video_url = task["output"][0]
                vid_r = requests.get(video_url, timeout=60, stream=True)
                with open(output_path, "wb") as f:
                    for chunk in vid_r.iter_content(chunk_size=8192):
                        f.write(chunk)
                return True
            elif status in ("FAILED", "CANCELLED"):
                return False
        except Exception:
            return False

    return False


def _safe_single_card_prompt(topic: str) -> str:
    """A generic, IP-safe establishing image for single-card mode. Never depicts real
    people, celebrities, copyrighted characters, or brand logos — the topic only steers
    mood/setting, and all specifics are carried by the on-screen title, not the artwork."""
    topic = (topic or "").strip()[:200]
    return (
        f"An original, atmospheric cinematic establishing background illustration evoking the "
        f"MOOD of this topic: \"{topic}\". Painterly, moody, high production value, rich depth, "
        "dramatic lighting. IMPORTANT: no real people, no faces, no celebrities, no identifiable "
        "individuals, no copyrighted characters, no brand names or logos, no text, letters, "
        "numbers, or watermark. Entirely original design that does not resemble any specific "
        "existing film, TV show, book cover, or video game. Leave some clean negative space for a title."
    )


async def fetch_visuals(scenes: list, output_dir: str, mode: str = "both",
                         progress_cb: Optional[Callable] = None,
                         single_prompt: str = "") -> list:
    """
    Fetch or generate one visual per scene.
    mode: "pexels" | "dalle" | "both" | "ai_video" | "single"
      - "single": generate ONE original topic card and hold it across every scene
        (voiceover-essay style). Cheapest + most IP-safe; the title carries the specifics.
    Returns list of file paths (images or videos).
    """
    visual_files = []

    # Single-card mode: one image, reused for the whole video (generated once).
    if mode == "single":
        topic = single_prompt or (scenes[0].get("visual_cue", "") if scenes else "")
        card_path = os.path.join(output_dir, "topic_card.jpg")
        got = _generate_dalle_image(_safe_single_card_prompt(topic), card_path)
        if not got:
            card_path = os.path.join(output_dir, "topic_card_placeholder.png")
            _create_fallback_image(topic, card_path, 0)
        card = {"path": card_path, "type": "image",
                "source": "single" if got else "placeholder"}
        if progress_cb:
            progress_cb(f"Generated one topic card ({card['source']}) — held across {len(scenes)} scenes")
        return [dict(card) for _ in scenes]

    for i, scene in enumerate(scenes):
        search_terms = scene.get("search_terms", ["nature"])
        visual_cue = scene.get("visual_cue", "")
        base_name = f"visual_scene_{i:03d}"
        success = False

        # AI Video mode — Runway ML
        if mode == "ai_video":
            vid_path = os.path.join(output_dir, f"{base_name}_runway.mp4")
            if progress_cb:
                progress_cb(f"Generating AI video for scene {i+1}/{len(scenes)} (may take 60-90s)...")
            if await _generate_runway_video(visual_cue, vid_path):
                visual_files.append({"path": vid_path, "type": "video", "source": "runway"})
                success = True

        # Try Pexels video first (most dynamic)
        if not success and mode in ("pexels", "both"):
            vid_path = os.path.join(output_dir, f"{base_name}.mp4")
            if _fetch_pexels_video(search_terms, vid_path):
                visual_files.append({"path": vid_path, "type": "video", "source": "pexels"})
                success = True
            else:
                img_path = os.path.join(output_dir, f"{base_name}.jpg")
                if _fetch_pexels_image(search_terms, img_path):
                    visual_files.append({"path": img_path, "type": "image", "source": "pexels"})
                    success = True

        # Fall back to DALL-E (also used as fallback for ai_video mode)
        if not success and mode in ("dalle", "both", "ai_video"):
            img_path = os.path.join(output_dir, f"{base_name}_dalle.jpg")
            if _generate_dalle_image(visual_cue, img_path):
                visual_files.append({"path": img_path, "type": "image", "source": "dalle"})
                success = True

        # Final fallback: solid color placeholder
        if not success:
            img_path = os.path.join(output_dir, f"{base_name}_placeholder.png")
            _create_fallback_image(visual_cue, img_path, i)
            visual_files.append({"path": img_path, "type": "image", "source": "placeholder"})

        if progress_cb:
            src = visual_files[-1]["source"]
            progress_cb(f"Got visual for scene {i+1}/{len(scenes)} ({src})")

    return visual_files


# ─── Video Assembly (MoviePy) ───────────────────────────────────────────────────

def _get_audio_duration(audio_path: str) -> float:
    """Get duration of an audio file in seconds."""
    from moviepy.editor import AudioFileClip
    clip = AudioFileClip(audio_path)
    d = clip.duration
    clip.close()
    return d


def _ken_burns(image_path: str, duration: float, zoom_direction: str = "in") -> "VideoClip":
    """Apply Ken Burns effect (subtle zoom/pan) to a static image."""
    from moviepy.editor import ImageClip
    import moviepy.video.fx.all as vfx

    clip = ImageClip(image_path).set_duration(duration)

    # Resize to 1920x1080, cropping to fill
    clip = clip.resize(height=1080)
    if clip.w < 1920:
        clip = clip.resize(width=1920)

    # Crop to exact 1920x1080
    clip = clip.crop(x_center=clip.w / 2, y_center=clip.h / 2, width=1920, height=1080)

    # Subtle zoom effect via lambda resize
    zoom_factor = 0.06  # 6% zoom over the scene duration
    if zoom_direction == "in":
        clip = clip.fl_image(lambda img: _zoom_frame(img, 1.0))  # start
        def make_frame(t):
            scale = 1.0 + zoom_factor * (t / duration)
            return _zoom_image(np.array(Image.open(image_path).convert("RGB").resize((1920, 1080))), scale)
        from moviepy.editor import VideoClip
        clip = VideoClip(make_frame, duration=duration)
    else:
        def make_frame(t):
            scale = 1.0 + zoom_factor * (1 - t / duration)
            return _zoom_image(np.array(Image.open(image_path).convert("RGB").resize((1920, 1080))), scale)
        from moviepy.editor import VideoClip
        clip = VideoClip(make_frame, duration=duration)

    return clip


def _zoom_frame(img: np.ndarray, scale: float) -> np.ndarray:
    return img


def _zoom_image(img: np.ndarray, scale: float) -> np.ndarray:
    """Zoom into the center of an image."""
    h, w = img.shape[:2]
    new_h = int(h / scale)
    new_w = int(w / scale)
    y1 = (h - new_h) // 2
    x1 = (w - new_w) // 2
    cropped = img[y1:y1 + new_h, x1:x1 + new_w]
    resized = np.array(Image.fromarray(cropped).resize((w, h), Image.LANCZOS))
    return resized


def _prepare_video_clip(visual: dict, duration: float, idx: int):
    """Prepare a visual clip (image with Ken Burns, or video trimmed to duration)."""
    from moviepy.editor import VideoFileClip, ImageClip
    import moviepy.video.fx.all as vfx

    path = visual["path"]

    if visual["type"] == "video":
        try:
            clip = VideoFileClip(path)
            # Trim or loop to match audio duration
            if clip.duration < duration:
                clip = clip.loop(duration=duration)
            else:
                clip = clip.subclip(0, duration)
            # Resize to 1920x1080
            clip = clip.resize(height=1080)
            if clip.w < 1920:
                clip = clip.resize(width=1920)
            clip = clip.crop(x_center=clip.w / 2, y_center=clip.h / 2, width=1920, height=1080)
            clip = clip.without_audio()
            return clip
        except Exception:
            pass  # Fall through to image handling

    # Image — apply Ken Burns
    try:
        direction = "in" if idx % 2 == 0 else "out"
        return _ken_burns(path, duration, direction)
    except Exception:
        return ImageClip(path).set_duration(duration).resize((1920, 1080))


# ─── Brand Helpers ─────────────────────────────────────────────────────────────

def _hex_to_rgb(hex_color: str) -> tuple:
    """Convert hex color string to (R, G, B) tuple."""
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def _download_logo(logo_url: str, output_dir: str) -> str | None:
    """Download brand logo and resize to max 150px height."""
    try:
        logo_path = os.path.join(output_dir, "brand_logo.png")
        r = requests.get(logo_url, timeout=15)
        img = Image.open(io.BytesIO(r.content)).convert("RGBA")
        max_h = 150
        if img.height > max_h:
            ratio = max_h / img.height
            img = img.resize((int(img.width * ratio), max_h), Image.LANCZOS)
        img.save(logo_path, "PNG")
        return logo_path
    except Exception:
        return None


def _make_lower_third(text: str, brand_color: str, font_name: str, width: int = 1920) -> np.ndarray:
    """Create a branded lower-third bar as a numpy array (RGBA)."""
    from PIL import ImageDraw, ImageFont
    r, g, b = _hex_to_rgb(brand_color)
    bar = Image.new("RGBA", (width, 80), (r, g, b, 200))
    draw = ImageDraw.Draw(bar)
    try:
        font = ImageFont.truetype(font_name.replace("-", " "), 36)
    except Exception:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (width - text_w) // 2
    y = (80 - text_h) // 2
    draw.text((x, y), text, fill=(255, 255, 255, 255), font=font)
    return np.array(bar)


def _make_end_card(brand_config: dict, logo_path: str | None, duration: float = 4.0):
    """Create a branded end card: solid color + logo + CTA text."""
    from moviepy.editor import ImageClip, CompositeVideoClip, TextClip

    r, g, b = _hex_to_rgb(brand_config.get("primary_color", "#e63946"))
    bg = Image.new("RGB", (1920, 1080), (r, g, b))
    bg_clip = ImageClip(np.array(bg)).set_duration(duration)
    layers = [bg_clip]

    if logo_path and os.path.exists(logo_path):
        logo_clip = (ImageClip(logo_path)
                     .set_duration(duration)
                     .set_position(("center", 0.35), relative=True))
        layers.append(logo_clip)

    cta = brand_config.get("cta_text", "")
    if cta:
        try:
            txt = TextClip(
                cta, fontsize=56, color="white",
                font=brand_config.get("font_name", "DejaVu-Sans-Bold"),
                method="label",
            )
            txt = (txt.set_duration(duration)
                      .set_position(("center", 0.65), relative=True))
            layers.append(txt)
        except Exception:
            pass

    return CompositeVideoClip(layers, size=(1920, 1080))


# ─── Video Assembly ────────────────────────────────────────────────────────────

def assemble_video(
    script: dict,
    audio_files: list,
    visual_files: list,
    output_path: str,
    progress_cb: Optional[Callable] = None,
    brand_config: Optional[dict] = None,
) -> str:
    """Stitch everything into a final MP4, with optional brand overlays."""
    from moviepy.editor import (
        VideoFileClip, ImageClip, AudioFileClip,
        concatenate_videoclips, CompositeVideoClip,
        TextClip, ColorClip
    )

    scenes = script.get("scenes", [])
    clips = []

    # Prepare brand assets
    logo_path = None
    if brand_config:
        logo_url = brand_config.get("logo_url")
        if logo_url:
            output_dir = os.path.dirname(output_path)
            logo_path = _download_logo(logo_url, output_dir)

    for i, (scene, audio_path, visual) in enumerate(zip(scenes, audio_files, visual_files)):
        if not audio_path or not os.path.exists(audio_path):
            continue

        # Get exact duration from audio
        audio_clip = AudioFileClip(audio_path)
        duration = audio_clip.duration

        if progress_cb:
            progress_cb(f"Assembling scene {i+1}/{len(scenes)}...")

        # Prepare video/image clip
        video_clip = _prepare_video_clip(visual, duration, i)
        video_clip = video_clip.set_audio(audio_clip)

        # Add on-screen text overlay
        on_screen = scene.get("on_screen_text")
        if on_screen:
            try:
                if brand_config:
                    # Branded lower-third bar
                    bar_arr = _make_lower_third(
                        on_screen,
                        brand_config.get("primary_color", "#e63946"),
                        brand_config.get("font_name", "DejaVu-Sans-Bold"),
                    )
                    bar_clip = (ImageClip(bar_arr)
                                .set_duration(duration)
                                .set_position(("center", 0.82), relative=True)
                                .crossfadein(0.3).crossfadeout(0.3))
                    video_clip = CompositeVideoClip([video_clip, bar_clip])
                else:
                    # Default white text overlay
                    txt = TextClip(
                        on_screen, fontsize=64, color="white",
                        font="DejaVu-Sans-Bold", stroke_color="black",
                        stroke_width=2, method="label",
                    )
                    txt = (txt.set_duration(duration)
                              .set_position(("center", 0.75), relative=True)
                              .crossfadein(0.3).crossfadeout(0.3))
                    video_clip = CompositeVideoClip([video_clip, txt])
            except Exception:
                pass

        # Logo watermark (persistent across all scenes)
        if brand_config and logo_path:
            try:
                logo_clip = (ImageClip(logo_path)
                             .set_duration(duration)
                             .set_position((1920 - 170, 20))
                             .set_opacity(0.7))
                video_clip = CompositeVideoClip([video_clip, logo_clip])
            except Exception:
                pass

        # Add crossfade between scenes
        if i > 0:
            video_clip = video_clip.crossfadein(0.4)

        clips.append(video_clip)

    if not clips:
        raise ValueError("No clips were assembled — check audio/visual generation.")

    # Branded end card
    if brand_config and (brand_config.get("cta_text") or logo_path):
        if progress_cb:
            progress_cb("Creating branded end card...")
        try:
            end_card = _make_end_card(brand_config, logo_path, duration=4.0)
            clips.append(end_card)
        except Exception:
            pass

    if progress_cb:
        progress_cb("Concatenating all scenes...")

    final = concatenate_videoclips(clips, method="compose", padding=-0.4)

    if progress_cb:
        progress_cb("Rendering final video (this may take a minute)...")

    final.write_videofile(
        output_path,
        fps=24,
        codec="libx264",
        audio_codec="aac",
        bitrate="4000k",
        threads=4,
        preset="fast",
        logger=None,
    )

    # Cleanup
    for clip in clips:
        try:
            clip.close()
        except Exception:
            pass
    final.close()

    return output_path
