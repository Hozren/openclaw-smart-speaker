# Instructions for coding agents

## Scope

Read README.md, SKILL.md, references/deployment.md and references/boot.md before changing behavior. These are repository-owned sources: edit them using normal Git workflows. Do not modify a separately installed skill or the running speaker as a side effect of repository work.

## Preserve the contract

- Target Linux/systemd/PipeWire; do not claim other platforms work without an implemented, tested backend.
- Keep paths, audio devices, agent ID and wake word configurable. Never hardcode the author's account or hardware identifiers.
- Discover and benchmark models available in the target account; do not pin a supposedly fastest commercial model.
- Preserve explicit audio selection, continuous capture with deterministic controls, wake-at-start matching, rolling follow-up, stop handling and reconnect behavior.
- Preview voices through temporary overrides; persist the user's choice atomically.
- Keep model downloads out of synthesis runtime. Verify official provenance and hash before loading torch.package content.
- Maintain one listener. Save configuration and service state before deployment changes and document rollback.

## Security and operational boundaries

Do not commit credentials, account configuration, personal memory, transcripts, recordings, model weights, caches, virtual environments or export archives. Never print credential-bearing environments or complete configurations. Use subprocess argument arrays, not shell interpolation of spoken text. Do not add persistent recording or transcript logging by default.

Hardware playback, microphone tests, daemon changes and reboots are integration operations, not routine repository checks. Coordinate live tests. A code-only task does not authorize restarting the running speaker. Keep boot acceptance pending when it cannot be tested.

## Validation

1. Check Python syntax without loading models: `python3 -m compileall -q scripts`.
2. For behavior changes, verify relevant routing, follow-up timing, stop handling, settings validation and error recovery. Use isolated temporary settings, never the live voice selection.
3. With dependencies installed, run pip check, synthesize all five Silero voices, validate WAVs, and run synthetic TTS → ASR → agent → TTS. Explicitly report unavailable dependencies or account access.
4. Review paths, subprocess calls and documentation for portability and secrets. Keep documented flags consistent with the code.
5. Validate rendered units with systemd-analyze verify. Only a real boot without login and confirmed audio response validates boot acceptance; enabled status is insufficient.
6. Report exactly which checks ran and what remains unverified. Do not imply streaming, barge-in, graphical voice selection or asynchronous result delivery exists unless implemented and tested.

## Contributions

Keep changes focused. Exclude generated deployment artifacts. Confirm installed CLI/schema before changing OpenClaw integrations; do not invent flags or APIs. Preserve user changes and never force-push or rewrite history without an explicit request.

## Music component

The repository-owned skill is skills/speaker-music. Keep one stable cache root; never invoke a shell with song text. A cache hit must not require network or yt-dlp. Index only completed media; preserve cache across upgrades. Control only this component's mpv through its private IPC socket. Validate play/stop/status and installer behavior with `python3 -m unittest discover -s tests -v`; distinguish mocked installer tests from actual GitHub release installation. Release artifacts must exclude bytecode and local caches. Preserve speaker-music.tar.gz and speaker-music.sha256 in any release marked latest, since the installer consumes that API.

## Operation dispatcher

Read references/operations.md. Preserve exact-command parsing before agent routing, speech/music targeting, acknowledged IPC, no arbitrary command execution from state files, and suppression of paused/cancelled late replies. Use null-output mpv for playback tests. Do not add timers. Agent/tool cancellation and download cancellation are outside v1; document rather than imply them.
