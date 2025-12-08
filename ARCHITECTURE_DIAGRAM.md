┌───────────────────────────────────────────────────────────────────────────────┐
│                               RETROVUE “STATION”                              │
│                    (MP3/AAC → PCM decoding + scheduling)                      │
└───────────────────────────────────────────────────────────────────────────────┘

                 STATION CLOCK A: DECODE METRONOME / SEGMENT TIMELINE
                 (wall-clock driven ~21.333ms per frame, independent of Tower)

               ┌─────────────────────────────────────────────────────┐
               │        Clock A (Station Decode Metronome)           │
               │  - Owns segment timing (THINK/DO)                   │
               │  - Uses wall clock to advance content time          │
               │  - Paces decode consumption: ~21.333ms per frame   │
               │  - Ensures songs play at real duration              │
               │  - Monotonic, wall-clock-fidelity                   │
               │  - Never observes Tower state                       │
               │  - Never alters pacing based on socket state        │
               │  - Drives *decode pacing*, NOT socket pacing        │
               └─────────────────────────────────────────────────────┘
                                  │
                                  │ "it's time for the next PCM frame"
                                  ▼
                     ┌────────────────────────────────────────┐
                     │      Station Decoder (FFmpeg)          │
                     │  - Decodes 1024-sample PCM frames      │
                     │  - Clock A paces consumption           │
                     │    (~21.333ms per frame)               │
                     │  - Ensures real-time playback          │
                     └────────────────────────────────────────┘
                                  │
                                  │ PCM frames (4096 bytes each)
                                  │ (after Clock A pacing)
                                  ▼
               (send immediately when available; no pacing on socket writes)
               ┌─────────────────────────────────────────────────────┐
               │           Unix Domain Socket Output                 │
               │    (station → tower, pure PCM byte pipe)           │
               │  - Non-blocking writes                              │
               │  - Drop-on-full semantics                           │
               │  - NO timing / cadence assumptions                  │
               └─────────────────────────────────────────────────────┘



┌───────────────────────────────────────────────────────────────────────────────┐
│                        TOWER (ENCODER + BROADCAST ENGINE)                     │
│       *Tower owns ALL PCM/broadcast timing. Station never sets broadcast.*    │
└───────────────────────────────────────────────────────────────────────────────┘

                     TOWER CLOCK B: PCM CADENCE / BROADCAST TEMPO
                     (strict 21.333 ms, 48kHz / 1024 samples)
                     *Sole authority for broadcast timing*

              ┌────────────────────────────────────────────────┐
              │                AudioPump (Tower)               │
              │   **THE ONE TRUE METRONOME FOR PCM TIMING**    │
              │ Fires every 21.333ms (48kHz / 1024 samples)    │
              └────────────────────────────────────────────────┘
                                │
                                │ on every tick:
                                ▼
                     ┌──────────────────────────────┐
                     │   PCM Ingest Buffer (Tower)  │
                     │ Reads 1 frame from socket    │
                     │ If empty → silence/tone      │
                     └──────────────────────────────┘
                                │
                                │ selected PCM frame
                                ▼
                     ┌────────────────────────────────┐
                     │   EncoderManager.next_frame    │
                     │ (selection logic + fallback)   │
                     │ - choose PCM/silence/tone      │
                     │ - push to FFmpeg via supervisor│
                     │ - enforce PCM continuity       │
                     └────────────────────────────────┘
                                │
                                │ PCM frame
                                ▼
             ┌────────────────────────────────────────────────────────┐
             │              FFmpeg Supervisor (Tower)                 │
             │ - Write PCM to FFmpeg stdin (non-blocking)             │
             │ - Boot priming (fast burst)                            │
             │ - Restart logic, liveness checks                       │
             │ - NO OUTPUT TIMING — FFmpeg runs free                  │
             └────────────────────────────────────────────────────────┘
                                │
                                │ MP3 output frames (free-running)
                                ▼
                (drain immediately, no pacing, no sleeps)
       ┌───────────────────────────────────────────────────────┐
       │     MP3 Drain Thread (Tower, output boundary)         │
       │ Reads MP3 frames whenever FFmpeg produces them        │
       │ Pushes them into MP3 buffer                           │
       └───────────────────────────────────────────────────────┘
                                │
                                │ MP3 frames
                                ▼
                    ┌──────────────────────────────┐
                    │       MP3 Output Buffer      │
                    └──────────────────────────────┘
                                │
                                │ get_frame()
                                ▼
               ┌────────────────────────────────────────────────┐
               │        Tower Runtime Main Loop (no timing)     │
               │ - Immediately broadcasts MP3 frames            │
               │ - NO sleeps, NO pacing, NO cadence estimation  │
               └────────────────────────────────────────────────┘
                                │
                                ▼
                     ┌──────────────────────────────┐
                     │       HTTP Broadcast         │
                     │ (Shoutcast-style responses)  │
                     └──────────────────────────────┘
