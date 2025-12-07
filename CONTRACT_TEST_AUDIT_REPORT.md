=== CONTRACT TEST AUDIT ===

Tests executed: 349  | Passed: 346 | Failed: 3 | Errors: 0


⚠ FAIL tower/tests/contracts/test_supervisor_boot_pcm_flow.py::TestSupervisorBootPCMFlow::test_pcm_is_forwarded_during_boot

Reason: Test failed (no error details)

Category: UNKNOWN FAILURE

Resolution: Test failed but no error details captured


⚠ FAIL tower/tests/contracts/test_tower_encoder_manager.py::TestContinuousSilenceDuringBoot::test_supervisor_continuous_silence_until_pcm_available

Reason: Test failed (no error details)

Category: UNKNOWN FAILURE

Resolution: Test failed but no error details captured


⚠ FAIL tower/tests/contracts/test_tower_ffmpeg_supervisor_startup.py::TestSupervisorStartupInitialPCM::test_supervisor_starts_ffmpeg_and_accepts_pcm

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
collecting ... collected 349 items

tower/tests/contracts/test_encoder_manager_boot_fallback_continuity.py::TestEncoderManagerBootFallbackContinuity::test_next_frame_during_booting_never_returns_none PASSED [  0%]
tower/tests/contracts/test_encoder_manager_boot_fallback_continuity.py::TestEncoderManagerBootFallbackContinuity::test_boot_fallback_frames_are_valid_size PASSED [  0%]
tower/tests/contracts/test_encoder_manager_boot_fallback_continuity.py::TestEncoderManagerBootFallbackContinuity::test_boot_fallback_independent_of_supervisor_startup_state PASSED [  0%]
tower/tests/contracts/test_encoder_manager_boot_fallback_continuity.py::TestEncoderManagerBootFallbackContinuity::test_supervisor_continuous_silence_until_pcm_available PASSED [  1%]
tower/tests/contracts/test_encoder_manager_boot_fallback_continuity.py::TestEncoderManagerBootFallbackContinuity::test_supervisor_boot_silence_cadence_jitter_tolerance PASSED [  1%]
tower/tests/contracts/test_encoder_manager_pcm_availability.py::TestEncoderManagerPCMAvailability::test_next_frame_never_none PASSED [  1%]
tower/tests/contracts/test_encoder_manager_pcm_availability.py::TestEncoderManagerPCMAvailability::test_next_frame_correct_size PASSED [  2%]
tower/tests/contracts/test_encoder_manager_pcm_availability.py::TestEncoderManagerPCMAvailability::test_provides_fallback_before_supervisor_starts PASSED [  2%]
tower/tests/contracts/test_encoder_manager_pcm_availability.py::TestEncoderManagerPCMAvailability::test_s7_0b_pcm_available_before_supervisor_start_called PASSED [  2%]
tower/tests/contracts/test_encoder_manager_pcm_availability.py::TestEncoderManagerPCMAvailability::test_s7_0b_prevents_race_condition_with_supervisor PASSED [  2%]
tower/tests/contracts/test_encoder_manager_pcm_availability.py::TestEncoderManagerPCMAvailability::test_pcm_conforms_to_manager_audio_format PASSED [  3%]
tower/tests/contracts/test_encoder_manager_pcm_availability.py::TestEncoderManagerPCMAvailability::test_fallback_is_immediate_and_zero_latency PASSED [  3%]
tower/tests/contracts/test_encoder_manager_pcm_availability.py::TestEncoderManagerPCMAvailability::test_s7_0f_tone_preference_over_silence PASSED [  3%]
tower/tests/contracts/test_encoder_manager_pcm_availability.py::TestEncoderManagerPCMAvailability::test_s7_0e_silence_vs_tone_is_internal_policy PASSED [  4%]
tower/tests/contracts/test_ffmpeg_supervisor_command_matches_contract.py::TestFFmpegCommandMatchesContract::test_ffmpeg_invocation_matches_contract PASSED [  4%]
tower/tests/contracts/test_ffmpeg_supervisor_command_matches_contract.py::TestFFmpegCommandMatchesContract::test_default_ffmpeg_cmd_structure PASSED [  4%]
tower/tests/contracts/test_ffmpeg_supervisor_drain_thread_ordering.py::TestDrainThreadOrderingBeforePCMWrite::test_stdout_stderr_drain_threads_start_before_initial_pcm_write PASSED [  4%]
tower/tests/contracts/test_full_system_boot_sustains_ffmpeg_until_running.py::TestFullSystemBootSustainsFFmpeg::test_full_system_boot_sustains_ffmpeg_until_running PASSED [  5%]
tower/tests/contracts/test_pcm_selection_priority.py::TestPCMSelectionPriority::test_pcm_selected_above_grace_silence_and_fallback PASSED [  5%]
tower/tests/contracts/test_supervisor_boot_pcm_flow.py::TestSupervisorBootPCMFlow::test_pcm_is_forwarded_during_boot FAILED [  5%]
tower/tests/contracts/test_supervisor_boot_priming.py::TestSupervisorBootPriming::test_s7_3_encoder_boot_priming_requirements PASSED [  6%]
tower/tests/contracts/test_supervisor_ffmpeg_stderr_visibility.py::TestFFmpegDiagnostics::test_ffmpeg_emits_startup_stderr_on_failure PASSED [  6%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterCoreInvariants::test_r1_bounded_queue PASSED [  6%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterCoreInvariants::test_r2_thread_safe PASSED [  6%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterCoreInvariants::test_r3_never_blocks PASSED [  7%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterCoreInvariants::test_r4_never_grows_unbounded PASSED [  7%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterInterface::test_r5_constructor_capacity PASSED [  7%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterInterface::test_r6_push_frame_method PASSED [  8%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterInterface::test_r6_get_frame_method PASSED [  8%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterInterface::test_r6_pop_frame_alias PASSED [  8%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterOverflow::test_r7_drops_newest_when_full PASSED [  8%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterOverflow::test_r7_never_blocks_or_raises PASSED [  9%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterOverflow::test_r8_stabilizes_with_consumption PASSED [  9%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterUnderflow::test_r9_non_blocking_when_timeout_none PASSED [  9%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterUnderflow::test_r9_waits_with_timeout PASSED [ 10%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterUnderflow::test_r9_timeout_expires_returns_none PASSED [ 10%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterUnderflow::test_r9_never_blocks_indefinitely PASSED [ 10%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterUnderflow::test_r10_underflow_triggers_fallback PASSED [ 10%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterPartialFrames::test_r11_partial_frames_discarded PASSED [ 11%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterPartialFrames::test_r13_never_returns_partial PASSED [ 11%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterThreadSafety::test_r15_all_operations_thread_safe PASSED [ 11%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterThreadSafety::test_r16_multiple_concurrent_writers PASSED [ 12%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterThreadSafety::test_r17_single_reader PASSED [ 12%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterThreadSafety::test_r18_no_deadlock PASSED [ 12%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterSocketIntegration::test_r19_decoupled_from_socket PASSED [ 12%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterSocketIntegration::test_r20_socket_reader_separate PASSED [ 13%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterSocketIntegration::test_r21_socket_calls_push_frame PASSED [ 13%]
tower/tests/contracts/test_tower_audio_input_router.py::TestAudioInputRouterSocketIntegration::test_r22_audiopump_calls_pop_independently PASSED [ 13%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpMetronome::test_a1_sole_metronome PASSED [ 14%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpMetronome::test_a2_never_interacts_with_supervisor PASSED [ 14%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpMetronome::test_a3_only_calls_encoder_manager_next_frame PASSED [ 14%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpMetronome::test_a4_timing_loop_24ms PASSED [ 14%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpInterface::test_a5_constructor_parameters PASSED [ 15%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpInterface::test_a6_public_interface PASSED [ 15%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpFrameSelection::test_a5_calls_next_frame_each_tick PASSED [ 15%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpFrameSelection::test_a7_no_routing_logic PASSED [ 16%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpFrameSelection::test_a8_no_grace_period_logic PASSED [ 16%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpFrameSelection::test_a9_no_fallback_selection PASSED [ 16%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpTiming::test_a9_absolute_clock_timing PASSED [ 16%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpTiming::test_a10_resync_on_behind_schedule PASSED [ 17%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpTiming::test_a11_sleeps_if_ahead PASSED [ 17%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpErrorHandling::test_a12_next_frame_errors_logged_not_crashed PASSED [ 17%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpErrorHandling::test_a13_sleeps_after_error PASSED [ 18%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpLifecycleResponsibility::test_a0_tower_service_creates_audiopump PASSED [ 18%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpLifecycleResponsibility::test_a0_tower_service_starts_audiopump PASSED [ 18%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpLifecycleResponsibility::test_a0_audiopump_runs_continuously PASSED [ 18%]
tower/tests/contracts/test_tower_audiopump.py::TestAudioPumpLifecycleResponsibility::test_a0_system_mp3_output_depends_on_audiopump PASSED [ 19%]
tower/tests/contracts/test_tower_broadcast_grade.py::TestBroadcastGradeCoreInvariants::test_bg1_no_dead_air_mp3_layer PASSED [ 19%]
tower/tests/contracts/test_tower_broadcast_grade.py::TestBroadcastGradeCoreInvariants::test_bg2_no_hard_dependence_on_pcm PASSED [ 19%]
tower/tests/contracts/test_tower_broadcast_grade.py::TestBroadcastGradeCoreInvariants::test_bg3_predictable_audio_state_machine PASSED [ 20%]
tower/tests/contracts/test_tower_broadcast_grade.py::TestBroadcastGradeStartupIdle::test_bg4_cold_start_no_pcm PASSED [ 20%]
tower/tests/contracts/test_tower_broadcast_grade.py::TestBroadcastGradeStartupIdle::test_bg7_long_term_idle_stability PASSED [ 20%]
tower/tests/contracts/test_tower_broadcast_grade.py::TestBroadcastGradePCMDetection::test_bg8_pcm_validity_threshold PASSED [ 20%]
tower/tests/contracts/test_tower_broadcast_grade.py::TestBroadcastGradePCMDetection::test_bg10_click_pop_minimization PASSED [ 21%]
tower/tests/contracts/test_tower_broadcast_grade.py::TestBroadcastGradePCMDetection::test_bg11_loss_detection PASSED [ 21%]
tower/tests/contracts/test_tower_broadcast_grade.py::TestBroadcastGradeEncoderLiveness::test_bg13_first_frame_source_agnostic PASSED [ 21%]
tower/tests/contracts/test_tower_broadcast_grade.py::TestBroadcastGradeEncoderLiveness::test_bg14_stall_semantics PASSED [ 22%]
tower/tests/contracts/test_tower_broadcast_grade.py::TestBroadcastGradeEncoderLiveness::test_bg15_stall_recovery PASSED [ 22%]
tower/tests/contracts/test_tower_broadcast_grade.py::TestBroadcastGradeRestartBehavior::test_bg16_buffer_preservation_across_restart PASSED [ 22%]
tower/tests/contracts/test_tower_broadcast_grade.py::TestBroadcastGradeRestartBehavior::test_bg17_automatic_fallback_resumption PASSED [ 22%]
tower/tests/contracts/test_tower_broadcast_grade.py::TestBroadcastGradeProductionTestBehavior::test_bg18_offline_test_mode PASSED [ 23%]
tower/tests/contracts/test_tower_broadcast_grade.py::TestBroadcastGradeProductionTestBehavior::test_bg19_no_tone_in_tests_by_default PASSED [ 23%]
tower/tests/contracts/test_tower_broadcast_grade.py::TestBroadcastGradeSelfHealing::test_bg22_self_healing_after_max_restarts PASSED [ 23%]
tower/tests/contracts/test_tower_broadcast_grade.py::TestBroadcastGradeObservability::test_bg26_http_status_endpoint PASSED [ 24%]
tower/tests/contracts/test_tower_encoder_buffers.py::TestFrameRingBuffer::test_push_pop_fifo PASSED [ 24%]
tower/tests/contracts/test_tower_encoder_buffers.py::TestFrameRingBuffer::test_overflow_drops_oldest PASSED [ 24%]
tower/tests/contracts/test_tower_encoder_buffers.py::TestFrameRingBuffer::test_len_updates_correctly PASSED [ 24%]
tower/tests/contracts/test_tower_encoder_buffers.py::TestFrameRingBuffer::test_no_blocking_behavior PASSED [ 25%]
tower/tests/contracts/test_tower_encoder_buffers.py::TestFrameRingBuffer::test_handles_thousands_of_operations PASSED [ 25%]
tower/tests/contracts/test_tower_encoder_buffers.py::TestFrameRingBuffer::test_thread_safety_smoke PASSED [ 25%]
tower/tests/contracts/test_tower_encoder_buffers.py::TestFrameRingBuffer::test_capacity_property PASSED [ 26%]
tower/tests/contracts/test_tower_encoder_buffers.py::TestFrameRingBuffer::test_empty_frame_rejected PASSED [ 26%]
tower/tests/contracts/test_tower_encoder_buffers.py::TestFrameRingBuffer::test_zero_capacity_rejected PASSED [ 26%]
tower/tests/contracts/test_tower_encoder_drain_thread.py::TestEncoderOutputDrainThread::test_pushes_frames_into_mp3_buffer PASSED [ 26%]
tower/tests/contracts/test_tower_encoder_drain_thread.py::TestEncoderOutputDrainThread::test_detects_stall_and_triggers_restart PASSED [ 27%]
tower/tests/contracts/test_tower_encoder_drain_thread.py::TestEncoderOutputDrainThread::test_no_blocking_behavior PASSED [ 27%]
tower/tests/contracts/test_tower_encoder_drain_thread.py::TestEncoderOutputDrainThread::test_thread_exits_cleanly_on_stop PASSED [ 27%]
tower/tests/contracts/test_tower_encoder_drain_thread.py::TestEncoderOutputDrainThread::test_handles_eof_gracefully PASSED [ 28%]
tower/tests/contracts/test_tower_encoder_drain_thread.py::TestEncoderOutputDrainThread::test_handles_select_errors PASSED [ 28%]
tower/tests/contracts/test_tower_encoder_drain_thread.py::TestEncoderOutputDrainThread::test_reads_in_chunks PASSED [ 28%]
tower/tests/contracts/test_tower_encoder_drain_thread.py::TestEncoderOutputDrainThread::test_partial_chunks_accumulate_until_full_frame PASSED [ 28%]
tower/tests/contracts/test_tower_encoder_drain_thread.py::TestEncoderOutputDrainThread::test_feed_yields_frames_incrementally PASSED [ 29%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_m1_encoder_manager_owns_supervisor PASSED [ 29%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_m2_never_exposes_supervisor PASSED [ 29%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_m3_public_interface_limited PASSED [ 30%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_m4_internally_maintains_buffers PASSED [ 30%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_m5_supervisor_created_in_init PASSED [ 30%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_m6_supervisor_lifecycle_encapsulated PASSED [ 30%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_starts_ffmpeg_process PASSED [ 31%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_state_transitions_to_running PASSED [ 31%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_m12_state_tracks_supervisor_resolves_as_operational_modes PASSED [ 31%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_m8_write_pcm_forwards_to_supervisor PASSED [ 32%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_m8_write_pcm_non_blocking PASSED [ 32%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_m9_pcm_frames_written_directly PASSED [ 32%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_write_pcm_handles_broken_pipe_non_blocking PASSED [ 32%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_write_pcm_multiple_calls_after_broken_pipe PASSED [ 33%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_can_stop_cleanly_without_zombie_ffmpeg PASSED [ 33%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_restart_does_not_clear_mp3_buffer PASSED [ 33%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_restart_triggers_after_async_call PASSED [ 34%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_get_frame_returns_silence_when_empty PASSED [ 34%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_get_frame_returns_frame_when_available PASSED [ 34%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_get_frame_never_blocks PASSED [ 34%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_m10_broadcast_grade_never_returns_none PASSED [ 35%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_m10_o1_cold_start_none_policy PASSED [ 35%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManager::test_max_restarts_enters_failed_state PASSED [ 35%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManagerOperationalModes::test_m14_translates_supervisor_state_to_operational_modes PASSED [ 36%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManagerOperationalModes::test_m15_get_frame_applies_source_selection_rules PASSED [ 36%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManagerOperationalModes::test_m16_write_pcm_only_during_live_input PASSED [ 36%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManagerOperationalModes::test_m16a_program_admission_pcm_validity_threshold PASSED [ 36%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManagerOperationalModes::test_m17_offline_test_mode_bypasses_supervisor PASSED [ 37%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManagerOperationalModes::test_m18_no_raw_supervisor_state_exposure PASSED [ 37%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManagerPCMFallback::test_m19_booting_injects_pcm_fallback PASSED [ 37%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManagerPCMFallback::test_m20_silence_first_then_optional_tone_after_grace PASSED [ 38%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManagerPCMFallback::test_m23_fallback_stream_is_continuous_no_stalls PASSED [ 38%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManagerPCMFallback::test_m24_real_pcm_arrival_stops_fallback PASSED [ 38%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManagerPCMFallback::test_m24a_offline_test_mode_exempts_fallback PASSED [ 38%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManagerPCMFallback::test_m11_fallback_on_demand_no_timing_loop PASSED [ 39%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManagerPCMFallback::test_m19a_fallback_controller_activation PASSED [ 39%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManagerPCMFallback::test_no_pcm_generation_outside_audiopump PASSED [ 39%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManagerPCMFallback::test_m25_no_fallback_thread PASSED [ 40%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManagerPCMFallback::test_m19l_fallback_reactivation_after_restart PASSED [ 40%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManagerPCMFallback::test_m19f_fallback_injection_hooks PASSED [ 40%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManagerPCMFallback::test_m19g_get_fallback_frame PASSED [ 40%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManagerPCMFallback::test_m19j_offline_test_mode_exceptions PASSED [ 41%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManagerPCMFallback::test_m19h_m19i_continuous_fallback_via_audiopump PASSED [ 41%]
tower/tests/contracts/test_tower_encoder_manager.py::TestPCMAdmissionAndProgramMode::test_m16a_threshold_enforcement_in_next_frame PASSED [ 41%]
tower/tests/contracts/test_tower_encoder_manager.py::TestPCMAdmissionAndProgramMode::test_m16a_single_stray_frame_no_admission PASSED [ 42%]
tower/tests/contracts/test_tower_encoder_manager.py::TestPCMAdmissionAndProgramMode::test_m16a_after_threshold_write_pcm_every_tick PASSED [ 42%]
tower/tests/contracts/test_tower_encoder_manager.py::TestPCMAdmissionAndProgramMode::test_m16a_pcm_none_after_threshold_triggers_loss_detection PASSED [ 42%]
tower/tests/contracts/test_tower_encoder_manager.py::TestPCMAdmissionAndProgramMode::test_m24_fallback_stops_after_program_admission PASSED [ 42%]
tower/tests/contracts/test_tower_encoder_manager.py::TestPCMAdmissionAndProgramMode::test_m16a_continuous_threshold_requirement PASSED [ 43%]
tower/tests/contracts/test_tower_encoder_manager.py::TestPCMAdmissionAndProgramMode::test_no_pcm_generation_outside_audiopump_unified PASSED [ 43%]
tower/tests/contracts/test_tower_encoder_manager.py::TestPCMAdmissionAndProgramMode::test_m16a_m24_end_to_end_program_lifecycle PASSED [ 43%]
tower/tests/contracts/test_tower_encoder_manager.py::TestContinuousSilenceDuringBoot::test_supervisor_continuous_silence_until_pcm_available FAILED [ 44%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManagerGracePeriod::test_m_grace1_uses_monotonic_clock PASSED [ 44%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManagerGracePeriod::test_m_grace2_silence_frame_precomputed PASSED [ 44%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManagerGracePeriod::test_m_grace3_exact_grace_second_boundary PASSED [ 44%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManagerGracePeriod::test_m_grace4_grace_resets_on_pcm_return PASSED [ 45%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManagerSourceSelection::test_m6_pcm_available_returns_pcm PASSED [ 45%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManagerSourceSelection::test_m7_1_no_pcm_within_grace_returns_silence PASSED [ 45%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManagerSourceSelection::test_m7_2_no_pcm_after_grace_calls_fallback_provider PASSED [ 46%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManagerSourceSelection::test_m16_fallback_provider_interaction PASSED [ 46%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManagerNextFrame::test_m1_m2_m3_next_frame_returns_exactly_one_frame PASSED [ 46%]
tower/tests/contracts/test_tower_encoder_manager.py::TestEncoderManagerNextFrame::test_m3_never_returns_none PASSED [ 46%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderOperationalModes::test_o1_cold_start_mode PASSED [ 47%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderOperationalModes::test_o2_booting_mode_instant_playback PASSED [ 47%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderOperationalModes::test_o2_2_frame_boundary_alignment PASSED [ 47%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderOperationalModes::test_o6_offline_test_mode PASSED [ 48%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderModeTransitions::test_o8_mode_transitions_atomic_and_thread_safe PASSED [ 48%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderModeTransitions::test_o9_continuous_output_during_transitions PASSED [ 48%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderModeTransitions::test_o11_clients_no_disconnections_during_transitions PASSED [ 48%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderOutputGuarantees::test_o12_continuous_output_requirement PASSED [ 49%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderOutputGuarantees::test_o13_frame_source_priority PASSED [ 49%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderOutputGuarantees::test_o14_mode_aware_frame_selection PASSED [ 49%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderTestingModeRequirements::test_o15_1_unit_tests_must_use_offline_test_mode PASSED [ 50%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderTestingModeRequirements::test_o15_6_tests_fail_if_ffmpeg_launched_without_explicit_request PASSED [ 50%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderTestingModeRequirements::test_o16_1_env_var_activates_offline_test_mode PASSED [ 50%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderTestingModeRequirements::test_o16_3_offline_test_mode_no_supervisor_creation PASSED [ 51%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderBroadcastGradeRequirements::test_o17_never_stall_transmission PASSED [ 51%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderBroadcastGradeRequirements::test_o18_graceful_degradation PASSED [ 51%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderBroadcastGradeRequirements::test_o20_output_cadence_guarantee PASSED [ 51%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderBroadcastGradeRequirements::test_o21_seamless_recovery PASSED [ 52%]
tower/tests/contracts/test_tower_encoder_operation_modes.py::TestEncoderBroadcastGradeRequirements::test_o22_mode_telemetry PASSED [ 52%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorCoreInvariants::test_f1_always_returns_valid_frame PASSED [ 52%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorCoreInvariants::test_f2_format_guarantees PASSED [ 53%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorCoreInvariants::test_f3_always_has_fallback_source PASSED [ 53%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorSourceSelection::test_f4_source_priority_order PASSED [ 53%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorSourceSelection::test_f5_falls_through_to_tone PASSED [ 53%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorSourceSelection::test_f6_falls_through_to_silence PASSED [ 54%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorSourceSelection::test_f7_priority_deterministic PASSED [ 54%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorToneGenerator::test_f10_440hz_tone PASSED [ 54%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorToneGenerator::test_f11_phase_accumulator PASSED [ 55%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorToneGenerator::test_f12_tone_selected_when_no_file PASSED [ 55%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorToneGenerator::test_f13_falls_to_silence_on_error PASSED [ 55%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorSilenceSource::test_f14_continuous_zeros PASSED [ 55%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorSilenceSource::test_f15_always_available PASSED [ 56%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorSilenceSource::test_f16_selected_on_tone_failure PASSED [ 56%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorSilenceSource::test_f17_never_fails PASSED [ 56%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorInterface::test_f18_constructor_no_parameters PASSED [ 57%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorInterface::test_f19_get_frame_method PASSED [ 57%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorInterface::test_f20_idempotent PASSED [ 57%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorFormatGuarantees::test_f21_exactly_4608_bytes PASSED [ 57%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorFormatGuarantees::test_f22_canonical_format PASSED [ 58%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackGeneratorFormatGuarantees::test_f23_frame_boundaries_preserved PASSED [ 58%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackProviderZeroLatency::test_fp2_2_zero_latency_requirement PASSED [ 58%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackProviderZeroLatency::test_c4_3_5_tone_zero_latency PASSED [ 59%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackProviderZeroLatency::test_c4_4_4_silence_zero_latency PASSED [ 59%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackProviderTonePreference::test_fp3_2_tone_is_preferred_fallback PASSED [ 59%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackProviderTonePreference::test_fp3_3_silence_only_when_tone_unavailable PASSED [ 59%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackProviderTonePreference::test_fp5_1_falls_to_tone_on_file_error PASSED [ 60%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackProviderTonePreference::test_fp5_2_silence_only_as_last_resort PASSED [ 60%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackProviderTonePreference::test_c4_3_tone_preferred_over_silence PASSED [ 60%]
tower/tests/contracts/test_tower_fallback_generator.py::TestFallbackProviderTonePreference::test_c4_4_silence_last_resort_only PASSED [ 61%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorLiveness::test_f5_process_starts_successfully PASSED [ 61%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorLiveness::test_s6_stderr_capture_thread_started PASSED [ 61%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorLiveness::test_s6a_booting_state_transition PASSED [ 61%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorLiveness::test_s7_first_frame_soft_target_500ms PASSED [ 62%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorLiveness::test_s7a_hard_startup_timeout PASSED [ 62%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorLiveness::test_s7b_first_frame_timer_uses_wall_clock_time PASSED [ 62%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorLiveness::test_f3_f4_never_generates_silence PASSED [ 63%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorLiveness::test_s8_continuous_frames_within_interval PASSED [ 63%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorFailureDetection::test_f6_process_failure_detection PASSED [ 63%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorFailureDetection::test_s10_startup_timeout_detection PASSED [ 63%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorFailureDetection::test_s11_stall_detection PASSED [ 64%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorFailureDetection::test_s12_frame_interval_violation PASSED [ 64%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorRestartBehavior::test_s13_1_logs_failure_reason PASSED [ 64%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorRestartBehavior::test_s13_2_transitions_to_restarting PASSED [ 65%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorRestartBehavior::test_s13_3_preserves_mp3_buffer PASSED [ 65%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorRestartBehavior::test_s13_3b_mp3_output_remains_continuous_during_restart PASSED [ 65%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorRestartBehavior::test_s13_3c_frame_delivery_continues_from_buffer_during_restart PASSED [ 65%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorRestartBehavior::test_s13_4_follows_backoff_schedule PASSED [ 66%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorRestartBehavior::test_s13_5_max_restarts_enforced PASSED [ 66%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorRestartBehavior::test_s13_6_enters_failed_state PASSED [ 66%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorRestartBehavior::test_s13_8_restart_goes_through_booting_state PASSED [ 67%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorRestartBehavior::test_s13_9_immediate_exit_during_restart_respects_s13_8a PASSED [ 67%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorStderrCapture::test_s14_1_stderr_thread_starts_immediately PASSED [ 67%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorStderrCapture::test_s14_2_stderr_drain_thread_started PASSED [ 67%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorStderrCapture::test_s14_3_logs_with_ffmpeg_prefix PASSED [ 68%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorStderrCapture::test_s14_4_daemon_thread PASSED [ 68%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorStderrCapture::test_s14_5_continues_until_stderr_closes PASSED [ 68%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorStderrCapture::test_s14_7_stdout_drain_thread_ordering_and_non_blocking_termination PASSED [ 69%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorFrameTiming::test_s15_frame_interval_calculation PASSED [ 69%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorFrameTiming::test_s16_tolerance_window PASSED [ 69%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorFrameTiming::test_s17_tracks_last_frame_timestamp PASSED [ 69%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorFrameTiming::test_s18_detects_interval_violation PASSED [ 70%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorStartupSequence::test_s19_startup_sequence_order PASSED [ 70%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorStartupSequence::test_s19_13_start_completion_guarantee_returns_booting PASSED [ 70%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorStartupSequence::test_s19_14_deferred_failure_handling_during_starting PASSED [ 71%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorErrorLogging::test_s20_1_logs_process_exit PASSED [ 71%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorErrorLogging::test_s20_1_logs_encoder_live_on_running_transition PASSED [ 71%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorErrorLogging::test_s20_2_logs_slow_startup_warn PASSED [ 71%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorErrorLogging::test_s20_3_logs_startup_timeout PASSED [ 72%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorErrorLogging::test_s20_3_logs_stall PASSED [ 72%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorErrorLogging::test_s21_reads_stderr_on_exit PASSED [ 72%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorErrorLogging::test_s21_2_non_string_stderr_exit_log_hygiene PASSED [ 73%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorPhase9StderrDrain::test_phase9_s14_2_stderr_drain_thread_started PASSED [ 73%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorPhase9StderrDrain::test_phase9_s14_3_stderr_drain_uses_readline_loop PASSED [ 73%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorPhase9StderrDrain::test_phase9_s14_4_stderr_logged_with_ffmpeg_prefix PASSED [ 73%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorPhase9StderrDrain::test_phase9_s21_reads_stderr_on_exit PASSED [ 74%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorPhase9StderrDrain::test_phase9_s19_4_drain_threads_started PASSED [ 74%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorPhase10RecentUpdates::test_phase10_s19_11_frame_size_in_default_command PASSED [ 74%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorPhase10RecentUpdates::test_phase10_s19_11_build_ffmpeg_cmd_ensures_frame_size PASSED [ 75%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorPhase10RecentUpdates::test_phase10_s21_1_exit_code_logged_on_eof PASSED [ 75%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorPhase10RecentUpdates::test_phase10_s21_1_exit_code_logged_on_stdin_broken PASSED [ 75%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorPhase10RecentUpdates::test_phase10_s21_1_stderr_captured_on_failure PASSED [ 75%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorPhase10RecentUpdates::test_phase10_s7_1_pcm_input_during_booting PASSED [ 76%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorPhase10RecentUpdates::test_phase10_s7_1a_default_booting_input_is_silence PASSED [ 76%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorPhase10RecentUpdates::test_phase10_s7_1b_first_mp3_frame_from_any_pcm_source PASSED [ 76%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorPhase10RecentUpdates::test_phase10_s7_1c_tone_via_operational_modes_only PASSED [ 77%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorPhase10RecentUpdates::test_s13_7_thread_safety_no_deadlock_on_concurrent_failures PASSED [ 77%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorOperationalModeMapping::test_s27_supervisor_state_maps_to_operational_modes PASSED [ 77%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorOperationalModeMapping::test_s22a_supervisor_must_not_know_about_noise_silence_generation PASSED [ 77%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorOperationalModeMapping::test_s28_supervisor_does_not_decide_fallback PASSED [ 78%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorOperationalModeMapping::test_s29_restart_enters_booting_not_running PASSED [ 78%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorOperationalModeMapping::test_s30_continuously_emits_frames_even_with_silence PASSED [ 78%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorWritePCM::test_f7_write_pcm_accepts_frames PASSED [ 79%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorWritePCM::test_f8_write_pcm_frame_size PASSED [ 79%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorSelfHealing::test_f_heal1_restarts_after_crash PASSED [ 79%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorSelfHealing::test_f_heal2_restart_rate_limiting PASSED [ 79%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorSelfHealing::test_f_heal3_health_does_not_block PASSED [ 80%]
tower/tests/contracts/test_tower_ffmpeg_supervisor.py::TestFFmpegSupervisorSelfHealing::test_f_heal4_em_continues_during_restart PASSED [ 80%]
tower/tests/contracts/test_tower_ffmpeg_supervisor_startup.py::TestSupervisorStartupInitialPCM::test_supervisor_starts_ffmpeg_and_accepts_pcm FAILED [ 80%]
tower/tests/contracts/test_tower_frame_ring_buffer.py::TestFrameRingBufferCoreInvariants::test_b1_complete_frames_only PASSED [ 81%]
tower/tests/contracts/test_tower_frame_ring_buffer.py::TestFrameRingBufferCoreInvariants::test_b2_bounded PASSED [ 81%]
tower/tests/contracts/test_tower_frame_ring_buffer.py::TestFrameRingBufferCoreInvariants::test_b3_thread_safe PASSED [ 81%]
tower/tests/contracts/test_tower_frame_ring_buffer.py::TestFrameRingBufferCoreInvariants::test_b4_non_blocking PASSED [ 81%]
tower/tests/contracts/test_tower_frame_ring_buffer.py::TestFrameRingBufferThreadSafety::test_b5_multi_producer_multi_consumer PASSED [ 82%]
tower/tests/contracts/test_tower_frame_ring_buffer.py::TestFrameRingBufferThreadSafety::test_b6_rlock_protection PASSED [ 82%]
tower/tests/contracts/test_tower_frame_ring_buffer.py::TestFrameRingBufferThreadSafety::test_b7_no_deadlock PASSED [ 82%]
tower/tests/contracts/test_tower_frame_ring_buffer.py::TestFrameRingBufferThreadSafety::test_b8_explicit_thread_safety PASSED [ 83%]
tower/tests/contracts/test_tower_frame_ring_buffer.py::TestFrameRingBufferOverflow::test_b9_mp3_buffer_drops_oldest PASSED [ 83%]
tower/tests/contracts/test_tower_frame_ring_buffer.py::TestFrameRingBufferOverflow::test_b10_never_blocks_or_raises PASSED [ 83%]
tower/tests/contracts/test_tower_frame_ring_buffer.py::TestFrameRingBufferOverflow::test_b11_overflow_counter_tracked PASSED [ 83%]
tower/tests/contracts/test_tower_frame_ring_buffer.py::TestFrameRingBufferUnderflow::test_b12_returns_none_immediately PASSED [ 84%]
tower/tests/contracts/test_tower_frame_ring_buffer.py::TestFrameRingBufferUnderflow::test_b12_with_timeout_waits PASSED [ 84%]
tower/tests/contracts/test_tower_frame_ring_buffer.py::TestFrameRingBufferUnderflow::test_b13_underflow_expected PASSED [ 84%]
tower/tests/contracts/test_tower_frame_ring_buffer.py::TestFrameRingBufferInterface::test_b14_constructor_capacity PASSED [ 85%]
tower/tests/contracts/test_tower_frame_ring_buffer.py::TestFrameRingBufferInterface::test_b15_push_frame_method PASSED [ 85%]
tower/tests/contracts/test_tower_frame_ring_buffer.py::TestFrameRingBufferInterface::test_b15_pop_frame_method PASSED [ 85%]
tower/tests/contracts/test_tower_frame_ring_buffer.py::TestFrameRingBufferInterface::test_b15_clear_method PASSED [ 85%]
tower/tests/contracts/test_tower_frame_ring_buffer.py::TestFrameRingBufferInterface::test_b15_stats_method PASSED [ 86%]
tower/tests/contracts/test_tower_frame_ring_buffer.py::TestFrameRingBufferInterface::test_b16_o1_time_complexity PASSED [ 86%]
tower/tests/contracts/test_tower_frame_ring_buffer.py::TestFrameRingBufferFrameSemantics::test_b17_arbitrary_bytes PASSED [ 86%]
tower/tests/contracts/test_tower_frame_ring_buffer.py::TestFrameRingBufferFrameSemantics::test_b18_no_format_validation PASSED [ 87%]
tower/tests/contracts/test_tower_frame_ring_buffer.py::TestFrameRingBufferFrameSemantics::test_b19_frame_boundaries_preserved PASSED [ 87%]
tower/tests/contracts/test_tower_frame_ring_buffer.py::TestFrameRingBufferStatistics::test_b20_stats_returns_count_capacity_overflow PASSED [ 87%]
tower/tests/contracts/test_tower_frame_ring_buffer.py::TestFrameRingBufferStatistics::test_b21_stats_thread_safe PASSED [ 87%]
tower/tests/contracts/test_tower_runtime.py::TestTowerRuntimeAlwaysOnTransmitter::test_t1_exposes_get_stream_endpoint PASSED [ 88%]
tower/tests/contracts/test_tower_runtime.py::TestTowerRuntimeAlwaysOnTransmitter::test_t2_always_returns_valid_mp3_bytes PASSED [ 88%]
tower/tests/contracts/test_tower_runtime.py::TestTowerRuntimeAlwaysOnTransmitter::test_t3_continues_streaming_if_station_down PASSED [ 88%]
tower/tests/contracts/test_tower_runtime.py::TestTowerRuntimeLiveVsFallback::test_t4_streams_live_when_station_feeding PASSED [ 89%]
tower/tests/contracts/test_tower_runtime.py::TestTowerRuntimeLiveVsFallback::test_t5_1_detects_absence_within_timeout PASSED [ 89%]
tower/tests/contracts/test_tower_runtime.py::TestTowerRuntimeLiveVsFallback::test_t5_2_uses_silence_during_grace PASSED [ 89%]
tower/tests/contracts/test_tower_runtime.py::TestTowerRuntimeLiveVsFallback::test_t5_3_switches_to_fallback_after_grace PASSED [ 89%]
tower/tests/contracts/test_tower_runtime.py::TestTowerRuntimeLiveVsFallback::test_t6_transitions_do_not_disconnect_clients PASSED [ 90%]
tower/tests/contracts/test_tower_runtime.py::TestTowerRuntimeStationInput::test_t7_reads_from_bounded_buffer PASSED [ 90%]
tower/tests/contracts/test_tower_runtime.py::TestTowerRuntimeStationInput::test_t8_overflow_drops_frames_not_blocks PASSED [ 90%]
tower/tests/contracts/test_tower_runtime.py::TestTowerRuntimeStationInput::test_t9_sole_metronome_21_333ms PASSED [ 91%]
tower/tests/contracts/test_tower_runtime.py::TestTowerRuntimeClientHandling::test_t10_slow_clients_never_block_broadcast PASSED [ 91%]
tower/tests/contracts/test_tower_runtime.py::TestTowerRuntimeClientHandling::test_t11_slow_clients_dropped_after_timeout PASSED [ 91%]
tower/tests/contracts/test_tower_runtime.py::TestTowerRuntimeClientHandling::test_t12_all_clients_receive_same_data PASSED [ 91%]
tower/tests/contracts/test_tower_runtime.py::TestTowerRuntimeLifecycle::test_t13_clean_shutdown_within_timeout PASSED [ 92%]
tower/tests/contracts/test_tower_runtime.py::TestTowerRuntimeLifecycle::test_t14_can_start_when_station_offline PASSED [ 92%]
tower/tests/contracts/test_tower_service_integration.py::TestTowerServiceComponentWiring::test_i1_tower_service_constructs_components PASSED [ 92%]
tower/tests/contracts/test_tower_service_integration.py::TestTowerServiceComponentWiring::test_i2_startup_sequence_follows_order PASSED [ 93%]
tower/tests/contracts/test_tower_service_integration.py::TestTowerServiceComponentWiring::test_i3_no_contract_violations PASSED [ 93%]
tower/tests/contracts/test_tower_service_integration.py::TestTowerServiceConstructionOrder::test_i4_buffers_created_first PASSED [ 93%]
tower/tests/contracts/test_tower_service_integration.py::TestTowerServiceConstructionOrder::test_i5_components_constructed_in_order PASSED [ 93%]
tower/tests/contracts/test_tower_service_integration.py::TestTowerServiceConstructionOrder::test_i5_1_no_component_references_unconstructed PASSED [ 94%]
tower/tests/contracts/test_tower_service_integration.py::TestTowerServiceConstructionOrder::test_i5_2_all_components_constructed_before_threads PASSED [ 94%]
tower/tests/contracts/test_tower_service_integration.py::TestTowerServiceConstructionOrder::test_i6_supervisor_not_in_tower_service PASSED [ 94%]
tower/tests/contracts/test_tower_service_integration.py::TestTowerServiceStartupSequence::test_i7_startup_order_critical PASSED [ 95%]
tower/tests/contracts/test_tower_service_integration.py::TestTowerServiceStartupSequence::test_i8_startup_ensures_dependencies PASSED [ 95%]
tower/tests/contracts/test_tower_service_integration.py::TestTowerServiceStartupSequence::test_i26_no_circular_startup_dependencies PASSED [ 95%]
tower/tests/contracts/test_tower_service_integration.py::TestTowerServiceInterfaceCompliance::test_i9_audiopump_only_calls_encoder_manager PASSED [ 95%]
tower/tests/contracts/test_tower_service_integration.py::TestTowerServiceInterfaceCompliance::test_i10_broadcast_loop_only_calls_get_frame PASSED [ 96%]
tower/tests/contracts/test_tower_service_integration.py::TestTowerServiceInterfaceCompliance::test_i11_supervisor_encapsulated PASSED [ 96%]
tower/tests/contracts/test_tower_service_integration.py::TestTowerServiceInterfaceCompliance::test_i23_broadcast_clock_driven_not_frame_availability PASSED [ 96%]
tower/tests/contracts/test_tower_service_integration.py::TestTowerServiceInterfaceCompliance::test_i24_encoder_restart_does_not_break_broadcast PASSED [ 97%]
tower/tests/contracts/test_tower_service_integration.py::TestTowerServiceShutdown::test_i12_shutdown_order_reverse PASSED [ 97%]
tower/tests/contracts/test_tower_service_integration.py::TestTowerServiceAudioPumpLifecycle::test_a0_tower_service_creates_audiopump PASSED [ 97%]
tower/tests/contracts/test_tower_service_integration.py::TestTowerServiceAudioPumpLifecycle::test_a0_tower_service_starts_audiopump PASSED [ 97%]
tower/tests/contracts/test_tower_service_integration.py::TestTowerServiceAudioPumpLifecycle::test_a0_audiopump_provides_continuous_pcm PASSED [ 98%]
tower/tests/contracts/test_tower_service_integration.py::TestTowerServiceOperationalModes::test_i18_tower_service_exposes_mode_selection PASSED [ 98%]
tower/tests/contracts/test_tower_service_integration.py::TestTowerServiceOperationalModes::test_i19_offline_test_mode_activation PASSED [ 98%]
tower/tests/contracts/test_tower_service_integration.py::TestTowerServiceOperationalModes::test_i20_tests_cannot_launch_ffmpeg_unless_explicit PASSED [ 99%]
tower/tests/contracts/test_tower_service_integration.py::TestTowerServiceOperationalModes::test_i21_full_startup_follows_mode_transitions PASSED [ 99%]
tower/tests/contracts/test_tower_service_integration.py::TestTowerServiceOperationalModes::test_i22_tower_service_root_owner_of_operational_mode PASSED [ 99%]
tower/tests/contracts/test_tower_service_integration.py::TestTowerServiceTestIsolation::test_i25_tests_fail_loudly_if_ffmpeg_starts_in_non_integration_tests PASSED [100%]

=================================== FAILURES ===================================
_________ TestSupervisorBootPCMFlow.test_pcm_is_forwarded_during_boot __________
tower/tests/contracts/test_supervisor_boot_pcm_flow.py:165: in test_pcm_is_forwarded_during_boot
    assert pcm_frames_forwarded >= num_frames, \
E   AssertionError: Contract violation [F7, F8]: PCM frames must continue flowing during BOOTING. Expected at least 5 frames to be forwarded via write_pcm(), but only 0 were forwarded. Total writes to stdin: 112. Frames written: [4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608]
E   assert 0 >= 5
------------------------------ Captured log call -------------------------------
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:945 FFMPEG_SUPERVISOR: ffmpeg started
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:953 Started ffmpeg PID=12345
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:1158 Encoder stdout drain thread running
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:2104 Encoder stdout drain thread started
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:2113 Encoder stderr drain thread started
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:2125 Encoder PCM writer thread started (restart)
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:647 FFMPEG_SUPERVISOR: Boot priming burst complete [S7.3] (83 frames in 0.004ms)
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:2176 Encoder restarted successfully (in BOOTING state, waiting for first frame per [S13.8])
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:1158 Encoder stdout drain thread running
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:2104 Encoder stdout drain thread started
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:2113 Encoder stderr drain thread started
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:2125 Encoder PCM writer thread started (restart)
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:647 FFMPEG_SUPERVISOR: Boot priming burst complete [S7.3] (83 frames in 0.003ms)
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:2176 Encoder restarted successfully (in BOOTING state, waiting for first frame per [S13.8])
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:1158 Encoder stdout drain thread running
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:300 Encoder stdout drain thread started
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:311 Encoder stderr drain thread started
WARNING  tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:1270 Encoder stdout EOF - encoder process ended (exit code: None)
ERROR    tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:1648 🔥 FFmpeg stdout EOF (exit code: unknown - process may have been killed or terminated abnormally)
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:647 FFMPEG_SUPERVISOR: Boot priming burst complete [S7.3] (83 frames in 32.729ms)
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:336 Encoder PCM writer thread started
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:1749 FFMPEG_SUPERVISOR: entering _enter_restarting_or_failed (failure_type=eof, state=BOOTING, first_frame_received=False, startup_complete=True)
ERROR    tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:1782 🔥 FFmpeg stdout EOF (exit code: unknown - process may have been killed or terminated abnormally)
ERROR    tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:1819 FFMPEG_SUPERVISOR: last_stderr at BOOTING→RESTARTING: <empty>
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:2046 Restarting encoder (attempt 1/5) after 1.0s delay
WARNING  tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:1542 ⚠ FFmpeg slow startup: first frame not received within 500ms
WARNING  tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:1542 ⚠ FFmpeg slow startup: first frame not received within 500ms
WARNING  tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:1542 ⚠ FFmpeg slow startup: first frame not received within 500ms
---------------------------- Captured log teardown -----------------------------
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:379 Stopping FFmpegSupervisor...
WARNING  tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:468 Restart thread did not terminate within timeout
WARNING  tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:485 Background threads still running after shutdown: ['restart']
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:508 FFmpegSupervisor stopped
_ TestContinuousSilenceDuringBoot.test_supervisor_continuous_silence_until_pcm_available _
tower/tests/contracts/test_tower_encoder_manager.py:2288: in test_supervisor_continuous_silence_until_pcm_available
    assert sup.get_state() == SupervisorState.BOOTING, \
E   AssertionError: Supervisor should remain in BOOTING state when no MP3 frames received. Actual state: SupervisorState.RESTARTING
E   assert <SupervisorState.RESTARTING: 4> == <SupervisorState.BOOTING: 2>
E    +  where <SupervisorState.RESTARTING: 4> = get_state()
E    +    where get_state = <tower.encoder.ffmpeg_supervisor.FFmpegSupervisor object at 0x7fbf960b7090>.get_state
E    +  and   <SupervisorState.BOOTING: 2> = <enum 'SupervisorState'>.BOOTING
------------------------------ Captured log call -------------------------------
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:945 FFMPEG_SUPERVISOR: ffmpeg started
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:953 Started ffmpeg PID=12345
WARNING  tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:1367 🔥 FFmpeg frame interval violation: 48.8ms (expected ~24.0ms)
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:1158 Encoder stdout drain thread running
WARNING  tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:1207 Read error in drain thread: 
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:300 Encoder stdout drain thread started
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:311 Encoder stderr drain thread started
INFO     tower.fallback.generator:generator.py:73 FallbackGenerator initialized: 440.0Hz tone, 1152 samples/frame, 4608 bytes/frame
WARNING  tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:1270 Encoder stdout EOF - encoder process ended (exit code: None)
ERROR    tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:1648 🔥 FFmpeg stdout EOF (exit code: unknown - process may have been killed or terminated abnormally)
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:647 FFMPEG_SUPERVISOR: Boot priming burst complete [S7.3] (83 frames in 37.225ms)
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:336 Encoder PCM writer thread started
INFO     tower.encoder.encoder_manager:encoder_manager.py:439 EncoderManager started
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:1749 FFMPEG_SUPERVISOR: entering _enter_restarting_or_failed (failure_type=eof, state=BOOTING, first_frame_received=False, startup_complete=True)
ERROR    tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:1782 🔥 FFmpeg stdout EOF (exit code: unknown - process may have been killed or terminated abnormally)
ERROR    tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:1819 FFMPEG_SUPERVISOR: last_stderr at BOOTING→RESTARTING: <empty>
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:2046 Restarting encoder (attempt 1/5) after 1.0s delay
_ TestSupervisorStartupInitialPCM.test_supervisor_starts_ffmpeg_and_accepts_pcm _
tower/tests/contracts/test_tower_ffmpeg_supervisor_startup.py:161: in test_supervisor_starts_ffmpeg_and_accepts_pcm
    assert supervisor.get_state() == SupervisorState.BOOTING, \
E   AssertionError: Supervisor should remain in BOOTING state when no MP3 frames received. Actual state: SupervisorState.RESTARTING
E   assert <SupervisorState.RESTARTING: 4> == <SupervisorState.BOOTING: 2>
E    +  where <SupervisorState.RESTARTING: 4> = get_state()
E    +    where get_state = <tower.encoder.ffmpeg_supervisor.FFmpegSupervisor object at 0x7fbf3cbe3f50>.get_state
E    +  and   <SupervisorState.BOOTING: 2> = SupervisorState.BOOTING
------------------------------ Captured log call -------------------------------
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:945 FFMPEG_SUPERVISOR: ffmpeg started
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:953 Started ffmpeg PID=12345
ERROR    tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:1561 FFMPEG_SUPERVISOR: startup timeout fired, no MP3 produced
ERROR    tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:1566 🔥 FFmpeg did not produce first MP3 frame within 1500ms
ERROR    tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:1568 FFMPEG_SUPERVISOR: last_stderr at startup timeout: <empty>
WARNING  tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:1367 🔥 FFmpeg frame interval violation: 48.3ms (expected ~24.0ms)
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:1158 Encoder stdout drain thread running
WARNING  tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:1207 Read error in drain thread: 
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:300 Encoder stdout drain thread started
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:311 Encoder stderr drain thread started
WARNING  tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:1270 Encoder stdout EOF - encoder process ended (exit code: None)
ERROR    tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:1648 🔥 FFmpeg stdout EOF (exit code: unknown - process may have been killed or terminated abnormally)
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:647 FFMPEG_SUPERVISOR: Boot priming burst complete [S7.3] (83 frames in 40.503ms)
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:336 Encoder PCM writer thread started
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:1749 FFMPEG_SUPERVISOR: entering _enter_restarting_or_failed (failure_type=eof, state=BOOTING, first_frame_received=False, startup_complete=True)
ERROR    tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:1782 🔥 FFmpeg stdout EOF (exit code: unknown - process may have been killed or terminated abnormally)
ERROR    tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:1819 FFMPEG_SUPERVISOR: last_stderr at BOOTING→RESTARTING: <empty>
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:2046 Restarting encoder (attempt 1/5) after 1.0s delay
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:945 FFMPEG_SUPERVISOR: ffmpeg started
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:953 Started ffmpeg PID=171787
---------------------------- Captured log teardown -----------------------------
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:379 Stopping FFmpegSupervisor...
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:1380 MP3 output buffer: 10 frames
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:1380 MP3 output buffer: 10 frames
WARNING  tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:468 Restart thread did not terminate within timeout
WARNING  tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:485 Background threads still running after shutdown: ['restart']
INFO     tower.encoder.ffmpeg_supervisor:ffmpeg_supervisor.py:508 FFmpegSupervisor stopped
=========================== short test summary info ============================
FAILED tower/tests/contracts/test_supervisor_boot_pcm_flow.py::TestSupervisorBootPCMFlow::test_pcm_is_forwarded_during_boot - AssertionError: Contract violation [F7, F8]: PCM frames must continue flowing during BOOTING. Expected at least 5 frames to be forwarded via write_pcm(), but only 0 were forwarded. Total writes to stdin: 112. Frames written: [4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608, 4608]
assert 0 >= 5
FAILED tower/tests/contracts/test_tower_encoder_manager.py::TestContinuousSilenceDuringBoot::test_supervisor_continuous_silence_until_pcm_available - AssertionError: Supervisor should remain in BOOTING state when no MP3 frames received. Actual state: SupervisorState.RESTARTING
assert <SupervisorState.RESTARTING: 4> == <SupervisorState.BOOTING: 2>
 +  where <SupervisorState.RESTARTING: 4> = get_state()
 +    where get_state = <tower.encoder.ffmpeg_supervisor.FFmpegSupervisor object at 0x7fbf960b7090>.get_state
 +  and   <SupervisorState.BOOTING: 2> = <enum 'SupervisorState'>.BOOTING
FAILED tower/tests/contracts/test_tower_ffmpeg_supervisor_startup.py::TestSupervisorStartupInitialPCM::test_supervisor_starts_ffmpeg_and_accepts_pcm - AssertionError: Supervisor should remain in BOOTING state when no MP3 frames received. Actual state: SupervisorState.RESTARTING
assert <SupervisorState.RESTARTING: 4> == <SupervisorState.BOOTING: 2>
 +  where <SupervisorState.RESTARTING: 4> = get_state()
 +    where get_state = <tower.encoder.ffmpeg_supervisor.FFmpegSupervisor object at 0x7fbf3cbe3f50>.get_state
 +  and   <SupervisorState.BOOTING: 2> = SupervisorState.BOOTING
======================== 3 failed, 346 passed in 57.68s ========================

FFMPEG_SUPERVISOR: startup timeout fired, no MP3 produced
🔥 FFmpeg did not produce first MP3 frame within 1500ms
FFMPEG_SUPERVISOR: last_stderr at startup timeout: <empty>
🔥 FFmpeg frame interval violation: 1789.1ms (expected ~24.0ms)
🔥 FFmpeg frame interval violation: 1786.9ms (expected ~24.0ms)
🔥 FFmpeg frame interval violation: 1786.8ms (expected ~24.0ms)
🔥 FFmpeg frame interval violation: 1788.8ms (expected ~24.0ms)
🔥 FFmpeg frame interval violation: 1437.2ms (expected ~24.0ms)
🔥 FFmpeg frame interval violation: 1789.7ms (expected ~24.0ms)
🔥 FFmpeg frame interval violation: 1794.8ms (expected ~24.0ms)
🔥 FFmpeg frame interval violation: 1817.4ms (expected ~24.0ms)
🔥 FFmpeg frame interval violation: 771.7ms (expected ~24.0ms)
