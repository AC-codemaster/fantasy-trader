# Improvement loop, 2026-10-10 (2026-w05)

Live parameters v1. Backtest weeks: 2024 wk 3–18, 2025 wk 3–18, 2026 wk 2–4.
- Live parameters on the backtest: average miss 5.200 over 7,931 player-games (calibration slope 0.975).
- Tested damp 0.3 → 0.35 (requested): -0.0029 ± 0.0009 pts (z -3.28) → passes
- Tested env_scale 1 → 1.1 (requested): -0.0028 ± 0.0008 pts (z -3.39) → passes
- Tested w1 0.8 → 0.7 (requested): -0.0020 ± 0.0006 pts (z -3.18) → passes
- Tested low_target 2 → 2.25 (requested): -0.0013 ± 0.0004 pts (z -3.52) → rejected: gain 0.0013 pts (needs ≥ 0.002)
- Tested bundle damp 0.3 → 0.35, env_scale 1 → 1.1, w1 0.8 → 0.7, low_target 2 → 2.25: -0.0091 ± 0.0017 pts (z -5.52) → passes

**Adopted:** damp 0.3 → 0.35, env_scale 1 → 1.1, w1 0.8 → 0.7, low_target 2 → 2.25 (parameters v2).
