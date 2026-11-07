# Optional: train a detector on a Colab GPU

CPU stays the default, and `uv.lock` stays the Windows CPU lockfile. The GPU build of torch is installed on the Colab runtime only, so it never enters this repo.

Use a ZIP built from a commit with `git archive` on the Windows machine. It carries the same manifest bytes as that machine, and `scripts/evaluate_media.py` refuses weights trained against a different manifest hash. A fresh Linux clone has different line endings, so it would be refused. Do not run `scripts/prepare_media.py` on Colab, because it rewrites the manifest.

## Set up

Select **Runtime > Change runtime type > T4 GPU**, then upload the ZIP to `MyDrive/cuas-demo.zip`.

```python
# Cell 1: see the GPU, connect Drive
!nvidia-smi --query-gpu=name,driver_version --format=csv
from google.colab import drive
drive.mount('/content/drive')
```

```python
# Cell 2: unpack, and confirm the manifest. Prints: config/media_manifest.yaml: OK
!unzip -qo /content/drive/MyDrive/cuas-demo.zip -d /content
%cd /content/cuas-demo
!echo "bc49b46ddb779574d8ab44e9ce52c9662f5b6b13a43f8a7b4b8da22da6f9caa5  config/media_manifest.yaml" | sha256sum -c
```

```python
# Cell 3: keep models/ on Drive, so a checkpoint outlives the runtime. Prints: two
!mkdir -p /content/drive/MyDrive/cuas-models
!ln -sfn /content/drive/MyDrive/cuas-models models
!echo one > models/.t.tmp && mv -f models/.t.tmp models/.t && echo two > models/.t.tmp && mv -f models/.t.tmp models/.t && cat models/.t && rm models/.t
```

```python
# Cell 4: the locked packages, then the GPU build of torch in place of the CPU one
!pip install -q uv==0.13.7
!uv sync --frozen --no-install-package torch --no-install-package torchvision
!env -u UV_CONSTRAINT -u UV_BUILD_CONSTRAINT uv pip install --python .venv/bin/python "torch==2.15.0+cu132" "torchvision==0.29.2+cu132" --index-url https://download.pytorch.org/whl/cu132
!.venv/bin/python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

```python
# Cell 5: the recordings and starting weights. The last line should read: 226 problems
!.venv/bin/python scripts/download_data.py | grep -v fsd50k
```

- **From here on, run `.venv/bin/python`, never `uv run`.** `uv run` re-syncs to the lockfile, which puts the CPU build of torch back.
- **`226 problems`** are the FSD50K audio clips, which the detector does not need. Any other problem line is a real failure.
- **If cell 4 prints `False` or warns about an old driver,** Colab's NVIDIA driver does not support this CUDA 13 build. `--device cuda` will then refuse to run rather than use the CPU.

## Measure speed

```python
# Cell 6: writes no weights or checkpoint. The first line names the GPU.
!.venv/bin/python scripts/train_detector.py --modality thermal --measure --device cuda
```

It decodes the training frames on a fresh runtime, then times 32 batches after a 2-batch warm-up. It prints seconds per batch, minutes per epoch and the total against the 120-minute budget in `site.yaml`.

## Train, once the speed is acceptable

```python
!.venv/bin/python scripts/train_detector.py --modality thermal --device cuda
```

- **If the runtime stops:** repeat the setup cells and this command. It resumes from `models/look_<modality>.checkpoint.pt` on Drive and loses at most one epoch. A checkpoint can move between CPU and GPU. Resuming is tested to give identical weights on the CPU; on a GPU it is not proven to be bit-identical.
- **What stays the same:** the manifest, the splits and the training settings. The test split is never read, and the model returns to the CPU to save its weights and choose the validation threshold.
- **The record:** `models/look_<modality>.json` names the GPU under `trained_on`.

## Evaluate on the Windows machine

Copy `look_<modality>.pt` and `look_<modality>.json` into the local `models/` folder, then run this there, with nothing else running:

```
uv run python scripts/evaluate_media.py --model look_<modality> --split test
```

That keeps the CPU timings and the count of test attempts on the machine the plan measures.

## Licences

The GPU packages (`torch` and `torchvision` built for CUDA, `triton` and NVIDIA's `nvidia-*` CUDA libraries, under NVIDIA's own terms) are installed on the Colab runtime only. They are not in `pyproject.toml` or `uv.lock`, and nothing from them is copied back except the trained weights.
