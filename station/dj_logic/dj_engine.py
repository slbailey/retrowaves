"""
DJ Engine for Appalachia Radio 3.1.

The DJ Brain is the sole source of programming decisions. It operates
in two distinct phases:
- Prep Window (THINK): Decides and selects concrete MP3 files
- Transition Window (DO): Executes pre-decided intent

Architecture 3.1 Reference:
- Section 2.1: The DJ Is the Brain
- Section 4: DJ Brain & Intent Model
- Section 4.3: DJ Prep Window Behavior (THINK)
- Section 4.4: DJ Transition Window Behavior (DO)
"""

import logging
import os
import random
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from station.broadcast_core.audio_event import AudioEvent
from station.broadcast_core.playout_engine import DJCallback, PlayoutEngine, _get_mp3_metadata
from station.dj_logic.intent_model import DJIntent
from station.dj_logic.ticklers import Tickler, GenerateIntroTickler, GenerateOutroTickler, RefillGenericIDTickler
from station.dj_logic.asset_discovery import AssetDiscoveryManager
from station.music_logic.rotation import RotationManager

logger = logging.getLogger(__name__)

# Setup file handler for contract-compliant logging (LOG1, LOG2, LOG3, LOG4)
# Per contract: /var/log/retrowaves/station.log, non-blocking, rotation-tolerant
try:
    import logging.handlers
    # Use WatchedFileHandler for rotation tolerance (per LOG3)
    handler = logging.handlers.WatchedFileHandler('/var/log/retrowaves/station.log', mode='a')
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    handler.setFormatter(formatter)
    # Wrap emit to handle write failures gracefully (per LOG4)
    original_emit = handler.emit
    def safe_emit(record):
        try:
            original_emit(record)
        except (IOError, OSError):
            # Logging failures degrade silently per contract LOG4
            pass
    handler.emit = safe_emit
    # Prevent duplicate handlers on module reload
    if not any(isinstance(h, logging.handlers.WatchedFileHandler)
               and getattr(h, 'baseFilename', None) == '/var/log/retrowaves/station.log'
               for h in logger.handlers):
        logger.addHandler(handler)
    logger.propagate = False  # Avoid duplicate logs
except Exception:
    # Logging must never crash component per LOG4
    # Catch all exceptions (including I/O errors) to prevent import-time failures
    pass


class DJEngine:
    """
    DJ Brain implementation for Architecture 3.1.
    
    Manages DJ state, makes programming decisions during Prep Windows,
    and executes pre-decided intents during Transition Windows.
    
    Implements DJCallback protocol to receive lifecycle events from PlayoutEngine.
    
    Architecture 3.1 Reference: Section 4.1 (DJ State Includes)
    """
    
    def __init__(self, playout_engine: Optional[PlayoutEngine] = None, rotation_manager: Optional[RotationManager] = None, dj_asset_path: Optional[str] = None, tower_control=None):
        """
        Initialize the DJ Engine with all required components.
        
        Args:
            playout_engine: PlayoutEngine instance to queue audio events
            rotation_manager: RotationManager instance for song selection
            dj_asset_path: Path to DJ assets directory (default: from DJ_PATH env var or cache/)
            tower_control: Optional TowerControlClient for sending heartbeat events
        """
        self.playout_engine = playout_engine
        self.rotation_manager: Optional[RotationManager] = rotation_manager
        self._tower_control = tower_control
        
        # DJ asset paths
        if dj_asset_path:
            self.dj_asset_path = Path(dj_asset_path)
        else:
            dj_path_env = os.getenv("DJ_PATH")
            if dj_path_env:
                self.dj_asset_path = Path(dj_path_env)
            else:
                self.dj_asset_path = Path("cache")
        
        # DJ State (Architecture 3.1 Section 4.1)
        self.last_played_songs: list[str] = []  # Last N played songs (song IDs/paths)
        self.max_history = 10  # Keep last 10 songs
        
        # Phase 5: Legal ID Timing Enforcement
        self.last_legal_id_time: Optional[datetime] = None
        self.legal_id_interval = 3600  # every hour (seconds)
        self.legal_id_grace = 300  # ±5 min window acceptable (seconds)
        
        # Phase 5: Generic Station ID Cooldown
        self.last_generic_id_time: Optional[datetime] = None
        self.generic_id_min = 180  # don't drop IDs closer than 3 minutes apart (seconds)
        
        # Phase 5: Talk Frequency & Talk Avoidance Rules
        self.last_talk_time: Optional[datetime] = None
        self.min_talk_spacing = 300  # 5 min minimum between talks (seconds)
        self.max_talk_silence = 1800  # 30 min – must talk eventually (seconds)
        
        # Phase 5: Intro & Outro Cooldowns (last 5 uses)
        self.intro_history: list[str] = []  # List of intro paths used recently
        self.outro_history: list[str] = []  # List of outro paths used recently
        self.cooldown_len = 5  # cannot reuse same file within last 5 uses
        
        # Current DJIntent (built during THINK, executed during DO)
        self.current_intent: Optional[DJIntent] = None
        
        # Phase 6: Tickler Queue
        self.ticklers: list[Tickler] = []
        
        # Phase 6: Track available generic IDs for pool health checks
        self.available_generic_ids: list[str] = []
        self._scan_generic_ids()
        
        # Phase 9: Asset Discovery Manager for intros/outros
        self.asset_manager = AssetDiscoveryManager(self.dj_asset_path)
        
        # Lifecycle state (set by Station, observed during THINK)
        self._is_startup = False  # True during initial startup THINK
        self._is_draining = False  # True when Station is in DRAINING state
        
        # Invariant: Terminal intent may only be queued once per lifecycle
        self._terminal_intent_queued = False  # Tracks if terminal intent has been queued
        
        logger.info("DJ Engine initialized (Phase 6)")
    
    def set_playout_engine(self, playout_engine: PlayoutEngine) -> None:
        """
        Set the playout engine reference.
        
        Args:
            playout_engine: PlayoutEngine instance to queue audio events
        """
        self.playout_engine = playout_engine
    
    def set_rotation_manager(self, rotation_manager: RotationManager) -> None:
        """
        Set the rotation manager reference.
        
        Args:
            rotation_manager: RotationManager instance for song selection
        """
        self.rotation_manager = rotation_manager
    
    def set_lifecycle_state(self, is_startup: bool = False, is_draining: bool = False) -> None:
        """
        Set lifecycle state (called by Station).
        
        Per E1.2: THINK may observe lifecycle state.
        
        Args:
            is_startup: True during initial startup THINK
            is_draining: True when Station is in DRAINING state
        """
        self._is_startup = is_startup
        self._is_draining = is_draining
    
    def on_station_start(self) -> None:
        """
        Handle station startup event.
        
        Architecture 3.1 Reference: Section 3.1 (on_station_start)
        """
        logger.info("[DJ] on_station_start: Initializing station")
        # TODO: Load DJ state and rotation state from disk
        # TODO: Choose first song
        # TODO: Create initial DJIntent for first transition
        logger.info("[DJ] Station startup complete")
    
    def on_segment_started(self, segment: AudioEvent) -> None:
        """
        Handle segment started event - Enter Prep Window (THINK phase).
        
        During this window, the DJ:
        - Consumes high-priority ticklers (for future segments)
        - Decides what the next break will look like
        - Selects exact MP3 files for all elements
        - Validates asset availability
        - Commits intent as DJIntent
        
        Architecture 3.1 Reference: Section 3.2 (on_segment_started)
        Architecture 3.1 Reference: Section 4.3 (DJ Prep Window Behavior)
        
        Args:
            segment: The AudioEvent that just started playing
        """
        logger.info(f"[DJ] THINK Phase: Segment started - {segment.type} - {segment.path}")
        
        # Check for shutdown state (per DJ2.5, E1.2)
        if self._is_draining:
            # Shutdown THINK: Select shutdown announcement if available, produce terminal intent
            # CRITICAL: Only create terminal intent if one doesn't already exist
            # Prevent duplicate terminal intent creation (e.g., when shutdown announcement segment starts)
            if self._terminal_intent_queued:
                # Terminal intent already created and queued - do not create another
                logger.debug("[DJ] THINK: Terminal intent already queued, skipping duplicate creation")
                return
            
            # Check if terminal intent already exists (but not yet queued)
            if self.current_intent and self.current_intent.is_terminal:
                logger.debug("[DJ] THINK: Terminal intent already exists, skipping duplicate creation")
                return
            
            logger.info("[DJ] THINK: Shutdown detected, preparing terminal intent...")
            self._handle_shutdown_think()
            return
        
        # Check for startup announcement (per DJ2.4, SL1.3)
        if self._is_startup:
            # Startup THINK: May select startup announcement
            startup_announcement = self._select_startup_announcement()
            if startup_announcement:
                # Create intent with only startup announcement (no next_song yet)
                self.current_intent = DJIntent(
                    next_song=startup_announcement,
                    is_terminal=False
                )
                logger.info(f"[DJ] THINK: Selected startup announcement - {startup_announcement.path}")
                # Reset startup flag after first THINK
                self._is_startup = False
                return
        
        # Radio Industry Best Practice: Only SONGS trigger DJ THINK/DO.
        # IDs, intros, outros, and imaging do NOT trigger breaks.
        # Exception: Startup announcements trigger THINK for first song (per SL1.4)
        # This ensures one break per song and prevents infinite queue growth.
        if segment.type != "song" and segment.type != "announcement":
            logger.debug(f"[DJ] Skipping THINK for non-song segment: {segment.type} - {segment.path}")
            return  # skip THINK/DO
        
        # Special case: Startup announcement triggers THINK for first song (per SL1.4)
        # When startup announcement starts, we need to prepare intent for after first song
        if segment.type == "announcement":
            # This could be startup or shutdown announcement
            # If it's startup announcement, prepare intent for first song
            # If it's shutdown announcement, it's already handled by terminal intent
            if not self._is_draining:
                # Startup announcement - prepare first song intent
                logger.info("[DJ] THINK: Startup announcement started, preparing first song intent")
                self._is_startup = False  # Reset flag
                # Continue to normal THINK logic below to select first song
            else:
                # Shutdown announcement - terminal intent should already exist
                # Do NOT create another terminal intent - prevent duplicate
                if self._terminal_intent_queued or (self.current_intent and self.current_intent.is_terminal):
                    logger.debug("[DJ] THINK: Shutdown announcement started, terminal intent already exists - skipping")
                else:
                    logger.warning("[DJ] THINK: Shutdown announcement started but no terminal intent exists - this should not happen")
                return
        
        # Phase 9: Maybe rescan assets (only once per hour, non-blocking)
        self.asset_manager.maybe_rescan()
        
        # 1. Clear any previous DJIntent that was already executed
        if self.current_intent:
            logger.debug("[DJ] Clearing previous intent (already executed)")
            self.current_intent = None
        
        # 2. Run deferred tasks (Phase 6: Tickler execution)
        self._run_ticklers()
        
        # 3. Decide break structure (Phase 5: Structured Break Composition)
        logger.info("[DJ] THINK: Deciding break structure...")
        now = datetime.now()
        
        # A. Start with high-priority decision: Legal ID
        needs_legal_id = self._needs_legal_id(now)
        
        # B. Next: talk requirement
        # If legal ID is required, talk does not happen this break
        should_talk = False
        if not needs_legal_id:
            should_talk = self._should_talk(now)
        
        # C. Next: generic ID logic
        # If no legal ID and no talk is needed, use generic ID if allowed
        needs_generic_id = False
        if not needs_legal_id and not should_talk:
            needs_generic_id = self._can_play_generic_id(now)
        
        # D. Next: intro logic
        # If next song is upbeat or DJ hasn't used an intro recently
        should_use_intro = self._should_use_intro()
        
        logger.info(f"[DJ] THINK: Break plan - talk={should_talk}, legal_id={needs_legal_id}, "
                   f"generic_id={needs_generic_id}, intro={should_use_intro}")
        
        # 4. Select concrete MP3 files
        logger.info("[DJ] THINK: Selecting concrete MP3 files...")
        
        # Choose next song using rotation logic (weighted variety)
        next_song_path = self._select_next_song(current_song_path=segment.path)
        
        # Extract MP3 metadata during THINK phase (not DO phase)
        # This ensures metadata extraction doesn't block playout
        metadata = _get_mp3_metadata(next_song_path) if next_song_path else None
        next_song = AudioEvent(path=next_song_path, type="song", metadata=metadata)
        logger.info(f"[DJ] THINK: Selected next song - {next_song_path}")
        
        # Select outro if talking
        outro: Optional[AudioEvent] = None
        if should_talk:
            outro_path = self._select_outro(segment.path if segment.type == "song" else None)
            if outro_path and os.path.exists(outro_path):
                outro = AudioEvent(path=outro_path, type="outro")
                logger.info(f"[DJ] THINK: Selected outro - {outro_path}")
            elif outro_path:
                logger.warning(f"[DJ] THINK: Outro file does not exist, skipping - {outro_path}")
        
        # Select station IDs if needed
        station_ids: Optional[list[AudioEvent]] = None
        has_legal_id = False  # Track if we selected a legal ID (for timestamp updates in DO)
        if needs_legal_id:
            id_paths = self._select_station_ids(count=1, legal=True)
            if id_paths:
                # Filter to only existing files
                existing_ids = [path for path in id_paths if os.path.exists(path)]
                if existing_ids:
                    station_ids = [AudioEvent(path=path, type="id") for path in existing_ids]
                    has_legal_id = True  # We selected a legal ID
                    logger.info(f"[DJ] THINK: Selected legal ID - {existing_ids[0]}")
                else:
                    logger.warning(f"[DJ] THINK: No legal ID files exist, skipping - {id_paths}")
        elif needs_generic_id:
            id_paths = self._select_station_ids(count=1, legal=False)
            if id_paths:
                # Filter to only existing files
                existing_ids = [path for path in id_paths if os.path.exists(path)]
                if existing_ids:
                    station_ids = [AudioEvent(path=path, type="id") for path in existing_ids]
                    has_legal_id = False  # We selected a generic ID
                    logger.info(f"[DJ] THINK: Selected generic ID - {existing_ids[0]}")
                else:
                    logger.warning(f"[DJ] THINK: No generic ID files exist, skipping - {id_paths}")
        
        # Select intro if needed
        intro: Optional[AudioEvent] = None
        if should_use_intro:
            intro_path = self._select_intro(next_song_path)
            if intro_path and os.path.exists(intro_path):
                intro = AudioEvent(path=intro_path, type="intro")
                logger.info(f"[DJ] THINK: Selected intro - {intro_path}")
            elif intro_path:
                logger.warning(f"[DJ] THINK: Intro file does not exist, skipping - {intro_path}")
        
        # 5. Validate asset availability - file existence checks done above
        
        # 6. Commit intent (all decisions made, all files validated)
        self.current_intent = DJIntent(
            next_song=next_song,
            outro=outro,
            station_ids=station_ids,
            intro=intro,
            has_legal_id=has_legal_id  # Metadata: whether any ID is legal (decided in THINK)
        )
        
        # Propagate intent_id to all AudioEvents in the intent (for atomic execution tracking)
        intent_id = self.current_intent.intent_id
        if next_song:
            next_song.intent_id = intent_id
        if outro:
            outro.intent_id = intent_id
        if station_ids:
            for sid in station_ids:
                sid.intent_id = intent_id
        if intro:
            intro.intent_id = intent_id
        
        logger.info(f"[DJ] THINK: DJIntent committed - intent_id={intent_id}, "
                   f"outro={outro is not None}, ids={len(station_ids) if station_ids else 0}, "
                   f"intro={intro is not None}, song={next_song.path if next_song else None}")
    
    def on_segment_finished(self, segment: AudioEvent) -> None:
        """
        Handle segment finished event - Enter Transition Window (DO phase).
        
        During this window, the DJ:
        - Retrieves the current DJIntent
        - Pushes assets onto playout queue in order
        - Clears DJIntent
        - Optionally schedules ticklers for future content
        
        No new decisions are made here. No blocking calls.
        
        Architecture 3.1 Reference: Section 3.3 (on_segment_finished)
        Architecture 3.1 Reference: Section 4.4 (DJ Transition Window Behavior)
        
        Args:
            segment: The AudioEvent that just finished playing
        """
        # Handle terminal intents (per INT2.4, E1.3)
        # Terminal intents may be triggered by non-song segments (e.g., shutdown announcement)
        is_terminal = False
        if self.current_intent and self.current_intent.is_terminal:
            is_terminal = True
            logger.info("[DJ] DO Phase: Executing terminal intent (end-of-stream)")
        elif segment.type != "song" and segment.type != "announcement":
            # Radio Industry Best Practice: Only SONGS trigger DJ THINK/DO.
            # IDs, intros, outros, and imaging do NOT trigger breaks.
            # Exception: Announcement segments (startup/shutdown) may trigger DO
            logger.debug(f"[DJ] Skipping DO for non-song segment: {segment.type} - {segment.path}")
            return  # skip THINK/DO
        
        # Special case: Startup announcement DO - verify queue is empty (SS3.1)
        # This check happens before startup state guard to catch violations early
        if segment.type == "announcement" and not is_terminal:
            # Check if this is a startup announcement (no intent_id)
            is_startup_announcement = (segment.intent_id is None)
            if is_startup_announcement:
                logger.info("[DJ] DO: Startup announcement finished, first song will play next")
                # SS3.1: Queue MUST be empty when startup announcement finishes
                if self.playout_engine and hasattr(self.playout_engine, '_queue'):
                    queue = self.playout_engine._queue
                    assert queue.empty(), f"[DJ] DO: SS3.1 violation - Queue must be empty when startup announcement finishes, but found {queue.size()} items"
                    logger.info("[DJ] DO: SS3.1 verified - queue is empty (as required) - ready to enqueue first DJIntent")
            # Don't record startup announcement as song played, don't update rotation
        
        logger.info(f"[DJ] DO Phase: Segment finished - {segment.type} - {segment.path}")
        
        # SD2.3, SD3.2: Guard terminal intent creation - if terminal intent already queued, return immediately
        # Per contract SD2.3: All code paths that could create a terminal DJIntent MUST check the lifecycle latch first
        # Per contract SD3.2: DJ DO MUST NOT execute terminal logic again after that enqueue
        if self._is_draining and self._terminal_intent_queued:
            logger.info("[DJ] DO: Terminal intent already queued - skipping DO phase (SD2.3, SD3.2)")
            return  # Do NOT create THINK, do NOT execute DO
        
        # During DRAINING: The first DO callback after entering DRAINING is the last chance to generate shutdown announcement
        # If no terminal intent exists, create one now and execute terminal DO immediately
        if self._is_draining:
            # Check if terminal intent already exists
            terminal_intent_exists = (self.current_intent and self.current_intent.is_terminal)
            
            if not terminal_intent_exists:
                # No terminal intent exists - create one now and execute terminal DO immediately
                logger.info("[DJ] DO: DRAINING state - no terminal intent exists, creating one now")
                self._handle_shutdown_think()
                # After creating terminal intent, check if it was created
                if self.current_intent and self.current_intent.is_terminal:
                    is_terminal = True
                    logger.info("[DJ] DO: Terminal intent created, executing terminal DO immediately")
                    # Continue to execute terminal DO below (don't return yet)
                else:
                    logger.error("[DJ] DO: Failed to create terminal intent during draining!")
                    return
            elif not is_terminal:
                # Terminal intent exists but current segment is not terminal - this shouldn't happen
                # but guard against it: skip normal intent processing during draining
                logger.warning("[DJ] DO: DRAINING state - normal intent detected during draining, skipping")
                if self.current_intent:
                    logger.warning(f"[DJ] DO: Ignoring normal intent during draining: {self.current_intent}")
                    self.current_intent = None  # Clear the intent to prevent leakage
                return  # Skip normal DO processing during draining
        
        # Record that this segment was played (state update, not a decision)
        # Skip for terminal intents (no state updates needed)
        if not is_terminal:
            self._record_song_played(segment.path)
            # Update rotation manager history as well
            if self.rotation_manager:
                try:
                    self.rotation_manager.record_song_played(segment.path)
                except Exception as e:
                    logger.warning(f"[DJ] Failed to record play in RotationManager: {e}")
        
        # SS4.3: DJ DO MUST NOT run until STARTUP_DO_ENQUEUE state
        # Check startup state if getter is available (Station provides this)
        if hasattr(self, '_station_startup_state_getter'):
            startup_state = self._station_startup_state_getter()
            if startup_state in ["BOOTSTRAP", "STARTUP_ANNOUNCEMENT_PLAYING", "STARTUP_THINK_COMPLETE"]:
                logger.error(f"[DJ] DO: CRITICAL - Attempted to execute DO during startup state {startup_state}")
                logger.error("[DJ] DO: SS4.3 violation - DJ DO MUST NOT run until STARTUP_DO_ENQUEUE state")
                raise RuntimeError(f"DO execution prohibited during startup state: {startup_state}")
            # If in STARTUP_DO_ENQUEUE, this is the first DO - verify queue is empty
            if startup_state == "STARTUP_DO_ENQUEUE":
                if self.playout_engine and hasattr(self.playout_engine, '_queue'):
                    queue = self.playout_engine._queue
                    assert queue.empty(), f"SS6.1.1: Queue MUST be empty before first DJ DO, but found {queue.size()} items"
                    logger.info("[DJ] DO: SS6.1.1 verified - queue is empty before first DO")
        
        # 1. Retrieve current DJIntent (must exist - THINK always creates one)
        if not self.current_intent:
            logger.error("[DJ] DO: No DJIntent found! This should never happen - THINK should always create intent.")
            # This is a critical error - THINK failed. Log and skip this transition.
            return
        
        # 2. Push AudioEvents to playout queue in order:
        # For normal intents: [outro?] → [station_id(s)?] → [intro?] → [next_song]
        # For terminal intents: [shutdown_announcement?] (in intro field, no next_song)
        # Files were validated in THINK phase, so just execute here
        queue_order: list[AudioEvent] = []
        
        # Capture intent_id for queue integrity tracking
        intent_id = self.current_intent.intent_id
        
        if is_terminal:
            # Invariant assertion: Terminal intent may only be queued once per lifecycle
            if self._terminal_intent_queued:
                logger.error("[DJ] DO: CRITICAL - Terminal intent already queued! This should never happen.")
                raise RuntimeError("Terminal intent may only be queued once per lifecycle")
            
            # Terminal intent: Only queue shutdown announcement if present (per INT2.4)
            # Shutdown announcement is stored in intro field for terminal intents
            if self.current_intent.intro:
                # Set intent_id on AudioEvent for queue integrity tracking
                event = self.current_intent.intro
                if event.intent_id is None:
                    event.intent_id = intent_id
                queue_order.append(event)
                logger.info(f"[DJ] DO: Queueing shutdown announcement - {self.current_intent.intro.path}")
            # Terminal intent has no next_song (per DJ2.5)
            self._terminal_intent_queued = True  # Mark as queued
            logger.info("[DJ] DO: Terminal intent executed - no further THINK/DO cycles will occur")
        else:
            # Normal intent: Standard queue order
            if self.current_intent.outro:
                event = self.current_intent.outro
                if event.intent_id is None:
                    event.intent_id = intent_id
                queue_order.append(event)
                logger.info(f"[DJ] DO: Queueing outro - {self.current_intent.outro.path}")
            
            if self.current_intent.station_ids:
                for sid in self.current_intent.station_ids:
                    if sid.intent_id is None:
                        sid.intent_id = intent_id
                queue_order.extend(self.current_intent.station_ids)
                for sid in self.current_intent.station_ids:
                    logger.info(f"[DJ] DO: Queueing station ID - {sid.path}")
            
            if self.current_intent.intro:
                event = self.current_intent.intro
                if event.intent_id is None:
                    event.intent_id = intent_id
                queue_order.append(event)
                logger.info(f"[DJ] DO: Queueing intro - {self.current_intent.intro.path}")
            
            if self.current_intent.next_song:
                event = self.current_intent.next_song
                if event.intent_id is None:
                    event.intent_id = intent_id
                queue_order.append(event)
                logger.info(f"[DJ] DO: Queueing next song - {self.current_intent.next_song.path}")
        
        # Invariant: No non-terminal AudioEvent may be queued after draining begins
        # Per contract SL2.2: During DRAINING, only terminal intents are allowed
        if self._is_draining and not is_terminal:
            logger.error("[DJ] DO: CRITICAL - Attempted to queue non-terminal audio during DRAINING!")
            logger.error(f"[DJ] DO: Queue order would have been: {[e.path for e in queue_order]}")
            raise RuntimeError("No non-terminal AudioEvent may be queued after draining begins")
        
        # Log intent ID and verify queue state before enqueuing (atomic execution enforcement)
        intent_id = self.current_intent.intent_id
        logger.info(f"[DJ] DO: Enqueuing intent - intent_id={intent_id}, segments={len(queue_order)}")
        
        # Debug assertion: Queue must be empty before enqueueing intent when queue was previously empty
        # This ensures no AudioEvent is enqueued before a DJIntent DO phase completes when queue is empty
        # Per requirement: "assert playout_queue.is_empty() immediately before enqueueing the first DJIntent"
        if self.playout_engine and hasattr(self.playout_engine, '_queue'):
            queue = self.playout_engine._queue
            # Check if queue is empty before enqueueing (this happens on first intent and other boundary cases)
            # This covers both cases: after startup announcement, or bootstrap (no announcement)
            is_queue_empty_before_enqueue = (queue.empty() and self.current_intent.next_song is not None)
            if is_queue_empty_before_enqueue:
                assert queue.empty(), f"[DJ] DO: CRITICAL - Playout queue must be empty before enqueueing intent, but found {queue.size()} items"
                logger.info("[DJ] DO: Queue empty at DO boundary — safe to enqueue intent")
        
        # Assert that no older intent IDs remain at the queue head (per INT2.3, E0.6)
        if self.playout_engine and hasattr(self.playout_engine, '_queue'):
            queue = self.playout_engine._queue
            if not queue.empty():
                # Check intent_id at queue head
                head_intent_id = queue.peek_intent_id()
                if head_intent_id is not None:
                    # Verify queue head is from the current intent being executed
                    # (It's acceptable to have segments from current intent, but not from older intents)
                    if head_intent_id != intent_id:
                        # Get all intent_ids for detailed error message
                        queue_intent_ids = queue.get_all_intent_ids() if hasattr(queue, 'get_all_intent_ids') else [head_intent_id]
                        logger.error(f"[DJ] DO: CRITICAL - Queue head contains older intent_id={head_intent_id}, "
                                   f"current intent_id={intent_id}")
                        logger.error(f"[DJ] DO: All queue intent_ids: {queue_intent_ids}")
                        logger.error(f"[DJ] DO: This violates atomic intent execution (INT2.3, E0.6)")
                        raise RuntimeError(f"Queue head contains older intent_id {head_intent_id}, "
                                         f"cannot enqueue new intent {intent_id} - cross-intent leakage detected")
                    else:
                        logger.debug(f"[DJ] DO: Queue head matches current intent_id={intent_id} (acceptable)")
        
        # Push to playout queue
        if self.playout_engine:
            # SS3.4: All AudioEvents enqueued in STARTUP_DO_ENQUEUE MUST share the same intent_id
            if hasattr(self, '_station_startup_state_getter'):
                startup_state = self._station_startup_state_getter()
                if startup_state == "STARTUP_DO_ENQUEUE":
                    # Verify all AudioEvents share the same intent_id
                    intent_ids = [e.intent_id for e in queue_order if e.intent_id is not None]
                    if len(intent_ids) > 0:
                        first_intent_id = intent_ids[0]
                        assert all(iid == first_intent_id for iid in intent_ids), \
                            "SS6.1.3: All AudioEvents enqueued during STARTUP_DO_ENQUEUE MUST share the same intent_id"
                        logger.info(f"[DJ] DO: SS6.1.3 verified - all {len(queue_order)} AudioEvents share intent_id={first_intent_id}")
            
            self.playout_engine.queue_audio(queue_order)
            logger.info(f"[DJ] DO: Pushed {len(queue_order)} audio event(s) to playout queue with intent_id={intent_id}")
            
            # SS1.5: After first DO completes, transition to NORMAL_OPERATION
            if hasattr(self, '_station_startup_state_getter') and hasattr(self, '_notify_startup_state_transition'):
                startup_state = self._station_startup_state_getter()
                if startup_state == "STARTUP_DO_ENQUEUE" and not is_terminal:
                    # First DO completed - notify Station to transition to NORMAL_OPERATION
                    self._notify_startup_state_transition("NORMAL_OPERATION")
                    logger.info("[DJ] DO: SS1.5 - First DO completed, transitioning to NORMAL_OPERATION")
            
            # Invariant: Terminal intent may only be queued once
            if is_terminal:
                logger.info("[DJ] DO: Terminal intent queued - invariant: terminal intent queued exactly once")
        else:
            logger.error("[DJ] DO: No playout engine reference! Cannot queue audio.")
        
        # For terminal intents: Only queue shutdown announcement, then return immediately
        # Do NOT update timestamps, histories, schedule ticklers, or queue next_song
        if is_terminal:
            # Clear intent and return immediately (per INT2.4, E1.3)
            self.current_intent = None
            logger.info("[DJ] DO: Terminal intent cleared, no further scheduling")
            return
        
        # 3. Update timestamps and histories (Phase 5)
        # Use metadata from intent (decided in THINK) - no decisions here
        now = datetime.now()
        
        # Update ID timestamps based on metadata from THINK
        if self.current_intent.station_ids:
            if self.current_intent.has_legal_id:
                self.last_legal_id_time = now
                logger.debug(f"[DJ] DO: Updated last_legal_id_time to {now}")
            else:
                # Generic ID
                self.last_generic_id_time = now
                logger.debug(f"[DJ] DO: Updated last_generic_id_time to {now}")
        
        # Update talk timestamp if outro was queued
        if self.current_intent.outro:
            self.last_talk_time = now
            logger.debug(f"[DJ] DO: Updated last_talk_time to {now}")
        
        # Update intro/outro histories
        if self.current_intent.intro:
            self.intro_history.append(self.current_intent.intro.path)
            # Keep only last cooldown_len entries
            if len(self.intro_history) > self.cooldown_len:
                self.intro_history.pop(0)
            logger.debug(f"[DJ] DO: Added intro to history: {self.current_intent.intro.path}")
        
        if self.current_intent.outro:
            self.outro_history.append(self.current_intent.outro.path)
            # Keep only last cooldown_len entries
            if len(self.outro_history) > self.cooldown_len:
                self.outro_history.pop(0)
            logger.debug(f"[DJ] DO: Added outro to history: {self.current_intent.outro.path}")
        
        # 4. Schedule ticklers for future content (Phase 6)
        # Do this before clearing intent so we can check what was used
        self._schedule_ticklers_for_intent(self.current_intent)
        
        # 5. Clear DJIntent (ready for next Prep Window)
        self.current_intent = None
        logger.info("[DJ] DO: DJIntent cleared")
    
    def on_station_stop(self) -> None:
        """
        Handle station shutdown event.
        
        Architecture 3.1 Reference: Section 3.4 (on_station_stop)
        """
        logger.info("[DJ] on_station_stop: Shutting down")
        # TODO: Save DJ state (rotation, cooldowns, last played list)
        # TODO: Save tickler backlog
        # TODO: Save long-term cooldown/usage tracking
        # DJIntent does not need to persist (transient)
        logger.info("[DJ] Station shutdown complete")
    
    def get_current_intent(self) -> Optional[DJIntent]:
        """
        Get the current DJIntent (for debugging/testing).
        
        Returns:
            Current DJIntent or None if not yet prepared
        """
        return self.current_intent
    
    # ===== Phase 5 Logic Methods =====
    
    def _needs_legal_id(self, now: datetime) -> bool:
        """
        Phase 5: Check if a legal ID is required.
        
        Legal ID is required every hour (with grace period).
        
        Args:
            now: Current datetime
            
        Returns:
            True if legal ID is required
        """
        if self.last_legal_id_time is None:
            return True
        
        time_since_last = (now - self.last_legal_id_time).total_seconds()
        return time_since_last >= self.legal_id_interval
    
    def _can_play_generic_id(self, now: datetime) -> bool:
        """
        Phase 5: Check if a generic station ID can be played.
        
        Generic IDs must be at least 3 minutes apart.
        
        Args:
            now: Current datetime
            
        Returns:
            True if generic ID can be played
        """
        if self.last_generic_id_time is None:
            return True
        
        time_since_last = (now - self.last_generic_id_time).total_seconds()
        return time_since_last >= self.generic_id_min
    
    def _should_talk(self, now: datetime) -> bool:
        """
        Phase 5: Decide if DJ should talk after current segment.
        
        Rules:
        - Must talk if it's been 30+ minutes since last talk (overdue)
        - Cannot talk if it's been less than 5 minutes since last talk (too soon)
        - Default: don't over-talk
        
        Args:
            now: Current datetime
            
        Returns:
            True if DJ should talk
        """
        if self.last_talk_time is None:
            # Never talked before, allow talk
            return True
        
        time_since_last = (now - self.last_talk_time).total_seconds()
        
        # Must talk if overdue (30+ minutes)
        if time_since_last >= self.max_talk_silence:
            logger.debug(f"[DJ] Should talk: overdue ({time_since_last/60:.1f} min since last)")
            return True
        
        # Cannot talk if too soon (less than 5 minutes)
        if time_since_last < self.min_talk_spacing:
            logger.debug(f"[DJ] Should not talk: too soon ({time_since_last:.0f}s since last)")
            return False
        
        # Default: don't over-talk
        return False
    
    def _cooldown_ok(self, file: str, history: list[str]) -> bool:
        """
        Phase 5: Check if a file is not in recent cooldown history.
        
        Args:
            file: File path to check
            history: List of recently used file paths
            
        Returns:
            True if file is not in the last cooldown_len uses
        """
        return file not in history[-self.cooldown_len:]
    
    def _should_use_intro(self) -> bool:
        """
        Phase 5: Decide if an intro should be used for next song.
        
        Logic: Use intro if DJ hasn't used one recently (simple heuristic).
        More sophisticated logic could consider song energy, genre, etc.
        
        Returns:
            True if intro should be used
        """
        # Simple logic: use intro sometimes (50% chance)
        # Could be enhanced with more sophisticated rules
        return random.random() < 0.5
    
    def _select_next_song(self, current_song_path: Optional[str] = None) -> str:
        """
        Select next song using RotationManager.
        
        Architecture 3.1 Reference: Section 4.3 (Step 3)
        
        Args:
            current_song_path: Path to currently playing song (to avoid immediate repeat)
        
        Returns:
            Path to next song MP3 file
        """
        if not self.rotation_manager:
            raise RuntimeError("RotationManager not available - cannot select next song")
        
        # Get all available tracks from rotation manager
        # Filter out current song to avoid immediate repeat
        all_tracks = self.rotation_manager._regular_tracks + self.rotation_manager._holiday_tracks
        candidates = [s for s in all_tracks if s != current_song_path]
        
        if not candidates:
            # If filtering out current song leaves nothing, use all tracks anyway
            candidates = all_tracks
        
        try:
            selected = self.rotation_manager.select_next_song(candidates)
            logger.debug(f"[DJ] Selected via RotationManager: {selected}")
            return selected
        except Exception as e:
            logger.error(f"[DJ] RotationManager selection failed: {e}")
            # Last resort: random selection from candidates
            if candidates:
                selected = random.choice(candidates)
                logger.warning(f"[DJ] Using random fallback: {selected}")
                return selected
            raise RuntimeError("No songs available for selection")
    
    def _generic_id_pool_low(self) -> bool:
        """
        Phase 6: Check if generic ID pool is running low.
        
        Returns:
            True if pool is below threshold
        """
        threshold = 3  # Example threshold
        return len(self.available_generic_ids) < threshold
    
    def _scan_generic_ids(self) -> None:
        """
        Scan for available generic ID files.
        
        Updates self.available_generic_ids with paths to available IDs.
        """
        generic_ids_dir = self.dj_asset_path / "ids" / "generic"
        if not generic_ids_dir.exists():
            self.available_generic_ids = []
            return
        
        try:
            self.available_generic_ids = [
                str(f) for f in generic_ids_dir.glob("*.mp3")
            ]
        except Exception as e:
            logger.warning(f"[DJ] Error scanning generic IDs: {e}")
            self.available_generic_ids = []
    
    def _select_outro(self, song_path: Optional[str] = None) -> Optional[str]:
        """
        Phase 9: Select an outro MP3 file using asset discovery, respecting cooldowns.
        
        Selection priority:
        1. Per-song outros (if song_path provided)
        2. Generic outros (fallback)
        3. None (if neither exist)
        
        Args:
            song_path: Optional path to current song (for per-song outro)
        
        Returns:
            Path to outro MP3 file, or None if no outro available
        """
        # Phase 9: Try per-song outros first
        if song_path:
            candidate_outtros = self.asset_manager.get_outtros_for_song(song_path)
            if candidate_outtros:
                # Filter by cooldown
                available_outtros = [
                    outro for outro in candidate_outtros
                    if self._cooldown_ok(outro, self.outro_history)
                ]
                
                # If none available due to cooldown, use any (fallback)
                if not available_outtros:
                    logger.debug("[DJ] All per-song outros in cooldown, using any")
                    available_outtros = candidate_outtros
                
                # Select randomly
                selected = random.choice(available_outtros)
                logger.info(f"[DJ] THINK: Selected per-song outro: {selected}")
                return selected
        
        # Phase 9: Fallback to generic outros if no per-song outros
        candidate_outtros = self.asset_manager.get_generic_outros()
        if candidate_outtros:
            # Filter by cooldown (same logic as intros)
            available_outtros = [
                outro for outro in candidate_outtros
                if self._cooldown_ok(outro, self.outro_history)
            ]
            
            # If none available due to cooldown, use any (fallback)
            if not available_outtros:
                logger.debug("[DJ] All generic outros in cooldown, using any")
                available_outtros = candidate_outtros
            
            # Select randomly
            selected = random.choice(available_outtros)
            logger.info(f"[DJ] THINK: Selected generic outro (fallback): {selected}")
            return selected
        
        # No outros available (neither per-song nor generic)
        logger.debug("[DJ] No outro found (neither per-song nor generic)")
        return None
    
    def _select_station_ids(self, count: int = 1, legal: bool = False) -> list[str]:
        """
        Phase 5: Select station ID MP3 files.
        
        Args:
            count: Number of IDs to select
            legal: True if legal ID is required
        
        Returns:
            List of paths to station ID MP3 files
        """
        id_paths = []
        
        if legal:
            ids_dir = self.dj_asset_path / "ids" / "legal"
        else:
            ids_dir = self.dj_asset_path / "ids" / "generic"
        
        if not ids_dir.exists():
            # Fallback paths
            if legal:
                base_path = str(self.dj_asset_path / "ids" / "legal" / "legal_id.mp3")
            else:
                base_path = str(self.dj_asset_path / "ids" / "generic" / "generic_id_001.mp3")
            
            for i in range(count):
                id_paths.append(base_path)
            logger.debug(f"[DJ] Selected ID (fallback): {base_path}")
            return id_paths
        
        # Get all ID files
        try:
            all_ids = [f.name for f in ids_dir.glob("*.mp3")]
            if not all_ids:
                logger.warning(f"[DJ] No {'legal' if legal else 'generic'} ID files found")
                return []
            
            # Select randomly (IDs don't have cooldowns in Phase 5, only timing rules)
            for i in range(count):
                selected = random.choice(all_ids)
                id_paths.append(str(ids_dir / selected))
            
            logger.debug(f"[DJ] Selected {len(id_paths)} {'legal' if legal else 'generic'} ID(s)")
            return id_paths
            
        except Exception as e:
            logger.warning(f"[DJ] Error selecting IDs: {e}")
            return []
    
    def _select_intro(self, song_path: str) -> Optional[str]:
        """
        Phase 9: Select an intro MP3 file using asset discovery, respecting cooldowns.
        
        Selection priority:
        1. Per-song intros (if available for this song)
        2. Generic intros (fallback)
        
        Args:
            song_path: Path to next song (for per-song intro)
        
        Returns:
            Path to intro MP3 file, or None if no intro available
        """
        # Phase 9: Try per-song intros first
        candidate_intros = self.asset_manager.get_intros_for_song(song_path)
        
        # Phase 9: Fallback to generic intros if no per-song intros
        if not candidate_intros:
            candidate_intros = self.asset_manager.generic_intros
            logger.debug(f"[DJ] No per-song intro found, using generic intros ({len(candidate_intros)} available)")
        
        if not candidate_intros:
            logger.warning("[DJ] No intro files found (neither per-song nor generic)")
            return None
        
        # Filter by cooldown
        available_intros = [
            intro for intro in candidate_intros
            if self._cooldown_ok(intro, self.intro_history)
        ]
        
        # If none available due to cooldown, use any (fallback)
        if not available_intros:
            logger.debug("[DJ] All intros in cooldown, using any")
            available_intros = candidate_intros
        
        # Select randomly
        selected = random.choice(available_intros)
        logger.debug(f"[DJ] Selected intro: {selected}")
        return selected
    
    def _record_song_played(self, song_path: str) -> None:
        """
        Record that a song was played.
        
        Args:
            song_path: Path to song that was played
        """
        # Add to history
        self.last_played_songs.append(song_path)
        
        # Keep only last N songs
        if len(self.last_played_songs) > self.max_history:
            self.last_played_songs.pop(0)
        
        logger.debug(f"[DJ] Recorded song played: {song_path} (history: {len(self.last_played_songs)} songs)")
    
    def _record_talk(self) -> None:
        """
        Record that a talk segment occurred.
        
        Note: This is now called from DO phase when outro is actually queued.
        """
        # This method is kept for backward compatibility but is no longer
        # the primary way to record talk (DO phase handles it)
        pass
    
    # ===== Phase 6: Tickler System =====
    
    def add_tickler(self, tickler: Tickler) -> None:
        """
        Add a tickler to the queue.
        
        Ticklers are executed during the next THINK window.
        
        Args:
            tickler: Tickler instance to add
        """
        self.ticklers.append(tickler)
        logger.info(f"[DJ DO] Scheduling tickler: {tickler}")
    
    def _run_ticklers(self) -> None:
        """
        Run all ticklers in the queue during THINK phase.
        
        Ticklers are executed before break planning to prepare
        assets for future use.
        """
        if not self.ticklers:
            return
        
        logger.info(f"[DJ THINK] Running {len(self.ticklers)} tickler(s)")
        
        while self.ticklers:
            tickler = self.ticklers.pop(0)
            logger.info(f"[Tickler] Executing {tickler}")
            try:
                tickler.run(self)
            except Exception as e:
                logger.error(f"[Tickler] Error executing {tickler}: {e}")
    
    def _schedule_ticklers_for_intent(self, intent: DJIntent) -> None:
        """
        Schedule ticklers during DO phase for future content preparation.
        
        This is where the DJ decides what needs to be prepared next.
        Examples:
        - If we used an intro, schedule a replacement for later
        - If generic ID pool is low, schedule a refill
        - If we're about to play a song, schedule intro/outro generation
        
        Args:
            intent: The DJIntent that was just executed
        """
        # Example: If we used an intro, schedule a replacement for later
        if intent.intro:
            # Schedule intro generation for the next song that will need it
            # For now, schedule for the next song that was just queued
            if intent.next_song:
                self.add_tickler(GenerateIntroTickler(intent.next_song.path))
        
        # If we used an outro, we might want to schedule outro generation
        if intent.outro and intent.next_song:
            # Schedule outro generation for future use
            self.add_tickler(GenerateOutroTickler(intent.next_song.path))
        
        # If generic ID pool is low, schedule a refill
        if self._generic_id_pool_low():
            self.add_tickler(RefillGenericIDTickler())
    
    # ===== Phase 7: State Persistence Support =====
    
    def _now(self) -> int:
        """
        Get current Unix timestamp.
        
        Returns:
            Current time as Unix timestamp (seconds since epoch)
        """
        return int(time.time())
    
    def to_dict(self) -> dict:
        """
        Phase 7: Convert DJ state to dictionary for persistence.
        
        Returns:
            Dictionary containing all persistable state
        """
        # Convert datetime objects to Unix timestamps for JSON serialization
        data = {
            "last_legal_id_time": self._datetime_to_timestamp(self.last_legal_id_time),
            "last_generic_id_time": self._datetime_to_timestamp(self.last_generic_id_time),
            "last_talk_time": self._datetime_to_timestamp(self.last_talk_time),
            "intro_history": self.intro_history[-20:],  # Keep it reasonable
            "outro_history": self.outro_history[-20:],
            "last_played_songs": self.last_played_songs,
            "ticklers": [repr(t) for t in self.ticklers],  # Store as strings for now
        }
        
        # Add rotation state if rotation_manager is available
        if self.rotation_manager:
            # Get last played songs from rotation manager
            rotation_last_played = self.rotation_manager.get_last_played_songs(count=20)
            data["rotation"] = {
                "last_played": rotation_last_played,
                "play_counts": self.rotation_manager.play_counts.copy(),
                "holiday_play_counts": self.rotation_manager.holiday_play_counts.copy(),
                "history": [
                    {
                        "path": path,
                        "timestamp": ts,
                        "is_holiday": is_holiday
                    }
                    for path, ts, is_holiday in self.rotation_manager.history[-20:]
                ],
            }
        else:
            data["rotation"] = {}
        
        return data
    
    def _select_startup_announcement(self) -> Optional[AudioEvent]:
        """
        Select startup announcement from cached pool (per DJ2.4).
        
        Returns:
            AudioEvent for startup announcement, or None if pool is empty
        """
        if not hasattr(self.asset_manager, 'startup_announcements'):
            return None
        
        pool = self.asset_manager.startup_announcements
        if not pool:
            return None
        
        # Random selection from pool (per DJ2.4)
        selected_path = random.choice(pool)
        if selected_path and os.path.exists(selected_path):
            metadata = _get_mp3_metadata(selected_path)
            return AudioEvent(path=selected_path, type="announcement", metadata=metadata)
        
        return None
    
    def _handle_shutdown_think(self) -> None:
        """
        Handle shutdown THINK phase (per DJ2.5).
        
        Selects shutdown announcement if available and produces terminal intent.
        """
        # Clear any previous intent
        self.current_intent = None
        
        # Select shutdown announcement from cached pool (per DJ2.5)
        shutdown_announcement: Optional[AudioEvent] = None
        if hasattr(self.asset_manager, 'shutdown_announcements'):
            pool = self.asset_manager.shutdown_announcements
            if pool:
                # Random selection from pool (per DJ2.5)
                selected_path = random.choice(pool)
                if selected_path and os.path.exists(selected_path):
                    metadata = _get_mp3_metadata(selected_path)
                    shutdown_announcement = AudioEvent(path=selected_path, type="announcement", metadata=metadata, is_terminal=True)
                    logger.info(f"[DJ] THINK: Selected shutdown announcement - {selected_path}")
                    logger.info(f"[LIFECYCLE] Shutdown announcement selected: {selected_path}")
            else:
                logger.info("[LIFECYCLE] Shutdown announcement skipped (pool empty)")
        else:
            logger.info("[LIFECYCLE] Shutdown announcement skipped (pool not available)")
        
        # Create terminal intent (per DJ2.5, INT2.4)
        # Terminal intent may contain shutdown announcement or be empty
        # Terminal intent MUST NOT include next_song
        if shutdown_announcement:
            # Terminal intent with shutdown announcement
            self.current_intent = DJIntent(
                next_song=None,  # No next_song in terminal intent
                outro=None,
                station_ids=None,
                intro=shutdown_announcement,  # Use intro field for shutdown announcement
                has_legal_id=False,
                is_terminal=True
            )
            # Propagate intent_id to shutdown announcement AudioEvent
            intent_id = self.current_intent.intent_id
            shutdown_announcement.intent_id = intent_id
            logger.info(f"[DJ] THINK: Terminal intent created - intent_id={intent_id}")
        else:
            # Terminal intent with no AudioEvents (per SL2.2.6)
            self.current_intent = DJIntent(
                next_song=None,
                outro=None,
                station_ids=None,
                intro=None,
                has_legal_id=False,
                is_terminal=True
            )
            intent_id = self.current_intent.intent_id
            logger.info(f"[DJ] THINK: Terminal intent created (no announcement) - intent_id={intent_id}")
        
        logger.info(f"[DJ] THINK: Terminal intent created (announcement={shutdown_announcement is not None})")
    
    def _assert_queue_integrity(self, expanded_segments: list[AudioEvent], intent_id) -> None:
        """
        Assert that queue tail matches expanded segments from current intent.
        
        This defensive assertion prevents silent queue corruption by verifying that
        the segments we just enqueued are actually at the tail of the queue.
        
        Assertion Rule:
        After DO finishes enqueueing:
        queue_tail == expanded_segments_of_current_intent
        
        Constraints:
        - Must NOT run in production mode unless STRICT_QUEUE_ASSERTS=1
        - Must be O(n) max
        - Compares file paths AND intent IDs
        
        Args:
            expanded_segments: List of AudioEvents that were expanded from DJIntent
            intent_id: UUID of the DJIntent that was expanded
        """
        # Check if assertion should run
        strict_asserts = os.getenv("STRICT_QUEUE_ASSERTS", "0") == "1"
        if not strict_asserts:
            # Skip assertion in production mode unless explicitly enabled
            return
        
        if not self.playout_engine or not self.playout_engine._queue:
            # Can't assert if queue is not available
            return
        
        if len(expanded_segments) == 0:
            # Nothing to assert if no segments were enqueued
            return
        
        # Get queue tail (last N items where N = len(expanded_segments))
        queue_tail = self.playout_engine._queue.get_tail(len(expanded_segments))
        
        # Compare lengths
        if len(queue_tail) != len(expanded_segments):
            error_msg = (
                f"[QUEUE_INTEGRITY] Queue tail length mismatch! "
                f"Expected {len(expanded_segments)} segments, found {len(queue_tail)} in queue tail. "
                f"Intent ID: {intent_id}"
            )
            logger.error(error_msg)
            logger.error(f"[QUEUE_INTEGRITY] Expanded segments: {[(e.type, e.path, e.intent_id) for e in expanded_segments]}")
            logger.error(f"[QUEUE_INTEGRITY] Queue tail: {[(e.type, e.path, e.intent_id) for e in queue_tail]}")
            logger.error(f"[QUEUE_INTEGRITY] Full queue dump: {self.playout_engine._queue.dump()}")
            
            # Raise RuntimeError in debug mode (when STRICT_QUEUE_ASSERTS=1)
            raise RuntimeError(f"Queue integrity violation: tail length mismatch. {error_msg}")
        
        # Compare each segment: file paths AND intent IDs
        mismatches = []
        for i, (expected, actual) in enumerate(zip(expanded_segments, queue_tail)):
            path_match = expected.path == actual.path
            intent_match = expected.intent_id == actual.intent_id
            
            if not path_match or not intent_match:
                mismatches.append({
                    "index": i,
                    "expected": {"type": expected.type, "path": expected.path, "intent_id": expected.intent_id},
                    "actual": {"type": actual.type, "path": actual.path, "intent_id": actual.intent_id},
                    "path_match": path_match,
                    "intent_match": intent_match
                })
        
        if mismatches:
            error_msg = (
                f"[QUEUE_INTEGRITY] Queue tail content mismatch! "
                f"Found {len(mismatches)} mismatched segment(s). Intent ID: {intent_id}"
            )
            logger.error(error_msg)
            
            for mismatch in mismatches:
                logger.error(
                    f"[QUEUE_INTEGRITY] Mismatch at index {mismatch['index']}: "
                    f"Expected {mismatch['expected']}, found {mismatch['actual']}. "
                    f"Path match: {mismatch['path_match']}, Intent match: {mismatch['intent_match']}"
                )
            
            logger.error(f"[QUEUE_INTEGRITY] Expanded segments: {[(e.type, e.path, e.intent_id) for e in expanded_segments]}")
            logger.error(f"[QUEUE_INTEGRITY] Queue tail: {[(e.type, e.path, e.intent_id) for e in queue_tail]}")
            logger.error(f"[QUEUE_INTEGRITY] Full queue dump: {self.playout_engine._queue.dump()}")
            
            # Raise RuntimeError in debug mode (when STRICT_QUEUE_ASSERTS=1)
            raise RuntimeError(f"Queue integrity violation: tail content mismatch. {error_msg}")
        
        # Assertion passed
        logger.debug(
            f"[QUEUE_INTEGRITY] Assertion passed: queue tail matches expanded segments "
            f"({len(expanded_segments)} segments, intent_id={intent_id})"
        )
    
    def from_dict(self, data: dict) -> None:
        """
        Phase 7: Load DJ state from dictionary (from JSON).
        
        Args:
            data: Dictionary containing persisted state
        """
        # Restore timing fields (convert from Unix timestamps to datetime)
        self.last_legal_id_time = self._timestamp_to_datetime(data.get("last_legal_id_time"))
        self.last_generic_id_time = self._timestamp_to_datetime(data.get("last_generic_id_time"))
        self.last_talk_time = self._timestamp_to_datetime(data.get("last_talk_time"))
        
        # Restore histories
        self.intro_history = data.get("intro_history", [])
        self.outro_history = data.get("outro_history", [])
        
        # Restore last played songs
        self.last_played_songs = data.get("last_played_songs", [])
        
        # Ticklers will be reconstructed in Phase 8 when we add dynamic types.
        # For now, ignore or stub.
        self.ticklers = []
        
        # Restore rotation state if rotation_manager is available
        if self.rotation_manager and "rotation" in data:
            rot = data["rotation"]
            
            # Restore play counts
            if "play_counts" in rot:
                self.rotation_manager.play_counts = rot["play_counts"]
            if "holiday_play_counts" in rot:
                self.rotation_manager.holiday_play_counts = rot["holiday_play_counts"]
            
            # Restore history
            if "history" in rot:
                self.rotation_manager.history = [
                    (item["path"], item["timestamp"], item["is_holiday"])
                    for item in rot["history"]
                ]
            elif "last_played" in rot:
                # Fallback: reconstruct history from last_played list
                # This is less accurate but better than nothing
                current_time = time.time()
                self.rotation_manager.history = [
                    (path, current_time - (i * 180), False)  # Assume 3 min per song
                    for i, path in enumerate(reversed(rot["last_played"]))
                ]
    
    def _datetime_to_timestamp(self, dt: Optional[datetime]) -> Optional[float]:
        """
        Convert datetime to Unix timestamp.
        
        Args:
            dt: Datetime object or None
            
        Returns:
            Unix timestamp (float) or None
        """
        if dt is None:
            return None
        return dt.timestamp()
    
    def _timestamp_to_datetime(self, ts: Optional[float]) -> Optional[datetime]:
        """
        Convert Unix timestamp to datetime.
        
        Args:
            ts: Unix timestamp (float) or None
            
        Returns:
            Datetime object or None
        """
        if ts is None:
            return None
        return datetime.fromtimestamp(ts)
