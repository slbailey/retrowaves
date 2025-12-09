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
        # Radio Industry Best Practice: Only SONGS trigger DJ THINK/DO.
        # IDs, intros, outros, and imaging do NOT trigger breaks.
        # This ensures one break per song and prevents infinite queue growth.
        if segment.type != "song":
            logger.debug(f"[DJ] Skipping THINK for non-song segment: {segment.type} - {segment.path}")
            return  # skip THINK/DO
        
        logger.info(f"[DJ] THINK Phase: Segment started - {segment.type} - {segment.path}")
        
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
        
        logger.info(f"[DJ] THINK: DJIntent committed - "
                   f"outro={outro is not None}, ids={len(station_ids) if station_ids else 0}, "
                   f"intro={intro is not None}, song={next_song.path}")
    
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
        # Radio Industry Best Practice: Only SONGS trigger DJ THINK/DO.
        # IDs, intros, outros, and imaging do NOT trigger breaks.
        # This ensures one break per song and prevents infinite queue growth.
        if segment.type != "song":
            logger.debug(f"[DJ] Skipping DO for non-song segment: {segment.type} - {segment.path}")
            return  # skip THINK/DO
        
        logger.info(f"[DJ] DO Phase: Segment finished - {segment.type} - {segment.path}")
        
        # Record that this segment was played (state update, not a decision)
        self._record_song_played(segment.path)
        # Update rotation manager history as well
        if self.rotation_manager:
            try:
                self.rotation_manager.record_song_played(segment.path)
            except Exception as e:
                logger.warning(f"[DJ] Failed to record play in RotationManager: {e}")
        
        # 1. Retrieve current DJIntent (must exist - THINK always creates one)
        if not self.current_intent:
            logger.error("[DJ] DO: No DJIntent found! This should never happen - THINK should always create intent.")
            # This is a critical error - THINK failed. Log and skip this transition.
            return
        
        # 2. Push AudioEvents to playout queue in order:
        # [outro?] → [station_id(s)?] → [intro?] → [next_song]
        # Files were validated in THINK phase, so just execute here
        queue_order: list[AudioEvent] = []
        
        if self.current_intent.outro:
            queue_order.append(self.current_intent.outro)
            logger.info(f"[DJ] DO: Queueing outro - {self.current_intent.outro.path}")
        
        if self.current_intent.station_ids:
            queue_order.extend(self.current_intent.station_ids)
            for sid in self.current_intent.station_ids:
                logger.info(f"[DJ] DO: Queueing station ID - {sid.path}")
        
        if self.current_intent.intro:
            queue_order.append(self.current_intent.intro)
            logger.info(f"[DJ] DO: Queueing intro - {self.current_intent.intro.path}")
        
        queue_order.append(self.current_intent.next_song)
        logger.info(f"[DJ] DO: Queueing next song - {self.current_intent.next_song.path}")
        
        # Push to playout queue
        if self.playout_engine:
            self.playout_engine.queue_audio(queue_order)
            logger.info(f"[DJ] DO: Pushed {len(queue_order)} audio event(s) to playout queue")
        else:
            logger.error("[DJ] DO: No playout engine reference! Cannot queue audio.")
        
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
