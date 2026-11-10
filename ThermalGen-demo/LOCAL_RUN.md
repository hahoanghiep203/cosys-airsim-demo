# ThermalGen local exploration

Upstream: https://github.com/arplaboratory/ThermalGen
Revision: 681f8f96be1bb55779b49e10af0a273ff8e74895

## Run the pretrained demo

From this directory in PowerShell:

```powershell
.\run-demo.ps1
```

The launcher uses the project-local Python environment and Hugging Face cache. First run downloads the XL/2 weights (~4.41 GB) and Stability RGB VAE. The original `thermalgen_demo.py` is preserved. It resizes `test_color.png` to 256x256 and writes:

- `test_thermal_uncond.png`: RGB-conditioned, no dataset/style label.
- `test_thermal_cond.png`: RGB-conditioned, M3FD style (label 7).
- `test_thermal_cond_cfg4.png`: M3FD style with classifier-free guidance scale 4.

## Architecture and scope

RGB image -> RGB KL-VAE latent -> RGB/style-conditioned SiT flow model -> thermal KL-VAE -> grayscale image. Noise and VAE sampling make outputs stochastic. The default sampler is adaptive Dopri5; its 50 saved time points are not a limit of 50 network evaluations.

Style labels are in `configs/datasets`: Boson night 0, BosonPlus day/night 1/2, DJI day 3, M3FD 7. Label 1000 removes style conditioning while retaining RGB.

`thermalgen_demo.py` is the shortest inference path. `thermalgen.py` and `main.py` provide Lightning training; `test.py` evaluates datasets; `generate_map.py` stitches overlapping map patches. Full workflows need additional dependencies, downloaded datasets, and Lightning-format checkpoints. SLURM shell launchers target Linux clusters.

## AirSim relevance

Try captured RGB frames as inputs for synthetic thermal appearance. These grayscale intensities are not calibrated temperatures or physical heat simulation. The code has no AirSim integration or temporal-consistency mechanism; independent video frames can flicker.

## Local environment

Python 3.11, CUDA 12.8 PyTorch 2.7.1 / torchvision 0.22.1 selected for the RTX 5060 Ti. This differs from upstream Python 3.10 / PyTorch 2.4 / CUDA 12.1. Only inference dependencies are installed; xformers and training dependencies are unnecessary for this demo.

## Verified result (2026-10-21)

- Original `thermalgen_demo.py` completed with exit code 0 on RTX 5060 Ti using PyTorch 2.7.1+cu128. Upstream source files were not edited.
- CUDA availability, GPU identification, and a CUDA matrix multiplication passed.
- All three 256x256 grayscale PNGs decoded successfully and had nonconstant pixels: unconditional range 3-240, conditional 0-236, CFG4 0-236. Visual inspection confirmed recognizable street structure.
- `uv pip check --python .venv/Scripts/python.exe` passed for all 32 installed packages. Exact resolved versions are in `requirements-demo-lock.txt`.
- The 4,410,051,896-byte ThermalGen checkpoint and 334,643,276-byte RGB VAE are cached under `.hf-cache`.
- Non-fatal upstream messages: optional hf_xet absent (HTTP download succeeded); future torch.meshgrid indexing warning.
- Training, evaluation against ground truth, stitched-map generation, and AirSim integration were not run. Inference timing was not benchmarked.

To recreate the environment with uv installed, run `.\setup-demo.ps1`; then `.\run-demo.ps1`. Subsequent runs reuse the model cache. Outputs are stochastic and will be overwritten by a rerun.

