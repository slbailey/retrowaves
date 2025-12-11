import logging
import os
import time
from typing import Optional, Dict, Any
from pathlib import Path

from station.music_logic.media_library import MediaLibrary
from station.music_logic.rotation import RotationManager
from station.dj_logic.dj_engine import DJEngine
from station.dj_logic.asset_discovery import AssetDiscoveryManager
from station.broadcast_core.audio_event import AudioEvent
from station.broadcast_core.playout_engine import _get_mp3_metadata
from station.broadcast_core.playout_engine import PlayoutEngine
from station.outputs.factory import create_output_sink
from station.outputs.tower_pcm_sink import TowerPCMSink
from station.outputs.tower_control import TowerControlClient
from station.state.dj_state_store import DJStateStore

logger = logging.getLogger(__name__)


class Station:
    """
    Station orchestrator following Tower's robust, contract-driven architecture.
    
    Implements StationLifecycle Contract (SL1, SL2) and Tower Runtime Contract (T-EVENTS1):
    - SL1.1: Component Loading Order (MediaLibrary, AssetDiscoveryManager, DJStateStore before playout)
    - SL1.2: First Song Selection (before audio begins)
    - SL1.3: THINK Event Timing (no THINK before first segment)
    - SL1.4: Non-Blocking Startup
    - SL2.1: State Persistence (save all DJ state on shutdown)
    - SL2.2: Event Prohibition (no THINK/DO after shutdown begins)
    - SL2.3: Clean Audio Exit (stop all audio components cleanly)
    - T-EVENTS1: Lifecycle events (station_starting_up, station_shutting_down) MUST be sent exactly once
    """
    
    def __init__(self):
        """
        Initialize Station components.
        
        Per SL1.1: Components are created but not fully initialized until start().
        """
        # Load environment variables
        self._load_dotenv_simple()
        
        # Component references (initialized in start())
        self.library: Optional[MediaLibrary] = None
        self.asset_manager: Optional[AssetDiscoveryManager] = None
        self.state_store: Optional[DJStateStore] = None
        self.rotation: Optional[RotationManager] = None
        self.dj: Optional[DJEngine] = None
        self.engine: Optional[PlayoutEngine] = None
        self.sink: Optional[TowerPCMSink] = None
        self.tower_control: Optional[TowerControlClient] = None
        
        # Runtime state
        self.running = False
        self._shutdown_initiated = False
        
        # Lifecycle state tracking per contract T-EVENTS1
        # Per contract: Lifecycle events MUST be sent exactly once
        # Station MUST track whether lifecycle events have been sent to prevent duplicates
        self._lifecycle_state = {
            "station_starting_up": False,
            "station_shutting_down": False
        }
    
    def start(self):
        """
        Start Station with proper initialization order per contracts.
        
        Per SL1.1: MediaLibrary, AssetDiscoveryManager, DJStateStore MUST be loaded before playout.
        Per SL1.2: First song MUST be selected before audio begins.
        Per SL1.3: No THINK event MAY occur before first segment.
        Per SL1.4: Startup MUST not block playout once initiated.
        Per T-EVENTS1: station_starting_up event MUST be sent exactly once.
        """
        # Prevent multiple calls to start()
        if self.running:
            logger.warning("Station already started, ignoring duplicate start() call")
            return
        
        logger.info("=== Station starting ===")
        
        # SL1.1: Load MediaLibrary first
        logger.info("Loading MediaLibrary...")
        self.library = MediaLibrary.from_env()
        logger.info(f"MediaLibrary loaded: {len(self.library.regular_tracks)} regular, {len(self.library.holiday_tracks)} holiday tracks")
        
        # SL1.1: Initialize AssetDiscoveryManager and complete initial scan
        logger.info("Initializing AssetDiscoveryManager...")
        dj_path = os.getenv("DJ_PATH") or os.path.join(os.path.dirname(os.path.dirname(__file__)), "cache")
        self.asset_manager = AssetDiscoveryManager(Path(dj_path))
        # AssetDiscoveryManager performs initial scan in __init__, so it's ready now
        logger.info("AssetDiscoveryManager initialized and initial scan completed")
        
        # SL1.1: Load DJStateStore
        logger.info("Loading DJStateStore...")
        state_path = os.getenv("DJ_STATE_PATH", "/tmp/appalachia_dj_state.json")
        self.state_store = DJStateStore(path=state_path)
        logger.info("DJStateStore loaded")
        
        # Initialize RotationManager (needs MediaLibrary)
        logger.info("Initializing RotationManager...")
        self.rotation = RotationManager(
            self.library.regular_tracks,
            self.library.holiday_tracks
        )
        logger.info("RotationManager initialized")
        
        # Initialize DJEngine (needs RotationManager, AssetDiscoveryManager)
        logger.info("Initializing DJEngine...")
        # Initialize Tower control client first (needed for DJEngine events)
        tower_host = os.getenv("TOWER_HOST", "127.0.0.1")
        tower_port = int(os.getenv("TOWER_PORT", "8005"))
        tower_control = TowerControlClient(tower_host=tower_host, tower_port=tower_port)
        logger.info(f"Tower control client initialized (url=http://{tower_host}:{tower_port})")
        
        self.dj = DJEngine(
            playout_engine=None,  # Will be set after engine creation
            rotation_manager=self.rotation,
            dj_asset_path=dj_path,
            tower_control=tower_control
        )
        # Replace asset_manager with our initialized one (DJEngine creates its own, but we want to use ours)
        self.dj.asset_manager = self.asset_manager
        logger.info("DJEngine initialized")
        
        # SL1.1: Load persisted DJ state (warm-start recovery)
        saved = self.state_store.load()
        if saved:
            self.dj.from_dict(saved)
            logger.info("Warm start: DJ state restored from disk")
        else:
            logger.info("Cold start: no previous state found")
        
        # Initialize output sink (Tower PCM socket)
        logger.info("Initializing Tower PCM sink...")
        tower_socket_path = os.getenv("TOWER_SOCKET_PATH", "/var/run/retrowaves/pcm.sock")
        self.sink = TowerPCMSink(socket_path=tower_socket_path)
        logger.info(f"Tower PCM sink initialized (socket={tower_socket_path})")
        
        # Store tower_control for PlayoutEngine
        self.tower_control = tower_control
        
        # Initialize PlayoutEngine (needs DJ callback and output sink)
        logger.info("Initializing PlayoutEngine...")
        self.engine = PlayoutEngine(
            dj_callback=self.dj,
            output_sink=self.sink,
            tower_control=self.tower_control
        )
        # Set playout engine reference in DJ
        self.dj.set_playout_engine(self.engine)
        logger.info("PlayoutEngine initialized")
        
        # SL1.2: Select first song BEFORE playout begins
        # This ensures first song is selected during startup, not during first THINK phase
        # Per SL1.2: First song selection occurs during startup, not during first THINK phase
        logger.info("Selecting first song...")
        first_song = self.rotation.select_next_song()
        if not first_song:
            raise RuntimeError("Failed to select first song: no tracks available")
        logger.info(f"First song selected: {first_song}")
        
        # SL1.3: Queue first song BEFORE starting playout
        # Per SL1.3: No THINK event MAY occur before the first segment begins
        # By queuing the first song before starting playout, we ensure:
        # 1. First song is ready when playout starts
        # 2. THINK will only be triggered when the first segment actually begins (after startup completes)
        # 3. Startup is complete before any THINK events occur
        # Extract metadata for first song during startup (since it doesn't go through THINK phase)
        first_song_metadata = _get_mp3_metadata(first_song)
        first_audio_event = AudioEvent(first_song, "song", metadata=first_song_metadata)
        self.engine.queue_audio([first_audio_event])
        logger.info("First song queued for playout")
        
        # SL1.3: Send lifecycle event BEFORE starting playout
        # Per SL1.3: Lifecycle event MUST be sent before playout begins to guarantee
        # that THINK events cannot fire before the lifecycle notification is transmitted
        # Per T-EVENTS1: station_starting_up event MUST be sent exactly once
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
        
        self.running = True
        logger.info("=== Station started successfully ===")
    
    def run_forever(self):
        """
        Block forever like systemd would.
        
        Per SL2.2: Shutdown signal prevents new THINK/DO cycles.
        """
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Station shutdown requested via KeyboardInterrupt")
            self.stop()
    
    def stop(self):
        """
        Stop Station gracefully per contracts.
        
        Per SL2.1: All DJ/rotation state MUST be saved.
        Per SL2.2: No THINK or DO events MAY fire after shutdown begins.
        Per SL2.3: All audio components MUST exit cleanly.
        Per T-EVENTS1: station_shutting_down event MUST be sent exactly once.
        """
        if self._shutdown_initiated:
            logger.warning("Shutdown already initiated, ignoring duplicate stop() call")
            return
        
        logger.info("=== Station shutting down ===")
        self._shutdown_initiated = True
        self.running = False
        
        # Per T-EVENTS1: Send station_shutting_down event to Tower (only once)
        if self.tower_control and not self._lifecycle_state["station_shutting_down"]:
            try:
                success = self.tower_control.send_event(
                    event_type="station_shutting_down",
                    timestamp=time.monotonic(),
                    metadata={}
                )
                if success:
                    self._lifecycle_state["station_shutting_down"] = True
                    logger.info("Sent station_shutting_down event to Tower")
                else:
                    logger.warning("Failed to send station_shutting_down event to Tower (Tower may be unavailable)")
            except Exception as e:
                logger.error(f"Error sending station_shutting_down event: {e}", exc_info=True)
        elif self._lifecycle_state["station_shutting_down"]:
            logger.debug("station_shutting_down event already sent, skipping duplicate")
        elif not self.tower_control:
            logger.warning("Tower control client not available, cannot send station_shutting_down event")
        
        # SL2.2: Prevent new THINK/DO cycles
        # Per SL2.2: No THINK or DO events MAY fire after shutdown begins
        # First request shutdown (prevents callbacks in playout thread)
        # Then set callback to None (additional safety for race conditions)
        if self.engine:
            self.engine.request_shutdown()  # Set shutdown flag before modifying callback
            self.engine.set_dj_callback(None)  # Additional safety: clear callback reference
        
        # SL2.3: Stop playout engine cleanly (waits for current segment to finish)
        if self.engine:
            logger.info("Stopping playout engine...")
            self.engine.stop()
            logger.info("Playout engine stopped")
        
        # SL2.1: Save DJ state before shutdown
        if self.dj and self.state_store:
            try:
                logger.info("Saving DJ state...")
                state = self.dj.to_dict()
                self.state_store.save(state)
                logger.info("DJ state saved successfully")
            except Exception as e:
                logger.error(f"Failed to save DJ state: {e}", exc_info=True)
        
        # SL2.3: Close Tower PCM sink connection
        if self.sink:
            logger.info("Closing Tower PCM sink...")
            self.sink.close()
            logger.info("Tower PCM sink closed")
        
        logger.info("=== Station stopped ===")
    
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
