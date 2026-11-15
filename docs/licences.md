# Licences: short version

Summary of `REVIEW.md` (Licences) and `data/README.md`. Not legal advice: counsel must review before any client delivery.

**No AGPL code is used.** The detector is torchvision's SSDLite (BSD-3-Clause), not Ultralytics YOLO.

## Needs attention before commercial delivery

| Item | Licence | Allowed today | Before delivery |
| --- | --- | --- | --- |
| PyAV 18.1.0 (video decoding) | BSD-3-Clause, but the Windows wheel bundles FFmpeg (LGPL) and the **GPL-2.0+ codecs `libx264` and `libx265`** | Internal demo, decoding only; `libx264` was also used once, on this laptop, to cut the stand-in clip | Check whether shipping the wheel triggers GPL terms; or use an LGPL-only FFmpeg build |
| SSDLite starting weights (COCO) and our fine-tuned `look_rgb.pt`, `look_thermal.pt` | Code BSD-3-Clause; **the weights have no stated licence**; COCO images are under Flickr terms | Internal demo | Counsel review of the weights; or retrain from weights with a clear licence |
| Svanström Drone Detection Dataset (all video, drone and background audio; `sound.pt`) | **Sources disagree**: CC0-1.0 in the repository, "Other (Open)" on Zenodo, CC BY 4.0 on the article | Internal demo, with citation | Ask the authors which applies (contact in `data/README.md`). 49 YouTube clips and all helicopter audio are already excluded |
| FSD50K `Engine` clips (engine sound proxy) | Dataset CC BY; per-clip licences; only CC0 clips used. **"Commercial use requires contacting the authors"** | Internal demo | Contact the FSD50K authors |
| OpenStreetMap basemap of Portsmouth (`data/basemap/portsmouth.json`, committed) | ODbL 1.0: attribution required (shown on the map); share-alike if the derived data is distributed publicly | Private repository and demo display | Keep the attribution; check share-alike before distributing the file |

## Clear to use

| Item | Licence |
| --- | --- |
| torch 2.15.0, torchvision 0.29.2 (CPU) | BSD-3-Clause style |
| numpy, scipy, uvicorn, websockets, starlette, click, idna | BSD-3-Clause |
| fastapi, pydantic, PyYAML, anyio, h11 | MIT |
| opentelemetry-api | Apache-2.0 (an API only; nothing is recorded or sent) |
| Test tools: pytest, ruff (MIT), httpx (BSD-3-Clause), certifi (MPL-2.0, tests only) | Permissive or weak copyleft, development only |

## Ruled out, not used

| Source | Why |
| --- | --- |
| Drone Audio Dataset | Non-commercial; bars defence and surveillance use |
| Drone-vs-Bird | Research use only, under a signed agreement |
| Ultralytics YOLO | AGPL-3.0, which covers fine-tuned models too |

## Media used on screen

Every detector clip comes from one of two public datasets, listed clip by clip in `config/media_manifest.yaml` (path, SHA-256, label, split). The dashboard names the dataset in every caption: "Sample clip from Svanström Drone Detection Dataset - not footage of this track", "Sample recording from FSD50K". No client or site footage is used.

### Stand-in clips (S1 Zoom tab)

| Item | Source | Licence | Credit shown on screen |
| --- | --- | --- | --- |
| "RQ-7B Shadow Flight Demonstration": three in-flight cuts, 02:05.3 to 02:10.8, 02:13.8 to 02:20.5 and 02:28.0 to 02:35.0, cropped, audio removed | DVIDS, https://www.dvidshub.net/video/493473/rq-7b-shadow-flight-demonstration, downloaded 2026-11-15 | Public domain (work of the US government) | "Stand-in clip: RQ-7B Shadow fixed-wing drone - DVIDS, Tech. Sgt. Michael McGhee, public domain - not footage of this track" |

DVIDS media is public domain, but its use **implies no endorsement by the US Department of Defense** or any of its components; do not present it as such (https://www.dvidshub.net/about/copyright). The clips show a training flight demonstration in Iowa, not an attack. They are display only: no detector ran on them and they are not evidence. Recorded in `config/display_clips.yaml`; both files are committed in `data/standin/` (`docs/rules.md` §5 exception). S2's Zoom tab plays three held-out Svanström clips (V_DRONE_027, 033, 032) under the dataset's terms above; they stay out of git.
