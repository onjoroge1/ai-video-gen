# REELFORGE — AI YouTube Video Pipeline

Turn a single text prompt into a complete, ready-to-upload YouTube video.

**Pipeline:** Claude (script) → Google Cloud TTS (voiceover) → Pexels + DALL·E (visuals) → MoviePy (assembly) → MP4

---

## Prerequisites

- Python 3.10+
- FFmpeg installed and on your PATH
- API keys for: Anthropic, Google Cloud, Pexels, OpenAI

---

## 1. Install FFmpeg

**macOS:**
```bash
brew install ffmpeg
```

**Ubuntu/Debian:**
```bash
sudo apt-get install ffmpeg
```

**Windows:**
Download from https://ffmpeg.org/download.html and add to PATH.

---

## 2. Install Python dependencies

```bash
cd yt-pipeline
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

---

## 3. Set up API Keys

### Anthropic (Claude)
1. Get key from https://console.anthropic.com
2. Set env variable: `export ANTHROPIC_API_KEY=sk-ant-...`

### Google Cloud TTS
1. Go to https://console.cloud.google.com
2. Create a project, enable the **Cloud Text-to-Speech API**
3. Create a **Service Account** → download the JSON key file
4. Set: `export GOOGLE_APPLICATION_CREDENTIALS=/path/to/your-key.json`

### Pexels (free)
1. Sign up at https://www.pexels.com/api/
2. Get your free API key
3. Set: `export PEXELS_API_KEY=your-key-here`

### OpenAI (DALL·E 3 — optional if using Pexels only)
1. Get key from https://platform.openai.com
2. Set: `export OPENAI_API_KEY=sk-...`

---

## 4. Run the server

```bash
python app.py
```

Open your browser at: **http://localhost:8000**

---

## 5. Using the UI

1. Type a video topic in the prompt box
2. Set duration (1–15 minutes)
3. Choose visual source (Pexels+DALL·E recommended)
4. Pick a voice
5. Hit **Generate Video** — watch the pipeline run in real-time
6. When done, download the MP4 or view the full script

---

## Project Structure

```
yt-pipeline/
├── app.py           # FastAPI server + SSE streaming
├── pipeline.py      # Core pipeline: script, audio, visuals, assembly
├── requirements.txt
├── static/
│   └── index.html   # Web UI
└── README.md
```

---

## Customisation Tips

### Change the voice
In `pipeline.py → generate_audio()`, update `voice.name` to any Google Cloud TTS voice.
Full list: https://cloud.google.com/text-to-speech/docs/voices

### Adjust video quality
In `pipeline.py → assemble_video()`, change `bitrate` (e.g. `"8000k"` for higher quality)
or `preset` (`"slow"` for better compression, `"ultrafast"` for speed).

### Add background music
In `assemble_video()`, load an audio file with `AudioFileClip` and use
`CompositeAudioClip([narration, music.volumex(0.15)])` before writing.

### Add captions (subtitles)
After generating audio, run OpenAI Whisper on the final MP3 to get word-level
timestamps, then use MoviePy's `TextClip` to overlay them frame-by-frame.

---

## Troubleshooting

| Error | Fix |
|---|---|
| `GOOGLE_APPLICATION_CREDENTIALS not set` | Export the path to your GCP service account JSON |
| `FFmpeg not found` | Install FFmpeg and ensure it's in your system PATH |
| `moviepy.error: No file found` | Check Pexels API key is valid and has quota remaining |
| `DALL-E quota exceeded` | Switch visual mode to "Pexels only" in the UI |
| Port 8000 in use | Change port in `app.py`: `uvicorn.run(..., port=8080)` |

---

## Roadmap

- [ ] Auto-upload to YouTube via YouTube Data API v3
- [ ] AI-generated thumbnail (DALL·E → overlay title text)
- [ ] OpenAI Whisper captions burned into video
- [ ] Background music track selection
- [ ] Batch generation (multiple videos from a list of prompts)
- [ ] Voice cloning via ElevenLabs swap-in
