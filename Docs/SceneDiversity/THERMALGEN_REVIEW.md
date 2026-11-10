# Captured-image realism review and ThermalGen run — 2026-10-23

Both ThermalGen inference runs completed, but the results **do not pass as physically faithful thermal ground truth**. Original captures are preserved. Treat generated images as appearance experiments; no measured-temperature accuracy or downstream training benefit is established.

Open `ThermalGenReview/INDEX.html` in the canonical Cosys_Airsim project for all 50 three-way comparisons and the original-demo control.

## What was verified

- Input: `Saved/SceneDiversity/thermalgen_audited50/`, 50 independent viewpoints, 1280×720 RGB/IR pairs. Existing capture audit passed matching poses/timestamps, unique images and camera clearance. This review decoded every image and verified RGB/IR hashes again after inference: **unchanged**.
- Previous thermal audit covered 1,022 runtime mesh components, approximately 2.71 million instances, 39 actual hot-surface probes and all 13 vehicles' tire checks. Those checks establish configured simulation behavior, not measured real-world realism. See `TEMPERATURE_AUDIT.md`.
- All source pairs and both generated batches were reviewed on contact sheets; representative images were inspected separately at their output resolution. No corrupt, constant or duplicate generated PNGs were found. Both 50-image manifests completed; the original sample control also completed.
- Screening flags: **40/50** RGB images have more than 70% of grayscale pixels at or below 8/255; **24/50** IR images have global grayscale standard deviation below 5/255. **45/50** have one or both flags. These deliberately simple thresholds flag difficult low-light/low-contrast examples; they are not a real-camera calibration test or automatic proof that a night image is invalid.

## Model and actual runs

Used the existing local `ThermalGen/.venv`, cached ThermalGen-XL/2 weights, PyTorch 2.7.1+cu128 and RTX 5060 Ti. Unreal and local language-model inference were absent before starting. No project editor was opened/closed, no new model was downloaded, and no paid API was used.

Checkpoint snapshot: `1b030a5e575f11a0a49d85de87f76c4ef20e7015`; SHA256 `cc2eb247c48d11eada129d72819f4c2b148569227b9ee4f8cc682e132ef7bfb3`.

| Run | Input/output size | Conditioning | Results | Observed batch wall time |
|---|---|---|---|---:|
| Initial aspect-preserving experiment | 256×144 | Boson night style 0, CFG 1 | 50 generated PNGs | 85.5 s |
| Original-demo comparison | 256×256 | M3FD style 7, CFG 1 | 50 generated PNGs + original sample control | 89.8 s |

The first run uses the model's dynamic positional embeddings to retain the full 16:9 frame without padding/cropping. Its rectangular inference is an experimental departure from the square demo. The second uses the demo's square resize, which stretches the 16:9 source; it is a control comparison, not an aspect-correct replacement dataset. Source captures remain 720p; generated images are **not 720p**. No upscaled images are presented as native model resolution.

Both runs use raw RGB normalized to [-1,1], float32 with high matmul precision, evaluation mode, batch size one, per-image seed `20261023 + index`, and the original adaptive Dopri5 sampler. Its 50 saved time points are not a limit of 50 network evaluations. Peak PyTorch allocated GPU memory was approximately 4.33/4.40 GiB. Median measured inference was approximately 1.00/1.19 seconds per image; this is offline inference and does not establish Unreal preview FPS.

## Realism findings

The Boson aerial style frequently replaces street objects with blurred texture. M3FD keeps more recognizable paving, steps and building edges in brighter views, but vehicles and their hot hood/tire states are often missing or altered. The recognizable road/buildings/cars in the original `test_color.png` control show that execution works; changing style and square preprocessing did not make these dark synthetic inputs physically faithful.

The scene temperatures are controlled assumptions: uniform ambient surfaces, residual road warmth, and localized operating/cooling vehicle presets. Uniform backgrounds, broad hot patches, approximate mixed-material emissivity and stylized props leave a visible domain gap. The warm tank is a whole-surface preset and does not simulate nearby transfer. No new heat was added to decorative planes.

ThermalGen consumes RGB and a style label; this run does **not** condition on the simulated IR, temperatures, source metadata or engine state. Therefore it cannot be relied on to preserve invisible distinctions such as an operating engine versus an otherwise identical cold vehicle. Generated grayscale values are neither Kelvin nor calibrated radiance. Do not replace the simulated IR labels with these images and call the original temperature metadata their ground truth.

FLIR's [measurement guidance](https://docs.flir.com/T810603/en-US/latest/s07.html) identifies surface temperature, emissivity, ambient temperature and distance as measurement factors. The [ThermalGen paper](https://arxiv.org/abs/2509.24878) describes RGB-to-thermal image synthesis and style conditioning; successful synthesis alone does not validate this scene's temperatures.

## Outputs and repeatability

Everything generated is isolated under `Saved/SceneDiversity/ThermalGenReview_20261023/`:

- `review.json`: each original pair, SHA256 hashes, statistics and screening flags.
- `generated/`, `inference.json`: first 50-image experiment, seeds, exact checkpoint and timing.
- `M3FD_demo/generated/`, `M3FD_demo/inference.json`: original-demo comparison and control.
- `comparisons/`, `M3FD_demo/comparisons/`, and each `all50_comparisons.jpg`: RGB | simulated IR | generated appearance.
- `validation.json`, `image_diagnostics.csv`: final integrity checks and image-level diagnostics.

The CSV's gradient cosines and bright-IR proxy deltas are screening diagnostics, **not semantic hood/tire masks or temperature error**. There are no captured part masks/depth labels in this batch, so part-level heat recall is not reported. No FID, real-camera benchmark or training/evaluation run was performed.

Reusable scripts are `Scripts/SceneDiversity/run_thermalgen_review.py` and `finalize_thermalgen_review.py`. Use a new empty output folder for each `review`, then `infer --model-root <ThermalGen folder>`; defaults reproduce the rectangular experiment. Add `--style 7 --height 256 --control` for the square demo comparison. `finalize` expects both completed variants in the layout above. A new source capture must be reviewed independently.

## Next useful changes

Retain the night setting but lift indirect illumination/exposure enough for visible object structure, then recapture. Add closer and moderate oblique views so small tire/hood regions survive model downsampling. Keep operating-state metadata and simulated IR separate from learned appearance. Validate representative materials and hot surfaces against matched-condition real LWIR measurements before claiming physical accuracy. Do not add more assets as a substitute for fixing this input/conditioning gap.

Astra Team Antigravity (Gemini 4 Argon Medium) supplied a text-only advisory on validation limits; it did not inspect images. Its combined flag count was not accepted as a low-light-only count, and its assertion that material/atmospheric effects were absent was not accepted: the existing model contains approximations, with no measured calibration. Root execution verified the files, images and actual run results. Local LLM inference stayed unloaded to preserve GPU resources.
