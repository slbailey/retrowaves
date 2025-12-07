#!/usr/bin/env python3
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer

MP3_FILE = "test.mp3"

# Loop an MP3 FOREVER and output as MP3 stream
FFMPEG_CMD = [
    "ffmpeg",
    "-hide_banner",
    "-loglevel", "warning",
    "-stream_loop", "-1",      # loop forever
    "-i", MP3_FILE,
    "-f", "mp3",
    "-c:a", "libmp3lame",      # or "mp3" if you lack libmp3lame
    "pipe:1"
]

class MP3StreamHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.end_headers()

        # Start ffmpeg loop
        process = subprocess.Popen(
            FFMPEG_CMD,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        try:
            while True:
                chunk = process.stdout.read(4096)
                if not chunk:
                    break
                self.wfile.write(chunk)
        except BrokenPipeError:
            pass  # client disconnected

        process.kill()


def run_server():
    server = HTTPServer(("0.0.0.0", 8001), MP3StreamHandler)
    print("Streaming MP3 on http://localhost:8001/")
    server.serve_forever()


if __name__ == "__main__":
    run_server()
