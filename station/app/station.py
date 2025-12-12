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
        
        # Lifecycle state machine (per SL2.2.3)
        # States: RUNNING, DRAINING, SHUTTING_DOWN
        self._lifecycle_state_enum = "RUNNING"  # Initial state
        
        # Lifecycle state tracking per contract T-EVENTS1
        # Per contract: Lifecycle events MUST be sent exactly once
        # Station MUST track whether lifecycle events have been sent to prevent duplicates
        self._lifecycle_state = {
            "station_starting_up": False,
            "station_shutting_down": False
        }
        
        # Max-wait timeout for long segments (per SL2.2.5)
        self._shutdown_timeout_seconds = 300.0  # 5 minutes default
        self._shutdown_start_time: Optional[float] = None
    
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
        
        # SL1.3: Set startup flag for initial THINK (may select startup announcement)
        # Per SL1.3: Startup announcement is selected during initial THINK phase
        self.dj.set_lifecycle_state(is_startup=True, is_draining=False)
        
        # SL1.2: Select first song BEFORE playout begins
        # This ensures first song is selected during startup, not during first THINK phase
        # Per SL1.2: First song selection occurs during startup, not during first THINK phase
        logger.info("Selecting first song...")
        first_song = self.rotation.select_next_song()
        if not first_song:
            raise RuntimeError("Failed to select first song: no tracks available")
        logger.info(f"First song selected: {first_song}")
        first_song_metadata = _get_mp3_metadata(first_song)
        first_audio_event = AudioEvent(first_song, "song", metadata=first_song_metadata)
        
        # SL1.3: Trigger initial THINK to select startup announcement (if available)
        # Per SL1.3: Startup announcement is selected during initial THINK phase
        # We trigger THINK by calling on_segment_started with a dummy segment
        # This allows DJEngine to select startup announcement during THINK
        dummy_segment = AudioEvent(first_song, "song", metadata=first_song_metadata)
        self.dj.on_segment_started(dummy_segment)
        
        # Check if startup announcement was selected
        startup_queue = []
        if self.dj.current_intent and self.dj.current_intent.next_song and self.dj.current_intent.next_song.type == "announcement":
            # Startup announcement was selected, queue it directly
            startup_announcement = self.dj.current_intent.next_song
            startup_queue.append(startup_announcement)
            logger.info(f"[LIFECYCLE] Startup announcement selected: {startup_announcement.path}")
            # Clear intent so first song THINK can run when announcement starts
            self.dj.current_intent = None
        else:
            logger.info("[LIFECYCLE] Startup announcement skipped (pool empty or not selected)")
        
        # Queue startup announcement (if selected) and first song
        # Per SL1.4: If startup announcement exists, first song THINK occurs after startup announcement starts
        if startup_queue:
            self.engine.queue_audio(startup_queue)
            logger.info("Startup announcement queued for playout")
        # Always queue first song (it will play after startup announcement if present)
        # When startup announcement starts, THINK will run to prepare intent for after first song
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
        
        # Update lifecycle state to RUNNING
        previous_state = self._lifecycle_state_enum
        self._lifecycle_state_enum = "RUNNING"
        self.running = True
        logger.info(f"[LIFECYCLE] State transition: {previous_state} → RUNNING")
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
        Stop Station gracefully per contracts (two-phase shutdown).
        
        Per SL2.1: Shutdown triggers (SIGTERM, SIGINT, stop()) all enter DRAINING
        Per SL2.2: PHASE 1 - Soft Shutdown (DRAINING): Current segment finishes, terminal THINK/DO allowed
        Per SL2.3: PHASE 2 - Hard Shutdown (SHUTTING_DOWN): State persistence, audio components close
        Per T-EVENTS1: station_shutting_down event MUST be sent exactly once.
        """
        if self._shutdown_initiated:
            logger.warning("Shutdown already initiated, ignoring duplicate stop() call")
            return
        
        logger.info("=== Station shutting down ===")
        self._shutdown_initiated = True
        
        # SL2.2.1: PHASE 1 - Enter DRAINING state immediately
        previous_state = self._lifecycle_state_enum
        logger.info("[SHUTDOWN] PHASE 1: Entering DRAINING state")
        self._lifecycle_state_enum = "DRAINING"
        logger.info(f"[LIFECYCLE] State transition: {previous_state} → DRAINING")
        self._shutdown_start_time = time.monotonic()
        
        # Set draining state in DJEngine and PlayoutEngine
        if self.dj:
            self.dj.set_lifecycle_state(is_startup=False, is_draining=True)
        if self.engine:
            self.engine.set_draining(True)
        
        # SL2.2.1: Current segment MUST be allowed to finish
        # SL2.2.2: DJ THINK MAY run one final time to prepare terminal intent
        # SL2.2.5: Wait for current segment to finish (with timeout)
        # PHASE 1 (DRAINING) is a true soft shutdown - MUST NOT interrupt playback
        # MUST NOT call: engine.request_shutdown(), engine.stop(), sink.close(), stop_event.set()
        logger.info("[SHUTDOWN] PHASE 1: Waiting for terminal playout to complete (soft shutdown - playback continues)...")
        if self.engine:
            # Wait for terminal playout to complete (terminal DO executed AND terminal segment finished if any)
            # This is the definitive signal, not thread liveness
            max_wait = self._shutdown_timeout_seconds
            start_wait = time.monotonic()
            logger.info(f"[SHUTDOWN] PHASE 1: Waiting for terminal playout to complete (timeout: {max_wait}s)...")
            
            while not self.engine._terminal_playout_complete and (time.monotonic() - start_wait) < max_wait:
                time.sleep(0.1)
            
            # Check if terminal playout completed
            if self.engine._terminal_playout_complete:
                logger.info("[SHUTDOWN] PHASE 1: Terminal playout complete - current song finished, shutdown announcement played (if any)")
                
                # Per T-EVENTS1: Send station_shutting_down event to Tower AFTER shutdown announcement finishes (only once)
                # This event MUST be sent after terminal playout completes, not when shutdown is initiated
                if self.tower_control and not self._lifecycle_state["station_shutting_down"]:
                    try:
                        success = self.tower_control.send_event(
                            event_type="station_shutting_down",
                            timestamp=time.monotonic(),
                            metadata={}
                        )
                        if success:
                            self._lifecycle_state["station_shutting_down"] = True
                            logger.info("Sent station_shutting_down event to Tower (after shutdown announcement finished)")
                        else:
                            logger.warning("Failed to send station_shutting_down event to Tower (Tower may be unavailable)")
                    except Exception as e:
                        logger.error(f"Error sending station_shutting_down event: {e}", exc_info=True)
                elif self._lifecycle_state["station_shutting_down"]:
                    logger.debug("station_shutting_down event already sent, skipping duplicate")
                elif not self.tower_control:
                    logger.warning("Tower control client not available, cannot send station_shutting_down event")
                
                logger.info("[SHUTDOWN] PHASE 1: Transitioning to PHASE 2 (hard shutdown)")
            else:
                # Check if playout thread has already stopped (might have exited early)
                thread_stopped = (self.engine._play_thread is None or not self.engine._play_thread.is_alive())
                if thread_stopped:
                    logger.warning(f"[SHUTDOWN] PHASE 1: Playout thread stopped but terminal playout not complete, forcing transition to PHASE 2")
                else:
                    logger.warning(f"[SHUTDOWN] PHASE 1: Timeout ({max_wait}s) exceeded waiting for terminal playout, forcing transition to PHASE 2")
                
                # Per T-EVENTS1: Send station_shutting_down event even if terminal playout didn't complete normally
                # This ensures the event is always sent, even in timeout/error cases
                if self.tower_control and not self._lifecycle_state["station_shutting_down"]:
                    try:
                        success = self.tower_control.send_event(
                            event_type="station_shutting_down",
                            timestamp=time.monotonic(),
                            metadata={}
                        )
                        if success:
                            self._lifecycle_state["station_shutting_down"] = True
                            logger.info("Sent station_shutting_down event to Tower (timeout/error case)")
                        else:
                            logger.warning("Failed to send station_shutting_down event to Tower (Tower may be unavailable)")
                    except Exception as e:
                        logger.error(f"Error sending station_shutting_down event: {e}", exc_info=True)
                elif self._lifecycle_state["station_shutting_down"]:
                    logger.debug("station_shutting_down event already sent, skipping duplicate")
                elif not self.tower_control:
                    logger.warning("Tower control client not available, cannot send station_shutting_down event")
        else:
            # Engine is None - send event immediately since there's no playout to wait for
            if self.tower_control and not self._lifecycle_state["station_shutting_down"]:
                try:
                    success = self.tower_control.send_event(
                        event_type="station_shutting_down",
                        timestamp=time.monotonic(),
                        metadata={}
                    )
                    if success:
                        self._lifecycle_state["station_shutting_down"] = True
                        logger.info("Sent station_shutting_down event to Tower (no engine)")
                    else:
                        logger.warning("Failed to send station_shutting_down event to Tower (Tower may be unavailable)")
                except Exception as e:
                    logger.error(f"Error sending station_shutting_down event: {e}", exc_info=True)
            elif self._lifecycle_state["station_shutting_down"]:
                logger.debug("station_shutting_down event already sent, skipping duplicate")
            elif not self.tower_control:
                logger.warning("Tower control client not available, cannot send station_shutting_down event")
        
        # SL2.3: PHASE 2 - Enter SHUTTING_DOWN state
        previous_state = self._lifecycle_state_enum
        logger.info("[SHUTDOWN] PHASE 2: Entering SHUTTING_DOWN state")
        self._lifecycle_state_enum = "SHUTTING_DOWN"
        logger.info(f"[LIFECYCLE] State transition: {previous_state} → SHUTTING_DOWN")
        self.running = False
        
        # SL2.3.2: No THINK or DO events MAY fire after SHUTTING_DOWN begins
        if self.engine:
            self.engine.set_dj_callback(None)  # Clear callback reference
        
        # SL2.3.3: Stop playout engine cleanly
        # CRITICAL: Only call engine.stop() AFTER terminal_playout_complete is True
        # engine.stop() sets stop_event which would cut audio if called too early
        if self.engine:
            # Verify terminal playout is complete before stopping
            if not self.engine._terminal_playout_complete:
                logger.warning("[SHUTDOWN] PHASE 2: Terminal playout not complete, waiting...")
                # Wait a bit more for terminal playout to complete
                max_wait = 5.0
                start_wait = time.monotonic()
                while not self.engine._terminal_playout_complete and (time.monotonic() - start_wait) < max_wait:
                    time.sleep(0.1)
            
            logger.info("[SHUTDOWN] PHASE 2: Terminal playout confirmed complete, stopping playout engine...")
            self.engine.stop()
            logger.info("[SHUTDOWN] PHASE 2: Playout engine stopped")
        
        # SL2.3.1: State persistence occurs ONLY in SHUTTING_DOWN phase
        if self.dj and self.state_store:
            try:
                logger.info("Saving DJ state...")
                state = self.dj.to_dict()
                self.state_store.save(state)
                logger.info("DJ state saved successfully")
            except Exception as e:
                logger.error(f"Failed to save DJ state: {e}", exc_info=True)
        
        # SL2.3.3: Close Tower PCM sink connection
        # CRITICAL: Only close sink AFTER terminal playout completes and engine is stopped
        # Closing sink would cut audio if called too early
        if self.sink:
            logger.info("[SHUTDOWN] PHASE 2: Terminal playout complete and engine stopped, closing Tower PCM sink...")
            self.sink.close()
            logger.info("[SHUTDOWN] PHASE 2: Tower PCM sink closed (audio output terminated)")
        
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
