=== CONTRACT TEST AUDIT ===

Tests executed: 197  | Passed: 196 | Failed: 1 | Errors: 0


⚠ FAIL tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorRestartBehavior::test_s13_8_restart_goes_through_booting_state

Reason: Test failed (no error details)

Category: UNKNOWN FAILURE

Resolution: Test failed but no error details captured


--- Full Test Output ---
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.0.1, pluggy-1.6.0 -- /opt/retrowaves/venv/bin/python
cachedir: .pytest_cache
rootdir: /opt/retrowaves
configfile: pytest.ini
plugins: timeout-2.4.0, anyio-4.12.0
timeout: 60.0s
timeout method: thread
timeout func_only: False
collecting ... collected 329 items

tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterCoreInvariants::test_r1_bounded_queue PASSED [  0%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterCoreInvariants::test_r2_thread_safe PASSED [  0%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterCoreInvariants::test_r3_never_blocks PASSED [  0%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterCoreInvariants::test_r4_never_grows_unbounded PASSED [  1%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterInterface::test_r5_constructor_capacity PASSED [  1%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterInterface::test_r6_push_frame_method PASSED [  1%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterInterface::test_r6_get_frame_method PASSED [  2%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterInterface::test_r6_pop_frame_alias PASSED [  2%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterOverflow::test_r7_drops_newest_when_full PASSED [  2%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterOverflow::test_r7_never_blocks_or_raises PASSED [  3%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterOverflow::test_r8_stabilizes_with_consumption PASSED [  3%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterUnderflow::test_r9_non_blocking_when_timeout_none PASSED [  3%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterUnderflow::test_r9_waits_with_timeout PASSED [  3%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterUnderflow::test_r9_timeout_expires_returns_none PASSED [  4%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterUnderflow::test_r9_never_blocks_indefinitely PASSED [  4%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterUnderflow::test_r10_underflow_triggers_fallback PASSED [  4%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterPartialFrames::test_r11_partial_frames_discarded PASSED [  5%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterPartialFrames::test_r13_never_returns_partial PASSED [  5%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterThreadSafety::test_r15_all_operations_thread_safe PASSED [  5%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterThreadSafety::test_r16_multiple_concurrent_writers PASSED [  6%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterThreadSafety::test_r17_single_reader PASSED [  6%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterThreadSafety::test_r18_no_deadlock PASSED [  6%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterSocketIntegration::test_r19_decoupled_from_socket PASSED [  6%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterSocketIntegration::test_r20_socket_reader_separate PASSED [  7%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterSocketIntegration::test_r21_socket_calls_push_frame PASSED [  7%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterSocketIntegration::test_r22_audiopump_calls_pop_independently PASSED [  7%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpMetronome::test_a1_sole_metronome PASSED [  8%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpMetronome::test_a2_never_interacts_with_supervisor PASSED [  8%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpMetronome::test_a3_only_calls_encoder_manager_write_pcm PASSED [  8%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpMetronome::test_a4_timing_loop_24ms PASSED [  9%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpInterface::test_a5_constructor_parameters PASSED [  9%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpInterface::test_a6_public_interface PASSED [  9%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpFrameSelection::test_a7_frame_selection_pcm_first PASSED [ 10%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpFrameSelection::test_a7_frame_selection_fallback_when_empty PASSED [ 10%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpFrameSelection::test_a7_grace_period_uses_silence PASSED [ 10%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpFrameSelection::test_a7_uses_timeout_in_pop_frame PASSED [ 10%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpFrameSelection::test_a8_non_blocking_selection PASSED [ 11%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpTiming::test_a9_absolute_clock_timing PASSED [ 11%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpTiming::test_a10_resync_on_behind_schedule PASSED [ 11%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpTiming::test_a11_sleeps_if_ahead PASSED [ 12%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpErrorHandling::test_a12_write_errors_logged_not_crashed PASSED [ 12%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpErrorHandling::test_a13_sleeps_after_error PASSED [ 12%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpLifecycleResponsibility::test_a0_tower_service_creates_audiopump PASSED [ 13%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpLifecycleResponsibility::test_a0_tower_service_starts_audiopump PASSED [ 13%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpLifecycleResponsibility::test_a0_audiopump_runs_continuously PASSED [ 13%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpLifecycleResponsibility::test_a0_system_mp3_output_depends_on_audiopump PASSED [ 13%]
tower/tests/contracts/test_tower_encoder_buffers.py::TestFrameRingBuffer::test_push_pop_fifo PASSED [ 14%]
tower/tests/contracts/test_tower_encoder_buffers.py::TestFrameRingBuffer::test_overflow_drops_oldest PASSED [ 14%]
tower/tests/contracts/test_tower_encoder_buffers.py::TestFrameRingBuffer::test_len_updates_correctly PASSED [ 14%]
tower/tests/contracts/test_tower_encoder_buffers.py::TestFrameRingBuffer::test_no_blocking_behavior PASSED [ 15%]
tower/tests/contracts/test_tower_encoder_buffers.py::TestFrameRingBuffer::test_handles_thousands_of_operations PASSED [ 15%]
tower/tests/contracts/test_tower_encoder_buffers.py::TestFrameRingBuffer::test_thread_safety_smoke PASSED [ 15%]
tower/tests/contracts/test_tower_encoder_buffers.py::TestFrameRingBuffer::test_capacity_property PASSED [ 16%]
tower/tests/contracts/test_tower_encoder_buffers.py::TestFrameRingBuffer::test_empty_frame_rejected PASSED [ 16%]
tower/tests/contracts/test_tower_encoder_buffers.py::TestFrameRingBuffer::test_zero_capacity_rejected PASSED [ 16%]
tower/tests/contracts/test_tower_encoder_drain_thread.py::TestEncoderOutputDrainThread::test_feeds_packetizer_correctly PASSED [ 17%]
tower/tests/contracts/test_tower_encoder_drain_thread.py::TestEncoderOutputDrainThread::test_pushes_frames_into_mp3_buffer PASSED [ 17%]
tower/tests/contracts/test_tower_encoder_drain_thread.py::TestEncoderOutputDrainThread::test_detects_stall_and_triggers_restart PASSED [ 17%]
tower/tests/contracts/test_tower_encoder_drain_thread.py::TestEncoderOutputDrainThread::test_no_blocking_behavior PASSED [ 17%]
tower/tests/contracts/test_tower_encoder_drain_thread.py::TestEncoderOutputDrainThread::test_thread_exits_cleanly_on_stop PASSED [ 18%]
tower/tests/contracts/test_tower_encoder_drain_thread.py::TestEncoderOutputDrainThread::test_handles_eof_gracefully PASSED [ 18%]
tower/tests/contracts/test_tower_encoder_drain_thread.py::TestEncoderOutputDrainThread::test_handles_select_errors PASSED [ 18%]
tower/tests/contracts/test_tower_encoder_drain_thread.py::TestEncoderOutputDrainThread::test_reads_in_chunks PASSED [ 19%]
tower/tests/contracts/test_tower_encoder_drain_thread.py::TestEncoderOutputDrainThread::test_partial_chunks_accumulate_until_full_frame PASSED [ 19%]
tower/tests/contracts/test_tower_encoder_drain_thread.py::TestEncoderOutputDrainThread::test_feed_yields_frames_incrementally PASSED [ 19%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_m1_encoder_manager_owns_supervisor PASSED [ 20%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_m2_never_exposes_supervisor PASSED [ 20%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_m3_public_interface_limited PASSED [ 20%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_m4_internally_maintains_buffers PASSED [ 20%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_m5_supervisor_created_in_init PASSED [ 21%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_m6_supervisor_lifecycle_encapsulated PASSED [ 21%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_starts_ffmpeg_process PASSED [ 21%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_state_transitions_to_running PASSED [ 22%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_m12_state_tracks_supervisor_resolves_as_operational_modes PASSED [ 22%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_m8_write_pcm_forwards_to_supervisor PASSED [ 22%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_m8_write_pcm_non_blocking PASSED [ 23%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_m9_pcm_frames_written_directly PASSED [ 23%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_write_pcm_handles_broken_pipe_non_blocking PASSED [ 23%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_write_pcm_multiple_calls_after_broken_pipe PASSED [ 24%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_can_stop_cleanly_without_zombie_ffmpeg PASSED [ 24%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_restart_does_not_clear_mp3_buffer PASSED [ 24%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_restart_triggers_after_async_call PASSED [ 24%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_get_frame_returns_silence_when_empty PASSED [ 25%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_get_frame_returns_frame_when_available PASSED [ 25%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_get_frame_never_blocks PASSED [ 25%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_max_restarts_enters_failed_state PASSED [ 26%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManagerOperationalModes::test_m14_translates_supervisor_state_to_operational_modes PASSED [ 26%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManagerOperationalModes::test_m15_get_frame_applies_source_selection_rules PASSED [ 26%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManagerOperationalModes::test_m16_write_pcm_only_during_live_input PASSED [ 27%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManagerOperationalModes::test_m17_offline_test_mode_bypasses_supervisor PASSED [ 27%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManagerOperationalModes::test_m18_no_raw_supervisor_state_exposure PASSED [ 27%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderOperationalModes::test_o1_cold_start_mode PASSED [ 27%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderOperationalModes::test_o2_booting_mode_instant_playback PASSED [ 28%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderOperationalModes::test_o2_2_frame_boundary_alignment PASSED [ 28%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderOperationalModes::test_o6_offline_test_mode PASSED [ 28%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderModeTransitions::test_o8_mode_transitions_atomic_and_thread_safe PASSED [ 29%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderModeTransitions::test_o9_continuous_output_during_transitions PASSED [ 29%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderModeTransitions::test_o11_clients_no_disconnections_during_transitions PASSED [ 29%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderOutputGuarantees::test_o12_continuous_output_requirement PASSED [ 30%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderOutputGuarantees::test_o13_frame_source_priority PASSED [ 30%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderOutputGuarantees::test_o14_mode_aware_frame_selection PASSED [ 30%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderTestingModeRequirements::test_o15_1_unit_tests_must_use_offline_test_mode PASSED [ 31%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderTestingModeRequirements::test_o15_6_tests_fail_if_ffmpeg_launched_without_explicit_request PASSED [ 31%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderTestingModeRequirements::test_o16_1_env_var_activates_offline_test_mode PASSED [ 31%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderTestingModeRequirements::test_o16_3_offline_test_mode_no_supervisor_creation PASSED [ 31%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderBroadcastGradeRequirements::test_o17_never_stall_transmission PASSED [ 32%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderBroadcastGradeRequirements::test_o18_graceful_degradation PASSED [ 32%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderBroadcastGradeRequirements::test_o20_output_cadence_guarantee PASSED [ 32%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderBroadcastGradeRequirements::test_o21_seamless_recovery PASSED [ 33%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderBroadcastGradeRequirements::test_o22_mode_telemetry PASSED [ 33%]
tower/tests/contracts/test_tower_encoder_packetizer.py::TestMP3Packetizer::test_packetizer_feed_contract PASSED [ 33%]
tower/tests/contracts/test_tower_encoder_packetizer.py::TestMP3Packetizer::test_feed_one_frame_returns_frame PASSED [ 34%]
tower/tests/contracts/test_tower_encoder_packetizer.py::TestMP3Packetizer::test_feed_partial_header_returns_empty PASSED [ 34%]
tower/tests/contracts/test_tower_encoder_packetizer.py::TestMP3Packetizer::test_feed_two_frames_back_to_back PASSED [ 34%]
tower/tests/contracts/test_tower_encoder_packetizer.py::TestMP3Packetizer::test_feed_partial_frame_then_rest PASSED [ 34%]
tower/tests/contracts/test_tower_encoder_packetizer.py::TestMP3Packetizer::test_mixed_fragmentation_scenario_1 PASSED [ 35%]
tower/tests/contracts/test_tower_encoder_packetizer.py::TestMP3Packetizer::test_mixed_fragmentation_scenario_2 PASSED [ 35%]
tower/tests/contracts/test_tower_encoder_packetizer.py::TestMP3Packetizer::test_mixed_fragmentation_scenario_3 PASSED [ 35%]
tower/tests/contracts/test_tower_encoder_packetizer.py::TestMP3Packetizer::test_mixed_fragmentation_scenario_4 PASSED [ 36%]
tower/tests/contracts/test_tower_encoder_packetizer.py::TestMP3Packetizer::test_mixed_fragmentation_scenario_5 PASSED [ 36%]
tower/tests/contracts/test_tower_encoder_packetizer.py::TestMP3Packetizer::test_sync_word_detection PASSED [ 36%]
tower/tests/contracts/test_tower_encoder_packetizer.py::TestMP3Packetizer::test_frame_size_computation PASSED [ 37%]
tower/tests/contracts/test_tower_encoder_packetizer.py::TestMP3Packetizer::test_never_emits_partial_frames PASSED [ 37%]
tower/tests/contracts/test_tower_encoder_packetizer.py::TestMP3Packetizer::test_p1_accepts_byte_chunks_any_size PASSED [ 37%]
tower/tests/contracts/test_tower_encoder_packetizer.py::TestMP3Packetizer::test_p2_buffers_until_full_frame_available PASSED [ 37%]
tower/tests/contracts/test_tower_encoder_packetizer.py::TestMP3Packetizer::test_p3_emits_frames_one_by_one_generator PASSED [ 38%]
tower/tests/contracts/test_tower_encoder_packetizer.py::TestMP3Packetizer::test_p4_resync_on_malformed_input_missing_sync PASSED [ 38%]
tower/tests/contracts/test_tower_encoder_packetizer.py::TestMP3Packetizer::test_p4_resync_on_invalid_sync_word PASSED [ 38%]
tower/tests/contracts/test_tower_encoder_packetizer.py::TestMP3Packetizer::test_p4_resync_after_corrupted_frame PASSED [ 39%]
tower/tests/contracts/test_tower_encoder_packetizer.py::TestMP3Packetizer::test_p5_never_emits_partial_frames PASSED [ 39%]
tower/tests/contracts/test_tower_encoder_packetizer.py::TestMP3Packetizer::test_p5_never_emits_partial_even_on_stream_end PASSED [ 39%]
tower/tests/contracts/test_tower_encoder_packetizer.py::TestMP3Packetizer::test_p6_handle_split_headers PASSED [ 40%]
tower/tests/contracts/test_tower_encoder_packetizer.py::TestMP3Packetizer::test_p6_handle_multi_frame_blobs PASSED [ 40%]
tower/tests/contracts/test_tower_encoder_packetizer.py::TestMP3Packetizer::test_p6_handle_split_frame_boundaries PASSED [ 40%]
tower/tests/contracts/test_tower_encoder_packetizer.py::TestMP3Packetizer::test_p6_handle_split_header_and_payload PASSED [ 41%]
tower/tests/contracts/test_tower_encoder_packetizer.py::TestMP3Packetizer::test_output_guarantees_raw_bytes_unchanged PASSED [ 41%]
tower/tests/contracts/test_tower_encoder_packetizer.py::TestMP3Packetizer::test_buffer_cap_discards_oldest_bytes PASSED [ 41%]
tower/tests/contracts/test_tower_encoder_packetizer.py::TestMP3Packetizer::test_vbr_support_different_frame_sizes PASSED [ 41%]
tower/tests/contracts/test_tower_encoder_packetizer.py::TestMP3Packetizer::test_vbr_support_padding_variation PASSED [ 42%]
tower/tests/contracts/test_tower_encoder_packetizer.py::TestMP3Packetizer::test_performance_o_n_time_no_blocking PASSED [ 42%]
tower/tests/contracts/test_tower_encoder_packetizer.py::TestMP3Packetizer::test_streaming_invariant_unbounded_streams PASSED [ 42%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorCoreInvariants::test_f1_always_returns_valid_frame PASSED [ 43%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorCoreInvariants::test_f2_format_guarantees PASSED [ 43%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorCoreInvariants::test_f3_always_has_fallback_source PASSED [ 43%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorSourceSelection::test_f4_source_priority_order PASSED [ 44%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorSourceSelection::test_f5_falls_through_to_tone PASSED [ 44%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorSourceSelection::test_f6_falls_through_to_silence PASSED [ 44%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorSourceSelection::test_f7_priority_deterministic PASSED [ 44%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorToneGenerator::test_f10_440hz_tone PASSED [ 45%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorToneGenerator::test_f11_phase_accumulator PASSED [ 45%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorToneGenerator::test_f12_tone_selected_when_no_file PASSED [ 45%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorToneGenerator::test_f13_falls_to_silence_on_error PASSED [ 46%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorSilenceSource::test_f14_continuous_zeros PASSED [ 46%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorSilenceSource::test_f15_always_available PASSED [ 46%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorSilenceSource::test_f16_selected_on_tone_failure PASSED [ 47%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorSilenceSource::test_f17_never_fails PASSED [ 47%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorInterface::test_f18_constructor_no_parameters PASSED [ 47%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorInterface::test_f19_get_frame_method PASSED [ 48%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorInterface::test_f20_idempotent PASSED [ 48%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorFormatGuarantees::test_f21_exactly_4608_bytes PASSED [ 48%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorFormatGuarantees::test_f22_canonical_format PASSED [ 48%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorFormatGuarantees::test_f23_frame_boundaries_preserved PASSED [ 49%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorLiveness::test_s5_process_starts_successfully PASSED [ 49%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorLiveness::test_s6_stderr_capture_thread_started PASSED [ 49%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorLiveness::test_s6a_booting_state_transition PASSED [ 50%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorLiveness::test_s7_first_frame_soft_target_500ms PASSED [ 50%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorLiveness::test_s7a_hard_startup_timeout PASSED [ 50%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorLiveness::test_s7b_first_frame_timer_uses_wall_clock_time PASSED [ 51%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorLiveness::test_s7_1_pcm_input_during_booting PASSED [ 51%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorLiveness::test_s8_continuous_frames_within_interval PASSED [ 51%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorFailureDetection::test_s9_process_failure_detection PASSED [ 51%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorFailureDetection::test_s10_startup_timeout_detection PASSED [ 52%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorFailureDetection::test_s11_stall_detection PASSED [ 52%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorFailureDetection::test_s12_frame_interval_violation PASSED [ 52%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorRestartBehavior::test_s13_1_logs_failure_reason PASSED [ 53%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorRestartBehavior::test_s13_2_transitions_to_restarting PASSED [ 53%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorRestartBehavior::test_s13_3_preserves_mp3_buffer PASSED [ 53%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorRestartBehavior::test_s13_3b_mp3_output_remains_continuous_during_restart PASSED [ 54%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorRestartBehavior::test_s13_3c_frame_delivery_continues_from_buffer_during_restart PASSED [ 54%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorRestartBehavior::test_s13_4_follows_backoff_schedule PASSED [ 54%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorRestartBehavior::test_s13_5_max_restarts_enforced PASSED [ 55%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorRestartBehavior::test_s13_6_enters_failed_state PASSED [ 55%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorRestartBehavior::test_s13_8_restart_goes_through_booting_state FAILED [ 55%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorStderrCapture::test_s14_1_stderr_thread_starts_immediately PASSED [ 55%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorStderrCapture::test_s14_2_stderr_set_to_non_blocking PASSED [ 56%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorStderrCapture::test_s14_3_logs_with_ffmpeg_prefix PASSED [ 56%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorStderrCapture::test_s14_4_daemon_thread PASSED [ 56%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorStderrCapture::test_s14_5_continues_until_stderr_closes PASSED [ 57%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorStderrCapture::test_s14_7_stdout_drain_thread_ordering_and_non_blocking_termination PASSED [ 57%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorFrameTiming::test_s15_frame_interval_calculation PASSED [ 57%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorFrameTiming::test_s16_tolerance_window PASSED [ 58%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorFrameTiming::test_s17_tracks_last_frame_timestamp PASSED [ 58%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorFrameTiming::test_s18_detects_interval_violation PASSED [ 58%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorStartupSequence::test_s19_startup_sequence_order PASSED [ 58%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorStartupSequence::test_s19_13_start_completion_guarantee_returns_booting PASSED [ 59%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorStartupSequence::test_s19_14_deferred_failure_handling_during_starting PASSED [ 59%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorErrorLogging::test_s20_1_logs_process_exit PASSED [ 59%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorErrorLogging::test_s20_1_logs_encoder_live_on_running_transition +++++++++++++++++++++++++++++++++++ Timeout ++++++++++++++++++++++++++++++++++++
~~~~~~~~~~~~~~~~~~ Stack of EncoderRestart (139948883699392) ~~~~~~~~~~~~~~~~~~~
  File "/usr/lib/python3.11/threading.py", line 995, in _bootstrap
    self._bootstrap_inner()
  File "/usr/lib/python3.11/threading.py", line 1038, in _bootstrap_inner
    self.run()
  File "/usr/lib/python3.11/threading.py", line 975, in run
    self._target(*self._args, **self._kwargs)
  File "/opt/retrowaves/tower/encoder/ffmpeg_supervisor.py", line 1087, in _restart_worker
    self._start_encoder_process()
  File "/opt/retrowaves/tower/encoder/ffmpeg_supervisor.py", line 524, in _start_encoder_process
    time.sleep(0.2)  # Give FFmpeg a moment to start
~~~~~~~~~~~~~~~ Stack of StartupTimeoutMonitor (139949420541632) ~~~~~~~~~~~~~~~
  File "/usr/lib/python3.11/threading.py", line 995, in _bootstrap
    self._bootstrap_inner()
  File "/usr/lib/python3.11/threading.py", line 1038, in _bootstrap_inner
    self.run()
  File "/usr/lib/python3.11/threading.py", line 975, in run
    self._target(*self._args, **self._kwargs)
  File "/opt/retrowaves/tower/encoder/ffmpeg_supervisor.py", line 901, in _monitor_startup_timeout
    time.sleep(SOFT_STARTUP_TARGET_SEC)
~~~~~~~~~~~~~~~~~~ Stack of EncoderRestart (139949395363520) ~~~~~~~~~~~~~~~~~~~
  File "/usr/lib/python3.11/threading.py", line 995, in _bootstrap
    self._bootstrap_inner()
  File "/usr/lib/python3.11/threading.py", line 1038, in _bootstrap_inner
    self.run()
  File "/usr/lib/python3.11/threading.py", line 975, in run
    self._target(*self._args, **self._kwargs)
  File "/opt/retrowaves/tower/encoder/ffmpeg_supervisor.py", line 1087, in _restart_worker
    self._start_encoder_process()
  File "/opt/retrowaves/tower/encoder/ffmpeg_supervisor.py", line 524, in _start_encoder_process
    time.sleep(0.2)  # Give FFmpeg a moment to start
~~~~~~~~~~~~~~~~~~ Stack of EncoderRestart (139949470897856) ~~~~~~~~~~~~~~~~~~~
  File "/usr/lib/python3.11/threading.py", line 995, in _bootstrap
    self._bootstrap_inner()
  File "/usr/lib/python3.11/threading.py", line 1038, in _bootstrap_inner
    self.run()
  File "/usr/lib/python3.11/threading.py", line 975, in run
    self._target(*self._args, **self._kwargs)
  File "/opt/retrowaves/tower/encoder/ffmpeg_supervisor.py", line 1087, in _restart_worker
    self._start_encoder_process()
  File "/opt/retrowaves/tower/encoder/ffmpeg_supervisor.py", line 524, in _start_encoder_process
    time.sleep(0.2)  # Give FFmpeg a moment to start
~~~~~~~~~~~~~~~ Stack of StartupTimeoutMonitor (139948741088960) ~~~~~~~~~~~~~~~
  File "/usr/lib/python3.11/threading.py", line 995, in _bootstrap
    self._bootstrap_inner()
  File "/usr/lib/python3.11/threading.py", line 1038, in _bootstrap_inner
    self.run()
  File "/usr/lib/python3.11/threading.py", line 975, in run
    self._target(*self._args, **self._kwargs)
  File "/opt/retrowaves/tower/encoder/ffmpeg_supervisor.py", line 912, in _monitor_startup_timeout
    time.sleep(remaining_time)
~~~~~~~~~~~~~~~ Stack of StartupTimeoutMonitor (139949738280640) ~~~~~~~~~~~~~~~
  File "/usr/lib/python3.11/threading.py", line 995, in _bootstrap
    self._bootstrap_inner()
  File "/usr/lib/python3.11/threading.py", line 1038, in _bootstrap_inner
    self.run()
  File "/usr/lib/python3.11/threading.py", line 975, in run
    self._target(*self._args, **self._kwargs)
  File "/opt/retrowaves/tower/encoder/ffmpeg_supervisor.py", line 912, in _monitor_startup_timeout
    time.sleep(remaining_time)
~~~~~~~~~~~~~~~ Stack of StartupTimeoutMonitor (139949403756224) ~~~~~~~~~~~~~~~
  File "/usr/lib/python3.11/threading.py", line 995, in _bootstrap
    self._bootstrap_inner()
  File "/usr/lib/python3.11/threading.py", line 1038, in _bootstrap_inner
    self.run()
  File "/usr/lib/python3.11/threading.py", line 975, in run
    self._target(*self._args, **self._kwargs)
  File "/opt/retrowaves/tower/encoder/ffmpeg_supervisor.py", line 912, in _monitor_startup_timeout
    time.sleep(remaining_time)
~~~~~~~~~~~~~~~ Stack of StartupTimeoutMonitor (139950417761984) ~~~~~~~~~~~~~~~
  File "/usr/lib/python3.11/threading.py", line 995, in _bootstrap
    self._bootstrap_inner()
  File "/usr/lib/python3.11/threading.py", line 1038, in _bootstrap_inner
    self.run()
  File "/usr/lib/python3.11/threading.py", line 975, in run
    self._target(*self._args, **self._kwargs)
  File "/opt/retrowaves/tower/encoder/ffmpeg_supervisor.py", line 912, in _monitor_startup_timeout
    time.sleep(remaining_time)
~~~~~~~~~~~~~~~ Stack of StartupTimeoutMonitor (139948757874368) ~~~~~~~~~~~~~~~
  File "/usr/lib/python3.11/threading.py", line 995, in _bootstrap
    self._bootstrap_inner()
  File "/usr/lib/python3.11/threading.py", line 1038, in _bootstrap_inner
    self.run()
  File "/usr/lib/python3.11/threading.py", line 975, in run
    self._target(*self._args, **self._kwargs)
  File "/opt/retrowaves/tower/encoder/ffmpeg_supervisor.py", line 918, in _monitor_startup_timeout
    self._handle_failure("startup_timeout")
  File "/opt/retrowaves/tower/encoder/ffmpeg_supervisor.py", line 940, in _handle_failure
    with self._state_lock:
~~~~~~~~~~~~~~~~~ Stack of FFmpegStdoutDrain (139948892092096) ~~~~~~~~~~~~~~~~~
  File "/usr/lib/python3.11/threading.py", line 995, in _bootstrap
    self._bootstrap_inner()
  File "/usr/lib/python3.11/threading.py", line 1038, in _bootstrap_inner
    self.run()
  File "/usr/lib/python3.11/threading.py", line 975, in run
    self._target(*self._args, **self._kwargs)
  File "/opt/retrowaves/tower/encoder/ffmpeg_supervisor.py", line 802, in _stdout_drain
    self._handle_failure("eof", exit_code=exit_code)
  File "/opt/retrowaves/tower/encoder/ffmpeg_supervisor.py", line 940, in _handle_failure
    with self._state_lock:
~~~~~~~~~~~~~~~~~~~~ Stack of MainThread (139951439425600) ~~~~~~~~~~~~~~~~~~~~~
  File "<frozen runpy>", line 198, in _run_module_as_main
  File "<frozen runpy>", line 88, in _run_code
  File "/opt/retrowaves/venv/lib/python3.11/site-packages/pytest/__main__.py", line 9, in <module>
    raise SystemExit(pytest.console_main())
  File "/opt/retrowaves/venv/lib/python3.11/site-packages/_pytest/config/__init__.py", line 221, in console_main
    code = main()
  File "/opt/retrowaves/venv/lib/python3.11/site-packages/_pytest/config/__init__.py", line 197, in main
    ret: ExitCode | int = config.hook.pytest_cmdline_main(config=config)
  File "/opt/retrowaves/venv/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__
    return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
  File "/opt/retrowaves/venv/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec
    return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
  File "/opt/retrowaves/venv/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall
    res = hook_impl.function(*args)
  File "/opt/retrowaves/venv/lib/python3.11/site-packages/_pytest/main.py", line 365, in pytest_cmdline_main
    return wrap_session(config, _main)
  File "/opt/retrowaves/venv/lib/python3.11/site-packages/_pytest/main.py", line 318, in wrap_session
    session.exitstatus = doit(config, session) or 0
  File "/opt/retrowaves/venv/lib/python3.11/site-packages/_pytest/main.py", line 372, in _main
    config.hook.pytest_runtestloop(session=session)
  File "/opt/retrowaves/venv/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__
    return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
  File "/opt/retrowaves/venv/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec
    return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
  File "/opt/retrowaves/venv/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall
    res = hook_impl.function(*args)
  File "/opt/retrowaves/venv/lib/python3.11/site-packages/_pytest/main.py", line 396, in pytest_runtestloop
    item.config.hook.pytest_runtest_protocol(item=item, nextitem=nextitem)
  File "/opt/retrowaves/venv/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__
    return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
  File "/opt/retrowaves/venv/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec
    return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
  File "/opt/retrowaves/venv/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall
    res = hook_impl.function(*args)
  File "/opt/retrowaves/venv/lib/python3.11/site-packages/_pytest/runner.py", line 118, in pytest_runtest_protocol
    runtestprotocol(item, nextitem=nextitem)
  File "/opt/retrowaves/venv/lib/python3.11/site-packages/_pytest/runner.py", line 137, in runtestprotocol
    reports.append(call_and_report(item, "call", log))
  File "/opt/retrowaves/venv/lib/python3.11/site-packages/_pytest/runner.py", line 244, in call_and_report
    call = CallInfo.from_call(
  File "/opt/retrowaves/venv/lib/python3.11/site-packages/_pytest/runner.py", line 353, in from_call
    result: TResult | None = func()
  File "/opt/retrowaves/venv/lib/python3.11/site-packages/_pytest/runner.py", line 245, in <lambda>
    lambda: runtest_hook(item=item, **kwds),
  File "/opt/retrowaves/venv/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__
    return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
  File "/opt/retrowaves/venv/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec
    return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
  File "/opt/retrowaves/venv/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall
    res = hook_impl.function(*args)
  File "/opt/retrowaves/venv/lib/python3.11/site-packages/_pytest/runner.py", line 179, in pytest_runtest_call
    item.runtest()
  File "/opt/retrowaves/venv/lib/python3.11/site-packages/_pytest/python.py", line 1720, in runtest
    self.ihook.pytest_pyfunc_call(pyfuncitem=self)
  File "/opt/retrowaves/venv/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__
    return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
  File "/opt/retrowaves/venv/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec
    return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
  File "/opt/retrowaves/venv/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall
    res = hook_impl.function(*args)
  File "/opt/retrowaves/venv/lib/python3.11/site-packages/_pytest/python.py", line 166, in pytest_pyfunc_call
    result = testfunction(**testargs)
  File "/opt/retrowaves/tower/tests/contracts/test_tower_ffmpeg_supervisor.py", line 1118, in test_s20_1_logs_encoder_live_on_running_transition
    encoder_manager._supervisor._transition_to_running()
  File "/opt/retrowaves/tower/encoder/ffmpeg_supervisor.py", line 336, in _transition_to_running
    with self._state_lock:
+++++++++++++++++++++++++++++++++++ Timeout ++++++++++++++++++++++++++++++++++++

