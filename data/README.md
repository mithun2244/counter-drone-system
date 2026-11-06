# Data sources and recording rights

Public recordings only (`docs/rules.md` §5). Everything in `data/` except this file stays out of git.
`uv run python scripts/download_data.py` fetches it, and `--verify` checks every hash.

This records published terms and is not legal advice. Have counsel review before client delivery.

## In use

### Drone Detection Dataset (Svanström, Englund, Alonso-Fernandez)

- **URL:** https://github.com/DroneDetectionThesis/Drone-detection-dataset, pinned to commit `442d0c6750708cc221636f7a1fd31cbd8cb0aeb8`
- **Licence:** CC0-1.0 in the repository `LICENSE`. The sources disagree: [Zenodo](https://zenodo.org/records/5500576) shows "Other (Open)", and [the article](https://pmc.ncbi.nlm.nih.gov/articles/PMC8573135) is CC BY 4.0.
- **Rights:** the authors' own recordings in Sweden. The article says no human subjects or animals are included as subjects. It does not address people who might appear incidentally.
- **Used for:** RGB and thermal video (drone, bird, airplane, helicopter), plus drone and background audio.
- **Excluded, unverified third-party material:**
  - 49 visible clips (38 helicopter, 11 airplane) that the description spreadsheet attributes to https://www.youtube.com/user/SK678387.
  - All 30 helicopter audio clips, because the article does not say whether they came from those videos.
- **Excluded, duplicate:** `BACKGROUND_019.wav` is a byte-for-byte copy of `BACKGROUND_010.wav`.
- **Excluded, unreadable labels:** `V_AIRPLANE_002`, whose label file does not follow the layout of the other 649.
- **Labels:** read by `cuas.metrics.mat_labels`. The third-party `mcos-decoder` package was not used: it treats a two-box cell as an empty frame, which would misreport the 12 two-drone clips.
- **Requested citations:**
  - Svanström F. (2020), *Drone Detection and Classification using Machine Learning and Sensor Fusion*, thesis.
  - Svanström F., Englund C., Alonso-Fernandez F. (2020), *Real-Time Drone Detection and Tracking With Visible, Thermal and Acoustic Sensors*, ICPR.
  - Svanström F., Alonso-Fernandez F., Englund C. (2021), *A Dataset for Multi-Sensor Drone Detection*, Data in Brief 39, 107521.

### FSD50K (engine proxy)

- **URL:** https://zenodo.org/records/4060432
- **Licence:** the dataset is CC BY. Each clip has its own licence, set by its Freesound uploader. The record says commercial use requires contacting the authors.
- **Rights:** declared per clip by each uploader.
- **Used for:** CC0 clips labelled `Engine`, excluding any also labelled as speech or human voice. At most 266 clips from 152 uploaders in the `eval` set.
- **A proxy only:** these are mostly road vehicles. They are not recordings of one-way attack drones.

### SSDLite320 MobileNetV3 starting weights

- **URL:** https://download.pytorch.org/models/ssdlite320_mobilenet_v3_large_coco-a79551df.pth
- **Code licence:** BSD-3-Clause ([torchvision](https://github.com/pytorch/vision/blob/main/LICENSE)).
- **Weights licence:** none stated separately. [torchvision warns](https://docs.pytorch.org/vision/stable/models.html) that weights "may have their own licenses" derived from their training data, and that permission is the user's responsibility.
- **Data behind the weights:** COCO. A [secondary source](https://huggingface.co/datasets/shunk031/MSCOCO) gives annotations as CC BY 4.0 and images as subject to Flickr terms; [COCO's own page](https://cocodataset.org/#termsofuse) did not render when checked. Whether its training recipe used ImageNet weights is unverified.

## Checked and ruled out

| Source | Why |
| --- | --- |
| [Drone Audio Dataset](https://github.com/saraalemadi/DroneAudioDataset) | Non-commercial, and bars military, defence, intelligence, security, surveillance and weapons use |
| [Drone-vs-Bird](https://github.com/wosdetc/challenge) | Research use only, under a signed agreement |
| [Anti-UAV](https://github.com/ZhaoJ9014/Anti-UAV) | MIT on the project, but no audio or bird class mentioned, and data hosted on Drive and Baidu |

## Before client delivery

- Email the Svanström authors (DroneDetectionThesis@gmail.com) about the licence mismatch and the helicopter audio.
- Contact the FSD50K authors about commercial use.
- Check PyAV's wheel: it reports FFmpeg as LGPL v3 or later but also bundles `libx264` and `libx265`, which are normally GPL. The demo only decodes video.
