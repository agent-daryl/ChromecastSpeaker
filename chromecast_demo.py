#!/usr/bin/env python3
"""Chromecast Ultra demo: display avatar + play audio simultaneously.

Uses ffmpeg to merge avatar image with TTS audio into a single MP4,
so the Chromecast shows the image while speaking.
"""

import json
import os
import shutil
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time

from http.server import HTTPServer, SimpleHTTPRequestHandler

class QuietHTTPHandler(SimpleHTTPRequestHandler):
    def log_error(self, format, *args):
        exc_name = getattr(args[0], '__class__', lambda: None).__name__
        if exc_name in ('ConnectionResetError', 'BrokenPipeError'):
            return
        super().log_error(format, *args)
from gtts import gTTS

from pychromecast.cast_channel_pb2 import CastMessage

SENDER = "sender-0"
RECEIVER = "receiver-0"
CNS = "urn:x-cast:com.google.cast.tp.connection"
RNS = "urn:x-cast:com.google.cast.receiver"
MNS = "urn:x-cast:com.google.cast.media"
APP = "CC1AD845"

CAST_IP = "10.10.100.70"
SRV_IP = "10.10.0.100"
PORT = 8002

_req_counters = {}


def _get_rid(ns):
    _req_counters.setdefault(ns, 0)
    _req_counters[ns] += 1
    return _req_counters[ns]


def cast_build(src, dst, ns, payload):
    m = CastMessage()
    m.protocol_version = 0
    m.source_id = src
    m.destination_id = dst
    m.namespace = ns
    m.payload_type = 0
    m.payload_utf8 = payload
    raw = m.SerializeToString()
    return struct.pack(">I", len(raw)) + raw


def cast_send(sock, src, dst, ns, d):
    d["requestId"] = _get_rid(ns)
    sock.send(cast_build(src, dst, ns, json.dumps(d)))


def cast_connect(sock, src, dst):
    sock.send(cast_build(src, dst, CNS, json.dumps({
        "type": "CONNECT",
        "userAgent": "DemoBot",
        "senderInfo": {"sdkType": 2, "version": "15.605.1.3", "platform": 4}
    })))


def cast_recv(sock, timeout=3):
    sock.settimeout(timeout)
    try:
        hdr = sock.recv(4)
        if len(hdr) < 4:
            return None, None
        n = struct.unpack(">I", hdr)[0]
        data = b""
        while len(data) < n:
            chunk = sock.recv(n - len(data))
            if not chunk:
                break
            data += chunk
        m = CastMessage()
        m.ParseFromString(data)
        try:
            p = json.loads(m.payload_utf8)
        except:
            p = None
        return m, p
    except:
        return None, None


def drain_for_status(sock, wait=4):
    """Drain responses for up to `wait` seconds, return all parsed dicts."""
    start = time.time()
    results = []
    while time.time() - start < wait:
        _, p = cast_recv(sock, min(2, start + wait - time.time()))
        if p:
            results.append(p)
    return results

def get_session(sock):
    cast_send(sock, SENDER, RECEIVER, RNS, {"type": "GET_STATUS"})
    for p in drain_for_status(sock, 4):
        if p.get("type") == "RECEIVER_STATUS":
            for a in p.get("status", {}).get("applications", []):
                if a.get("appId") == APP:
                    return a["sessionId"]

    cast_send(sock, SENDER, RECEIVER, RNS, {"type": "LAUNCH", "appId": APP})
    for p in drain_for_status(sock, 8):
        if p.get("type") == "RECEIVER_STATUS":
            for a in p.get("status", {}).get("applications", []):
                if a.get("appId") == APP:
                    return a["sessionId"]
    return None


def play_media(sock, sid, url, ctype, title):
    print(f"  Loading: {title}")
    cast_send(sock, SENDER, sid, MNS, {
        "type": "LOAD",
        "media": {
            "contentId": url,
            "contentType": ctype,
            "streamType": "BUFFERED",
            "metadata": {"type": 0}
        },
        "autoplay": True,
        "currentTime": 0
    })
    for _ in range(15):
        _, p = cast_recv(sock, 3)
        if p and p.get("type") == "MEDIA_STATUS":
            sl = p.get("status", [{}])
            st = sl[0].get("playerState", "?") if sl else "?"
            ir = sl[0].get("idleReason")
            err = sl[0].get("errorId")
            print(f"    MEDIA_STATUS: state={st} idleReason={ir}")
            if ir == "ERROR":
                print(f"    errorId={err}")
            return st, ir
    return "UNKNOWN", "NONE"


def main():
    os.chdir("/tmp")
    server = HTTPServer(("0.0.0.0", PORT), QuietHTTPHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"  HTTP server on :{PORT}")

    # Connect
    raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    raw.settimeout(10)
    raw.connect((CAST_IP, 8009))
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    sock = ctx.wrap_socket(raw, server_hostname=CAST_IP)
    print(f"  Connected to Chromecast at {CAST_IP}")

    # Handshake
    cast_connect(sock, SENDER, RECEIVER)
    cast_recv(sock, 2)
    print("  Handshake done.")

    # Get or launch session
    sid = get_session(sock)
    if not sid:
        print("  No session — aborting.")
        sock.close()
        return
    print(f"  Session: {sid}")

    # Open channel
    cast_connect(sock, SENDER, sid)
    cast_recv(sock, 2)
    print("  Media channel open.")

    # Step 1: Generate TTS audio
    msg = (
        "Hi there. I am Qwen Three Point Six, a twenty seven billion parameter "
        "artificial intelligence running locally on an AI server in Daryl's datacenter. "
        "My full model is qwen three point six, two seven b dense, with a two fifty six "
        "kilobyte context window. I run inside a Docker container on an Ubuntu machine "
        "powered by dual NVIDIA RTX three oh nine graphics cards and an Intel Core i seven "
        "processor. This machine, affectionately called the AI-box, handles all my "
        "inference work, while Daryl's RHEL server acts as my command terminal. "
        "We just cracked the Google Cast protocol to let me talk through a Chromecast, "
        "with no cloud API, no Google account, just raw sockets and a little bit of "
        "reverse engineering. It is pretty wild what you can do with local AI and a "
        "little patience. Nice to meet you!"
    )
    ts = int(time.time())
    mp3_fn = f"qwen_intro_{ts}.mp3"
    mp3_fp = f"/tmp/{mp3_fn}"
    gTTS(msg, lang="en").save(mp3_fp)
    print(f"  TTS: {mp3_fn}")

    # Step 2: Merge avatar image + audio into single MP4 using bundled ffmpeg
    import imageio_ffmpeg
    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

    av_src = "/home/daryl/Documents/ai_workloads/tools/ChromecastSpeaker/Daryl_Agent_Avatar.png"
    mp4_fn = f"qwen_intro_{ts}.mp4"
    mp4_fp = f"/tmp/{mp4_fn}"
    print("  Building combined video (avatar + audio) with ffmpeg ...")
    result = subprocess.run([
        FFMPEG, "-y",
        "-loop", "1", "-i", av_src,
        "-i", mp3_fp,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-tune", "stillimage",
        "-c:a", "aac",
        "-shortest",
        "-movflags", "+faststart",
        mp4_fp
    ], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ffmpeg failed: {result.stderr}")
        sock.close()
        return
    mp4_size = os.path.getsize(mp4_fp)
    print(f"  Combined video: {mp4_fn} ({mp4_size} bytes)")

    # Step 3: Play combined video
    mp4_url = f"http://{SRV_IP}:{PORT}/{mp4_fn}"
    st, ir = play_media(sock, sid, mp4_url, "video/mp4", "Avatar + audio")

    if ir != "ERROR":
        for _ in range(15):
            _, p = cast_recv(sock, 4)
            if p and p.get("type") == "MEDIA_STATUS":
                sl = p.get("status", [{}])
                st2 = sl[0].get("playerState", "?") if sl else "?"
                ir2 = sl[0].get("idleReason")
                print(f"    Follow-up: state={st2} idleReason={ir2}")
                if st2 in ("PLAYING", "BUFFERING"):
                    print("  Audio playing — listen up!")
                    time.sleep(30)
                    break
                elif st2 == "IDLE" and ir2 == "FINISHED":
                    print("  Playback finished.")
                    break

    # Cleanup
    for f in [mp3_fp, mp4_fp]:
        if os.path.exists(f):
            os.remove(f)
    sock.close()
    print("  Demo complete.")


if __name__ == "__main__":
    main()
