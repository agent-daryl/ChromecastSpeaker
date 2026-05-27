# ChromecastSpeaker

Send combined avatar image + audio to a Chromecast via the Cast v2 protocol. Uses ffmpeg to merge an image with TTS audio into a single MP4, so the Chromecast displays the image while speaking simultaneously.

```
python3 chromecast_demo.py
```

## Requirements

- Python 3.9+
- `pip install pychromecast gTTS imageio[ffmpeg] imageio-ffmpeg pillow`
- Firewall: port 8002/tcp must be open
- Chromecast IP configured as `CAST_IP` at top of script

## How It Works

Same Cast v2 protocol as NestSpeaker, but adds an ffmpeg step:

1. gTTS generates TTS audio as `.mp3`
2. ffmpeg merges avatar image + audio into single `.mp4`
3. Single `LOAD` command plays the MP4 — image stays on screen while audio plays

## Configuration

Change `CAST_IP` at the top of `chromecast_demo.py` to point to your Chromecast.

## Files

| File | Purpose |
|--|--|
| `chromecast_demo.py` | Full demo: avatar display + simultaneous audio |
| `Daryl_Agent_Avatar.png` | AI agent avatar image |
