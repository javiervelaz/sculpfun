# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project: laserq

CLI tool for controlling the SculpFun S30 Pro Max laser engraver (GRBL 1.1 firmware). Designed for batch production with rotary axis support, especially conical objects (mugs, thermoses). Not a replacement for LightBurn—it automates the manufacturing pipeline (G-code generation → job queue → hardware execution).

## Commands

```bash
# Install in editable mode (required first)
pip install -e ".[dev]"

# Run all tests (no hardware required)
pytest

# Run a single test file
pytest tests/test_rotary.py

# Run a single test
pytest tests/test_gcode.py::test_no_repite_feed_ni_power

# Lint
ruff check src/

# CLI (real hardware)
laserq status
laserq raster image.png --material mdf_3mm_grabado
laserq rotary-info -d 90 --diameter-end 70 -l 100

# Batch: the queue homes ONCE before the first job by default.
laserq queue work                 # flat bed
laserq queue work --no-home       # rotary mounted, or after `set-origin`

# CLI (no hardware — uses FakeConnection)
laserq --fake status
laserq --fake queue work --no-home --no-confirm
```

**Not implemented yet** (do not assume these exist): `laserq rotary` (raster
onto a cone — the inverse mapping `ConeMapping.design_u()` is written but
unused), SVG import, toolpath ordering. Vector engraving on cones works via
`ConeMapping.warp_polyline()`; see `examples/lote_desde_csv.py`.

## Architecture

Three layers with hard boundaries — no layer should reach across:

```
Generators (laserq.gcode) → Queue (laserq.jobs) → Driver (laserq.driver) → Machine
      ↑                           ↑                        ↑
 Never touches               SQLite-backed           Only layer with
 serial port                 job state machine       serial port access
```

**`laserq/driver/`** — Hardware communication
- `connection.py`: Serial port abstraction + `FakeConnection` (used with `--fake` flag)
- `streamer.py`: Character-count flow control for GRBL's 128-byte buffer
- `state.py`: GRBL status/settings parser

**`laserq/gcode/`** — G-code generation (pure functions, no I/O)
- `raster.py`: Image → G-code with Jarvis dithering
- `rotary.py`: Conical mapping (`ConeMapping.warp_polyline()`) — arc-length-preserving geometry for text/images on tapered objects
- `builder.py`: G-code program assembly with F/S deduplication

**`laserq/jobs/`** — Job queue
- `queue.py`: SQLite persistence, states: PENDING → RUNNING → DONE/FAILED/CANCELLED
- `worker.py`: Polls queue, executes with operator confirmation; decoupled from CLI so it can be HTTP-fronted later. `home_policy` is `"once"` (default) / `"each"` / `"never"` — see below

**`profiles/`** — Versioned configuration (YAML, tracked in git)
- `machine.yaml`: Port, work area, backlash, rotary roller diameter
- `materials/*.yaml`: Speed, power, passes, DPI, dither algorithm, gamma — each with `verified_on` timestamp for calibration tracking

## Key Conventions

**Language:** Code comments, docs, error messages, and variable names are in Spanish (Argentina). Examples: `generar_pieza()`, `lote_desde_csv.py`.

**GRBL parameter requirements** — these must be set on the machine before automation:
- `$32=1` — laser mode (synchronizes power with motion; critical for quality)
- `$30=1000`, `$31=0` — power scale 0–1000
- `$22=1` — homing cycle enabled (required before any job)

**Homing policy (`Worker.home_policy`):** `"once"` homes before the first job
of a run and again after any failure (`emergency_stop()` soft-resets, so the
position is no longer trustworthy). `"never"` is **mandatory with the rotary
mounted** — Y is the roller there, and `$H` would hunt for a limit switch that
does not exist on that axis — and is also required for the
`home` → `jog` → `set-origin` workflow, where a later homing invalidates the
G92 offset.

**Stopping on failure:** `Streamer.run()` calls `abort()` (feed hold, then soft
reset) before propagating any exception. An `error:N` does not stop GRBL by
itself — it keeps executing the ~128 bytes already in its buffer with the laser
on. Never catch a streaming error and let the process exit without that stop.

**G-code conventions:**
- Always use M4 (dynamic power mode), not M3 — prevents burns at deceleration zones
- Deduplicate F (feed) and S (power) commands to conserve GRBL's lookahead buffer
- Backlash compensation happens at generator level (not firmware)

**Testing:** All 67 tests run without hardware. `FakeConnection` replaces serial for full CLI integration testing.

**Material profiles** use `verified_on` timestamps so calibration history is tracked in git — don't hardcode material settings in source.
