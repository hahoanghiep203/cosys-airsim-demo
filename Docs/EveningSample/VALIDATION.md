# Verified sample — 2026-10-21

Canonical project: Cosys_Airsim. UE 5.7.4, RTX 5060 Ti 16 GB, 32 GB RAM. Owned hidden editor PIE test, balanced distance/LOD preset, RGB main viewport and live GPU IR active together, 1280 x 720 each. No local inference running.

- Exact saved sample viewpoint, 70.013 seconds: **52.86 FPS** mean engine frame rate; **29.59 Hz** actual GPU IR dispatch. Target 30 Hz is close but not an exact sustained 30 Hz guarantee.
- Engine frame time: mean 18.92 ms, p95 35.11 ms, p99 39.86 ms, maximum 51.77 ms. Zero engine frames over 100 ms or 500 ms. No former FPS collapse/cycling reproduced in this run. UI wall timing independently showed maximum 54.82 ms.
- GPU frame time mean 10.86 ms, p95 14.26 ms. The worst engine frame includes game-thread tickable work. CPU simulation remains a material cost; unused VRAM alone cannot move arbitrary Unreal work to the GPU.
- This run covers more than the restored normal 60-second garbage-collection interval. It is a static editor test, not a packaged flight benchmark, long-duration soak or 30-pair-per-second disk recorder.
- Independent CPU surface/radiance result against GPU at the same geometry inputs: mean absolute difference **0.000140 / 255**, p95 and p99 zero, maximum 3 / 255; only about 0.000109% of channel values exceed 2. This validates agreement of the implemented calculations, not physical camera calibration.
- Scene check: **10 thermal sources**, seven existing car child sources, zero SUV sources, 687,284 thermal samples. Counter upper-side probe exceeds 305 K while lower cart remains 293.15 K. Source temperature and actual sampled surface temperature differ as intended.
- Fresh-start paired Scene/ThermalIR API captures pass at 1280 x 720 with identical reported camera pose and simulation timestamp. Hood, tire rubber, headlights and counter visibly warm; SUV stays cool. The live preview and API output agree visually.
- A previous moving-camera test produced an inconsistent saved IR image. It did not recur after the dedicated launcher started a fresh editor with the persisted pose, or in the post-measurement repeat. No native-code fix was claimed for an unreproduced transition issue. Check alignment/thermal features after changing cameras before accepting dataset frames.
- Original Showcase and user Showcase_CoordinateCrop SHA-256 hashes match their pre-sample values. Existing shared car/park Blueprint defaults were not edited. No heat sources added to decorative water planes.

`validation.json` records timings, counter values, capture metadata and protected-map checks. `scene_check.json` contains actual source/probe values. `sample_rgb.png` and `sample_ir.png` are an actual paused API pair from the sample, not generated concept art. CPU/GPU diagnostic images are separate.

Advisers: completed Antigravity gemini-4-argon-medium and local Qwen design reviews. After the routing change, the coordinator performed integration without further native Codex subagents. Both requested web model selectors failed before sending anything; there is no web adviser result to credit.
