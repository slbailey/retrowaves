import logging
import os
import time
from typing import Optional

from station.music_logic.media_library import MediaLibrary
from station.music_logic.rotation import RotationManager
from station.dj_logic.dj_engine import DJEngine
from station.broadcast_core.audio_event import AudioEvent
from station.broadcast_core.playout_engine import PlayoutEngine
from station.outputs.factory import create_output_sink
from station.outputs.tower_pcm_sink import TowerPCMSink
from station.outputs.tower_control import TowerControlClient
from station.state.dj_state_store import DJStateStore

logger = logging.getLogger(__name__)


class Station:
    """
    Phase 7 station orchestrator:
    - Loads MediaLibrary and RotationManager
    - Emits synthetic THINK/DO events to the DJ
    - Uses a simple PlayoutQueue (no audio)
    - Supports warm-start recovery with state persistence
    """

    def __init__(self) -> None:
        self._load_dotenv_simple()
        # Load library from environment
        self.library = MediaLibrary.from_env()

        # Initialize rotation (Phase 1 minimal)
        self.rotation = RotationManager(
            self.library.regular_tracks,
            self.library.holiday_tracks
        )

        # DJ assets path from environment (fallback to ./cache)
        dj_path = os.getenv("DJ_PATH") or os.path.join(os.path.dirname(os.path.dirname(__file__)), "cache")

        # Phase 7: Initialize state store
        state_path = os.getenv("DJ_STATE_PATH", "/tmp/appalachia_dj_state.json")
        self.state_store = DJStateStore(path=state_path)

        # Initialize DJ engine
        self.dj = DJEngine(
            playout_engine=None,  # Will be set after engine creation
            rotation_manager=self.rotation,
            dj_asset_path=dj_path
        )

        # Phase 7: Load saved state (warm-start recovery)
        saved = self.state_store.load()
        if saved:
            self.dj.from_dict(saved)
            logger.info("[STATION] Warm start: DJ state restored.")
        else:
            logger.info("[STATION] Cold start: no previous state found.")

        # Output sink - Tower PCM socket (replaces HTTP streaming)
        tower_socket_path = os.getenv("TOWER_SOCKET_PATH", "/var/run/retrowaves/pcm.sock")
        tower_host = os.getenv("TOWER_HOST", "127.0.0.1")
        tower_port = int(os.getenv("TOWER_PORT", "8005"))
        
        # Initialize Tower PCM sink (connects to Tower's Unix socket)
        self.sink = TowerPCMSink(socket_path=tower_socket_path)
        logger.info(f"[STATION] Tower PCM sink initialized (socket={tower_socket_path})")
        
        # Initialize Tower control client (for sending commands to Tower)
        self.tower_control = TowerControlClient(tower_host=tower_host, tower_port=tower_port)
        logger.info(f"[STATION] Tower control client initialized (url=http://{tower_host}:{tower_port})")

        # Real playout engine with DJ callback and output sink (Architecture 3.2)
        self.engine = PlayoutEngine(dj_callback=self.dj, output_sink=self.sink, tower_control=self.tower_control)
        
        # Set playout engine reference in DJ
        self.dj.set_playout_engine(self.engine)
        
        # Lifecycle state tracking per contract SL1/SL2
        # Per contract: Lifecycle is defined at Station level, not at transport level
        self._lifecycle_state = {
            "station_starting_up": False,
            "station_shutting_down": False
        }

    def start(self) -> None:
        """
        Start the station.
        
        Phase 7: On warm start, don't seed a song - let DJ THINK handle it.
        On cold start, seed the first song.
        """
        saved = self.state_store.load()
        
        if saved:
            # Warm start: Don't choose anything; playout picks up cleanly
            # The first THINK will kickstart DJIntent
            logger.info("[STATION] Warm start: waiting for DJ THINK on first segment.")
            # Note: We still need to seed something to start the playout loop
            # But we'll let the DJ decide what to play first via THINK
            # For now, we'll seed a song but the DJ will override it
            first_song = self.rotation.select_next_song()
            self.engine.queue_audio([AudioEvent(first_song, "song")])
        else:
            # Cold start: Choose first song
            first_song = self.rotation.select_next_song()
            self.engine.queue_audio([AudioEvent(first_song, "song")])
            logger.info(f"[STATION] Cold start: seeded first song - {first_song}")
        
        # Connect to Tower (TowerPCMSink handles connection automatically on first write)
        # No explicit start() needed - sink connects on demand
        
        # SL1.3: Send lifecycle event BEFORE starting playout
        # Per SL1.3: Lifecycle event MUST be sent before playout begins to guarantee
        # that THINK events cannot fire before the lifecycle notification is transmitted
        # Send station_starting_up event to Tower (only once per contract SL1/SL2)
        if self.tower_control and not self._lifecycle_state["station_starting_up"]:
            if self.tower_control.send_event(
                event_type="station_starting_up",
                timestamp=time.monotonic(),
                metadata={}
            ):
                self._lifecycle_state["station_starting_up"] = True
                logger.info("Sent station_starting_up event to Tower")
        elif self._lifecycle_state["station_starting_up"]:
            logger.debug("station_starting_up event already sent, skipping duplicate")
        
        # SL1.4: Start playout loop AFTER lifecycle event is sent (non-blocking - runs in background thread)
        # Per SL1.4: Startup MUST not block playout once initiated
        # Per SL1.3: Playout MUST start AFTER lifecycle event to ensure proper ordering
        # PlayoutEngine.run() starts a background thread, so startup returns immediately
        logger.info("Starting playout engine...")
        self.engine.run()  # This starts the playout loop in a background thread
        logger.info("Playout engine started (startup complete, playout running in background)")

    def stop(self) -> None:
        """
        Stop the station and save state.
        
        Phase 7: Saves DJ state before shutdown.
        """
        # Save DJ state before stopping
        try:
            state = self.dj.to_dict()
            self.state_store.save(state)
            logger.info("[STATION] DJ state saved.")
        except Exception as e:
            logger.error(f"[STATION] Failed to save DJ state: {e}")
        
        # Close Tower PCM sink connection
        self.sink.close()
        
        # Stop the engine
        self.engine.stop()

    @staticmethod
    def _load_dotenv_simple(dotenv_path: Optional[str] = None) -> None:
        """
        Minimal .env loader (no external dependencies).
        - Supports KEY=VALUE lines
        - Ignores comments (#) and blank lines
        - Does not handle quotes or escapes
        """
        # Default to /etc/retrowaves/station.env if not specified
        if dotenv_path is None:
            # Try system location first, then fallback to station directory for development
            system_path = "/etc/retrowaves/station.env"
            dev_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
            if os.path.exists(system_path):
                path = system_path
            elif os.path.exists(dev_path):
                path = dev_path
            else:
                # Neither exists, try system path anyway (will silently fail if not found)
                path = system_path
        else:
            path = dotenv_path
        
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()
                    if key and value and key not in os.environ:
                        os.environ[key] = value
        except OSError:
            pass

