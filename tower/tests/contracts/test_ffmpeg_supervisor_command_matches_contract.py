"""
Contract visibility test: FFmpeg command invocation.

This test asserts that the actual FFmpeg command built by FFmpegSupervisor
matches contract requirements. This is a visibility test to identify any
gaps between contract expectations and actual implementation.

See docs/contracts/FFMPEG_SUPERVISOR_CONTRACT.md for contract specification.
"""

import pytest
import os
from tower.audio.ring_buffer import FrameRingBuffer
from tower.encoder.ffmpeg_supervisor import FFmpegSupervisor, DEFAULT_FFMPEG_CMD


@pytest.fixture
def mp3_buffer():
    """Create MP3 buffer for supervisor."""
    return FrameRingBuffer(capacity=10)


@pytest.fixture
def supervisor(mp3_buffer):
    """Create FFmpegSupervisor instance for testing."""
    sup = FFmpegSupervisor(
        mp3_buffer=mp3_buffer,
        allow_ffmpeg=True,  # Allow FFmpeg for integration tests per [I25]
    )
    return sup


class TestFFmpegCommandMatchesContract:
    """Tests that FFmpeg command matches contract requirements."""
    
    def test_ffmpeg_invocation_matches_contract(self, supervisor):
        """
        Test FFmpeg command matches contract requirements.
        
        This visibility test captures the actual FFmpeg command that would be
        invoked in production and asserts it matches contract expectations.
        
        Contract expectations (based on [S19] and DEFAULT_FFMPEG_CMD):
        - Input format: s16le (signed 16-bit little-endian PCM)
        - Sample rate: 48000 Hz
        - Channels: 2 (stereo)
        - Input source: pipe:0 (stdin)
        - Output format: mp3
        - Output destination: pipe:1 (stdout)
        - Frame size: 1152 samples per [S19.11]
        """
        # Build the actual command that would be used
        cmd = supervisor._build_ffmpeg_cmd()
        
        # Convert to string for easier inspection
        cmd_str = " ".join(cmd)
        
        # Contract assertion: PCM input format MUST be raw s16le
        # Per contract [S19] and DEFAULT_FFMPEG_CMD: -f s16le
        assert "-f" in cmd, \
            f"[FFMPEG_CMD] Command must specify input format with -f flag. Command: {cmd_str}"
        
        # Find the format value after -f
        fmt_idx = cmd.index("-f")
        assert fmt_idx + 1 < len(cmd), \
            f"[FFMPEG_CMD] -f flag must have a value. Command: {cmd_str}"
        
        # Check for s16le format (may appear multiple times, check input format)
        # Input format should be before -i pipe:0
        input_fmt_idx = None
        if "-i" in cmd:
            input_idx = cmd.index("-i")
            # Look for -f before -i (this is the input format)
            for i in range(input_idx):
                if cmd[i] == "-f" and i + 1 < input_idx:
                    input_fmt_idx = i + 1
                    break
        
        if input_fmt_idx is not None:
            input_format = cmd[input_fmt_idx]
            assert input_format == "s16le", \
                f"[FFMPEG_CMD] Input format MUST be s16le per contract. Found: {input_format}. Command: {cmd_str}"
        else:
            # Fallback: check if s16le appears anywhere in command
            assert "s16le" in cmd, \
                f"[FFMPEG_CMD] Input format MUST be s16le per contract. Command: {cmd_str}"
        
        # Contract assertion: Sample rate MUST be 48000Hz
        # Per contract [S19] and DEFAULT_FFMPEG_CMD: -ar 48000
        assert "-ar" in cmd, \
            f"[FFMPEG_CMD] Command must specify sample rate with -ar flag. Command: {cmd_str}"
        
        ar_idx = cmd.index("-ar")
        assert ar_idx + 1 < len(cmd), \
            f"[FFMPEG_CMD] -ar flag must have a value. Command: {cmd_str}"
        
        sample_rate = cmd[ar_idx + 1]
        assert sample_rate == "48000", \
            f"[FFMPEG_CMD] Sample rate MUST be 48000Hz per contract. Found: {sample_rate}. Command: {cmd_str}"
        
        # Contract assertion: Channels MUST be stereo (2 channels)
        # Per contract [S19] and DEFAULT_FFMPEG_CMD: -ac 2
        assert "-ac" in cmd, \
            f"[FFMPEG_CMD] Command must specify channel count with -ac flag. Command: {cmd_str}"
        
        ac_idx = cmd.index("-ac")
        assert ac_idx + 1 < len(cmd), \
            f"[FFMPEG_CMD] -ac flag must have a value. Command: {cmd_str}"
        
        channels = cmd[ac_idx + 1]
        assert channels == "2", \
            f"[FFMPEG_CMD] Channels MUST be stereo (2) per contract. Found: {channels}. Command: {cmd_str}"
        
        # Contract assertion: Input MUST come from stdin pipe
        # Per contract [S19] and DEFAULT_FFMPEG_CMD: -i pipe:0
        assert "-i" in cmd, \
            f"[FFMPEG_CMD] Command must specify input with -i flag. Command: {cmd_str}"
        
        input_idx = cmd.index("-i")
        assert input_idx + 1 < len(cmd), \
            f"[FFMPEG_CMD] -i flag must have a value. Command: {cmd_str}"
        
        input_source = cmd[input_idx + 1]
        assert input_source == "pipe:0", \
            f"[FFMPEG_CMD] Input MUST come from stdin pipe (pipe:0) per contract. Found: {input_source}. Command: {cmd_str}"
        
        # Contract assertion: Output MUST be MP3 format
        # Per contract [S19] and DEFAULT_FFMPEG_CMD: -f mp3 (output format)
        # Note: -f appears twice (input and output), so we need to find the output format
        output_fmt_idx = None
        if "-i" in cmd:
            input_idx = cmd.index("-i")
            # Look for -f after -i (this is the output format)
            for i in range(input_idx + 1, len(cmd)):
                if cmd[i] == "-f" and i + 1 < len(cmd):
                    output_fmt_idx = i + 1
                    break
        
        if output_fmt_idx is not None:
            output_format = cmd[output_fmt_idx]
            assert output_format == "mp3", \
                f"[FFMPEG_CMD] Output format MUST be mp3 per contract. Found: {output_format}. Command: {cmd_str}"
        else:
            # Fallback: check if mp3 appears anywhere in command
            assert "mp3" in cmd, \
                f"[FFMPEG_CMD] Output format MUST be mp3 per contract. Command: {cmd_str}"
        
        # Contract assertion: Output MUST be stdout stream
        # Per contract [S19] and DEFAULT_FFMPEG_CMD: pipe:1
        assert "pipe:1" in cmd, \
            f"[FFMPEG_CMD] Output MUST be stdout stream (pipe:1) per contract. Command: {cmd_str}"
        
        # Additional contract requirement: Frame size MUST be 1152 per [S19.11]
        assert "-frame_size" in cmd, \
            f"[FFMPEG_CMD] Command MUST include -frame_size 1152 per contract [S19.11]. Command: {cmd_str}"
        
        frame_size_idx = cmd.index("-frame_size")
        assert frame_size_idx + 1 < len(cmd), \
            f"[FFMPEG_CMD] -frame_size flag must have a value. Command: {cmd_str}"
        
        frame_size = cmd[frame_size_idx + 1]
        assert frame_size == "1152", \
            f"[FFMPEG_CMD] Frame size MUST be 1152 per contract [S19.11]. Found: {frame_size}. Command: {cmd_str}"
        
        # Log the actual command for visibility
        print(f"\n[FFMPEG_CMD_VISIBILITY] Actual command that would be invoked:")
        print(f"  {' '.join(cmd)}")
        print(f"\n[FFMPEG_CMD_VISIBILITY] Command matches contract requirements ✓")
    
    def test_default_ffmpeg_cmd_structure(self):
        """
        Test that DEFAULT_FFMPEG_CMD has the expected structure.
        
        This provides visibility into the base command template.
        """
        cmd = DEFAULT_FFMPEG_CMD
        
        # Verify basic structure
        assert len(cmd) > 0, "DEFAULT_FFMPEG_CMD must not be empty"
        assert cmd[0] == "ffmpeg", "DEFAULT_FFMPEG_CMD must start with 'ffmpeg'"
        
        # Log the default command for visibility
        print(f"\n[DEFAULT_CMD_VISIBILITY] Base command template:")
        print(f"  {' '.join(cmd)}")
        
        # Verify key components are present
        assert "-f" in cmd and "s16le" in cmd, "DEFAULT_FFMPEG_CMD must include -f s16le"
        assert "-ar" in cmd and "48000" in cmd, "DEFAULT_FFMPEG_CMD must include -ar 48000"
        assert "-ac" in cmd and "2" in cmd, "DEFAULT_FFMPEG_CMD must include -ac 2"
        assert "-i" in cmd and "pipe:0" in cmd, "DEFAULT_FFMPEG_CMD must include -i pipe:0"
        assert "-frame_size" in cmd and "1152" in cmd, "DEFAULT_FFMPEG_CMD must include -frame_size 1152"
        assert "mp3" in cmd, "DEFAULT_FFMPEG_CMD must include mp3 output format"
        assert "pipe:1" in cmd, "DEFAULT_FFMPEG_CMD must include pipe:1 output"





