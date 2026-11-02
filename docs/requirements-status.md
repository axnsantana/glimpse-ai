# Requirements status

Each requirement from the Software Requirements Specification (draft 0.1) for this MVP.

- **Done** means it is implemented and a test shows it. Tests named `e2e` drive real Chrome, and the rest run in `pytest`.
- **Partial** says what is missing.
- **Not done** means it is out of this MVP.

Claude Opus 5.5 has been run live. No other provider has, so anything marked "fake server" ran against the real SDK and a local server speaking the provider's wire format.

## Page capture

| ID | Priority | Status | Evidence or gap |
|---|---|---|---|
| CAP-1 | MUST | Done | `test_examples.py` reads every example, none annotated |
| CAP-2 | MUST | Done | `test_probe_reads_a_real_grid_filter_and_sort` (e2e), `test_table_reports_filter_sort_selection_and_hidden_columns` |
| CAP-3 | MUST | Done | `test_capture.py`, plus `ui.pyplot` line data and `ui.mermaid`, which were optional |
| CAP-4 | SHOULD | Done | `test_snapshot_is_built_when_the_user_asks_not_before` |
| CAP-5 | SHOULD, prov. | Done | `test_probe_reads_real_chart_zoom_and_legend` (e2e). Spike S1's formal bake-off against DOM and screenshots was not run |
| CAP-6 | SHOULD | Done | `[kind-id]` on each entry, or your own with `describe(id=)` |
| CAP-7 | MUST | Done | [visibility-policy.md](visibility-policy.md), `test_visibility_policy_*` |
| CAP-8 | MAY | Not done | Screenshots. Unreadable widgets say so instead |
| CAP-9 | SHOULD | Done | `serializer=`, `json_serializer` |

## Context size and budget

| ID | Priority | Status | Evidence or gap |
|---|---|---|---|
| CTX-1 | MUST | Done | `test_budget_holds_for_random_shapes`, and `test_live_budget_holds` against the real token counting endpoint. The budget uses an estimate unless `count_tokens=` is given |
| CTX-2 | MUST | Done | `test_large_table_is_a_summary_plus_a_visible_notice`, `tools.py` |
| CTX-3 | SHOULD | Done | `test_long_series_is_narrated_from_python_statistics` |
| CTX-4 | MUST | Done | `test_a_long_session_does_not_grow_without_limit` |
| CTX-5 | SHOULD | Done | Example 09, including `available` as a function |

## Assistant panel

| ID | Priority | Status | Evidence or gap |
|---|---|---|---|
| UI-1 | MUST | Done | Every example, and `test_quickstart_*` (e2e) |
| UI-2 | MUST | Done | `test_panel_makes_room_for_a_host_right_drawer` (e2e) |
| UI-3 | MUST | Done | `test_host_css_cannot_reach_the_panel_and_panel_css_cannot_reach_the_host` (e2e). While open with `push=True`, a small stylesheet moves the page's right edge. `push=False` removes it |
| UI-4 | MUST | Done | `test_stop_button_cancels_the_stream_and_closes_the_engine` (e2e), `test_progress_heartbeat_during_silence` |
| UI-5 | SHOULD | Done | The same e2e test, and the engine's `finally` runs |
| UI-6 | SHOULD | Done | "What the assistant saw", used by most e2e tests |
| UI-7 | SHOULD | Done, lightly tested | Source chips work and cited IDs are checked against the snapshot. All 26 live answers cited a source. Saying "not on this page" comes from the system prompt, and was seen on a real model but not measured at scale |

## Developer integration

| ID | Priority | Status | Evidence or gap |
|---|---|---|---|
| DEV-1 | MUST, prov. | Done | Example 01. Assumption A2 still needs real apps from other developers |
| DEV-2 | MUST | Done | [models.md](models.md), example 07 |
| DEV-3 | MUST, prov. | Done | Example 04, `test_script_mode_gets_a_panel_per_client` and `test_root_function_app_follows_sub_page_navigation` (e2e). The shared auto-index page no longer exists in NiceGUI 3 |
| DEV-4 | SHOULD | Done | `test_exact_system_prompt_override` |
| DEV-5 | SHOULD | Done | `test_usage_hook_cost_and_session_limits`. Limits are per session, so they reset on reload |
| DEV-6 | SHOULD | Partial | [versioning.md](versioning.md) is written and `.github/workflows/ci.yml` includes the pre-release job, but the workflow has not yet run on GitHub |

## Engines

| ID | Priority | Status | Evidence or gap |
|---|---|---|---|
| ENG-1 | MUST | Done | `engine.py`, `test_engines.py`. Cancellation closes the iterator |
| ENG-2 | SHOULD | Done | `test_async_generator_of_str`, example 06 |
| ENG-3 | MUST | Done | Live on Claude Opus 5.5, including tool rounds. `test_openai_tool_round_trip_with_the_real_sdk` covers OpenAI on a fake server only. Uses provider SDKs and no agent framework |
| ENG-4 | SHOULD, prov. | Not done | Example 06 shows the adapter's shape with a stand-in agent. No ADK adapter exists, and spike S2 was not run |
| ENG-5 | SHOULD | Done, fake server | `test_local_model_through_an_openai_compatible_endpoint`. Not run against real Ollama |
| ENG-6 | MAY, prov. | Not done | Council engine, pending spike S3 |
| ENG-7 | SHOULD | Done | `test_events.py` maps every event onto `ag-ui-protocol` |
| ENG-8 | MAY | Not done | |

## Security and privacy

| ID | Priority | Status | Evidence or gap |
|---|---|---|---|
| SEC-1 | MUST | Done | `test_10_two_users_never_see_each_other`, `test_two_real_browser_tabs_stay_separate` (e2e), `test_no_conversation_or_page_state_at_module_level` |
| SEC-2 | MUST | Done | `test_exfiltration_attempt_loads_nothing_and_renders_nothing_active` (e2e) watches the network |
| SEC-3 | SHOULD | Done | `test_every_partial_chunk_is_safe` |
| SEC-4 | MUST | Done | Fencing, `test_page_content_cannot_close_its_fence`. Claude Opus 5.5 flagged the injection in example 08 and did not follow it, in a single try. This limits injection and does not prevent it. See [security.md](security.md) |
| SEC-5 | MUST | Done | `test_sensitive_inputs_are_withheld_by_default`, `test_exclude_fields_removes_table_columns_everywhere` |
| SEC-6 | MUST | Done | [security.md](security.md), example 09 |
| SEC-7 | SHOULD | Done | `test_redaction_runs_on_every_string_before_any_engine`, [data-flow.md](data-flow.md) |
| SEC-8 | MUST | Done | Calls run on the server, and the browser gets sanitized blocks only |
| SEC-9 | MUST | Done | No `ui.markdown` for output. Minimum NiceGUI 3.19.0, checked against all 24 published advisories |
| SEC-10 | MUST | Done | No Glimpse service exists |

## Non-functional

| ID | Priority | Status | Evidence or gap |
|---|---|---|---|
| NFR-1 | MUST | Done | NiceGUI is the only required dependency, and `test_core_does_not_import_nicegui_or_any_provider` checks the imports |
| NFR-2 | SHOULD | Partial | Heartbeats, cancel on close and a reconnect test exist. **Not tested behind nginx** |
| NFR-3 | MUST | Done | `test_concurrent_sessions_*` |
| NFR-4 | SHOULD, prov. | Partial | `test_snapshot_does_not_block_the_event_loop` applies a smoke limit on 300,000 rows. Numeric targets wait for S1 |
| NFR-5 | SHOULD, prov. | Partial | 26 questions in `test_fidelity.py`. Whether the facts reach the model is tested in every run. Claude Opus 5.5 scored 26/26 live, in one run with a simple substring scorer and the probe off. Pass thresholds wait for spike S1 |
| NFR-6 | SHOULD | Done | `test_only_the_adapter_mentions_nicegui` |
| NFR-7 | SHOULD | Done | [nicegui-internals.md](nicegui-internals.md), `test_private_nicegui_attributes_only_appear_in_compat` |
| NFR-8 | MUST | Done | `docs/` |
| NFR-9 | SHOULD | Done | `test_failure_cases.py` |

## Open issues from the SRS

| # | Issue | Outcome |
|---|---|---|
| 1 | Check the Gemini research against the requirements | Read. Most of it agrees. See the differences below |
| 2 | The initial idea note was not read | Read. It adds nothing that changes the requirements |
| 3 | The license was not chosen | The repository already has MIT |
| 4 | Numeric targets for latency, budget and accuracy | Still waiting for spikes S0 and S1. The default budget of 16,000 tokens is a starting point |
| 5 | Minimum NiceGUI and Python versions | NiceGUI 3.19.0, Python 3.10 |
| 6 | Visibility policy | [visibility-policy.md](visibility-policy.md) |

### Where this differs from the Gemini research

- **It recommends Pydantic AI for the direct engine.** The SRS asks for near-zero dependencies and no required agent framework (NFR-1, ENG-3), so the direct engine uses provider SDKs as optional extras.
- **It stores history in `app.storage.tab`.** Glimpse keeps it on the client connection for now. That is simpler and safer for SEC-1, but a reload loses the conversation.
- **Its probe example reads rows from the browser.** Glimpse reads row indices instead, because a large reply over Socket.IO can drop the connection, and the server already has the rows.
