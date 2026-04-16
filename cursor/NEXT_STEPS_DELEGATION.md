# Next Steps Delegation Matrix

This document starts execution of the roadmap while waiting for the proprietary Nanoleaf driver.

## Delegation model
- **AI-Architecture (GPT-5.3-Codex)**: owns interface contracts, service reliability, configuration schema.
- **AI-Capture (GPT-5.3-Codex)**: owns replay backend and capture selection logic.
- **AI-QA (GPT-5.3-Codex)**: owns contract tests, replay tests, and regression checks.
- **AI-Docs (GPT-5.3-Codex)**: owns integration runway docs and release notes updates.

## Started in this iteration
1. Driver contract skeleton (`device.interfaces.DeviceDriver`) and capabilities metadata.
2. Replay capture backend + capture factory support (`prefer_backend='replay'`).
3. Service observability and adaptive recovery knobs surfaced in config + status.
4. Tray diagnostics action for quick field debugging.
5. Initial tests for replay backend and driver contract.

## Pending follow-ups
- Implement calibration profile builder and migration utilities.
- Add benchmark script and CI workflow for quality gates.
- Integrate structured event export endpoint.
- Replace protocol stub bytes once proprietary driver spec arrives.
