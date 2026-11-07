"""Keep training and evaluation apart by source, because frames of one clip are near-copies."""

import hashlib
import itertools
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Clip:
    id: str
    number: int
    stratum: str
    """Clips only group within one stratum, and splits are balanced per stratum."""
    source: str = ""
    """Must match for neighbouring clip numbers to count as the same session."""


@dataclass(frozen=True)
class Group:
    """Clips that may share a recording session, so they must stay in one split."""

    id: str
    stratum: str
    clips: tuple[Clip, ...]


class _Sets:
    """Union-find over clip IDs."""

    def __init__(self, ids: Sequence[str]) -> None:
        self._parent = {clip_id: clip_id for clip_id in ids}

    def find(self, clip_id: str) -> str:
        while self._parent[clip_id] != clip_id:
            self._parent[clip_id] = self._parent[self._parent[clip_id]]
            clip_id = self._parent[clip_id]
        return clip_id

    def join(self, a: str, b: str) -> None:
        self._parent[self.find(a)] = self.find(b)


def scene_groups(
    clips: Sequence[Clip],
    signatures: Mapping[str, np.ndarray],
    max_hamming: int,
    prefix: str,
) -> list[Group]:
    """Group neighbouring clip numbers with one source, and clips that show the same scene.

    The dataset has no session IDs, so this is a stand-in: it cannot prove that two groups
    are separate flights. Neighbouring numbers alone are not enough, because one flight often
    spans several distance bins.
    """
    ordered = sorted(clips, key=lambda c: (c.stratum, c.number))
    sets = _Sets([clip.id for clip in ordered])
    for a, b in itertools.pairwise(ordered):
        if (a.stratum, a.source, a.number + 1) == (b.stratum, b.source, b.number):
            sets.join(a.id, b.id)
    for i, a in enumerate(ordered):
        for b in ordered[i + 1 :]:
            if a.stratum != b.stratum:
                break
            if hamming(signatures[a.id], signatures[b.id]) <= max_hamming:
                sets.join(a.id, b.id)
    members: defaultdict[str, list[Clip]] = defaultdict(list)
    for clip in ordered:
        members[sets.find(clip.id)].append(clip)
    return [
        Group(f"{prefix}_{group[0].number:03d}", group[0].stratum, tuple(group))
        for group in members.values()
    ]


def fixed_blocks(clips: Sequence[Clip], size: int, prefix: str) -> list[Group]:
    """Blocks of neighbouring clip numbers, for sources with nothing else to group by."""
    ordered = sorted(clips, key=lambda c: c.number)
    return [
        Group(
            f"{prefix}_{ordered[i].number:03d}",
            ordered[i].stratum,
            tuple(ordered[i : i + size]),
        )
        for i in range(0, len(ordered), size)
    ]


def assign_splits(
    groups: Sequence[Group], fractions: Mapping[str, float], salt: str
) -> dict[str, str]:
    """Map each group ID to a split, balancing clip counts within each stratum.

    Largest groups go first, each to the split furthest below its share. Ties follow the
    order of ``fractions``, and the salted hash makes the order of equal-sized groups fixed.
    """
    strata: defaultdict[str, list[Group]] = defaultdict(list)
    for group in groups:
        strata[group.stratum].append(group)
    assigned: dict[str, str] = {}
    for stratum in sorted(strata):
        members = strata[stratum]
        total = sum(len(g.clips) for g in members)
        placed = dict.fromkeys(fractions, 0)
        for group in sorted(
            members, key=lambda g: (-len(g.clips), _salted(salt, g.id))
        ):
            split = max(fractions, key=lambda s: fractions[s] * total - placed[s])
            assigned[group.id] = split
            placed[split] += len(group.clips)
    return assigned


def _salted(salt: str, text: str) -> str:
    return hashlib.sha256(f"{salt}|{text}".encode()).hexdigest()


def splits_too_thin(
    counts: Mapping[tuple[str, str], Counter[str]], split: str, minimum: int
) -> list[str]:
    """Which (modality, label) pairs have too few clips in a split."""
    return [
        f"{modality} {label}: {tally[split]} {split} clips"
        for (modality, label), tally in sorted(counts.items())
        if tally[split] < minimum
    ]


def hamming(a: np.ndarray, b: np.ndarray) -> int:
    return int(np.count_nonzero(a != b))


def lookalike_pairs(
    signatures: Mapping[str, np.ndarray],
    splits: Mapping[str, str],
    first: str,
    second: str,
    max_hamming: int,
) -> list[tuple[str, str]]:
    """Pairs across two splits whose clip signatures nearly match."""
    left = [c for c in sorted(signatures) if splits[c] == first]
    right = [c for c in sorted(signatures) if splits[c] == second]
    return [
        (a, b)
        for a in left
        for b in right
        if hamming(signatures[a], signatures[b]) <= max_hamming
    ]


def drop_exact_copies(entries: Sequence[dict]) -> tuple[list[dict], list[dict]]:
    """Keep the first clip with each hash. A copy could otherwise land in another split."""
    kept: dict[str, dict] = {}
    excluded = []
    for entry in sorted(entries, key=lambda e: e["path"]):
        first = kept.setdefault(entry["sha256"], entry)
        if first is not entry:
            excluded.append(
                {"path": entry["path"], "reason": f"exact copy of {first['path']}"}
            )
    return list(kept.values()), excluded
