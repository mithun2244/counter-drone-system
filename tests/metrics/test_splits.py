from collections import Counter

import numpy as np

from cuas.metrics.splits import (
    Clip,
    Group,
    assign_splits,
    drop_exact_copies,
    fixed_blocks,
    hamming,
    lookalike_pairs,
    scene_groups,
    splits_too_thin,
)

FRACTIONS = {"train": 0.7, "test": 0.15, "val": 0.15}
BITS = 16


def clip(number: int, stratum: str = "a", source: str = "") -> Clip:
    return Clip(f"{stratum}{number}", number, stratum, source)


def group(group_id: str, size: int, stratum: str = "a") -> Group:
    return Group(group_id, stratum, tuple(clip(n, stratum) for n in range(size)))


def numbers(groups: list[Group]) -> list[list[int]]:
    return [[c.number for c in g.clips] for g in groups]


def signature(flipped: int, start: int = 0) -> np.ndarray:
    """A signature that differs from the base in a known number of bits."""
    bits = np.zeros(BITS, dtype=bool)
    bits[start : start + flipped] = True
    return bits


def unrelated(clips: list[Clip]) -> dict[str, np.ndarray]:
    """Signatures far apart, so only the neighbour rule can join these clips."""
    rng = np.random.default_rng(0)
    return {c.id: rng.random(BITS * 8) > 0.5 for c in clips}


def test_neighbouring_numbers_with_one_source_group_together() -> None:
    clips = [clip(3), clip(1), clip(2), clip(5), clip(6)]
    groups = scene_groups(clips, unrelated(clips), 0, "x")
    assert sorted(numbers(groups)) == [[1, 2, 3], [5, 6]]
    assert sorted(g.id for g in groups) == ["x_001", "x_005"]


def test_a_new_source_does_not_join_by_number_alone() -> None:
    clips = [clip(1, "a", "close"), clip(2, "a", "far")]
    assert len(scene_groups(clips, unrelated(clips), 0, "x")) == 2


def test_clips_showing_the_same_scene_join_even_when_far_apart_in_number() -> None:
    clips = [clip(1), clip(50)]
    signatures = {"a1": signature(0), "a50": signature(3)}
    assert numbers(scene_groups(clips, signatures, 3, "x")) == [[1, 50]]
    assert len(scene_groups(clips, signatures, 2, "x")) == 2


def test_scene_joins_are_transitive() -> None:
    clips = [clip(1), clip(50), clip(90)]
    signatures = {
        "a1": signature(0),
        "a50": signature(2),
        "a90": signature(4),  # 4 bits from a1, but 2 from a50
    }
    assert numbers(scene_groups(clips, signatures, 2, "x")) == [[1, 50, 90]]


def test_scenes_never_join_across_strata() -> None:
    clips = [clip(1, "a"), clip(1, "b")]
    signatures = {c.id: signature(0) for c in clips}
    assert len(scene_groups(clips, signatures, 0, "x")) == 2


def test_fixed_blocks_keep_neighbours_together() -> None:
    blocks = fixed_blocks([clip(n) for n in range(1, 8)], 3, "audio")
    assert numbers(blocks) == [[1, 2, 3], [4, 5, 6], [7]]
    assert blocks[1].id == "audio_004"


def test_splits_are_balanced_within_a_stratum() -> None:
    groups = [group(f"g{i}", 1) for i in range(20)]
    tally = Counter(assign_splits(groups, FRACTIONS, "salt").values())
    assert tally == {"train": 14, "test": 3, "val": 3}


def test_every_stratum_is_balanced_separately() -> None:
    groups = [group(f"a{i}", 1, "a") for i in range(20)]
    groups += [group(f"b{i}", 1, "b") for i in range(20)]
    assigned = assign_splits(groups, FRACTIONS, "salt")
    for stratum in "ab":
        tally = Counter(v for k, v in assigned.items() if k.startswith(stratum))
        assert tally["test"] == 3


def test_a_group_lands_in_exactly_one_split_even_when_large() -> None:
    assigned = assign_splits([group("big", 9), group("small", 1)], FRACTIONS, "salt")
    assert assigned == {"big": "train", "small": "test"}


def test_assignment_is_repeatable_and_depends_on_the_salt() -> None:
    groups = [group(f"g{i:02d}", 1) for i in range(30)]
    first = assign_splits(groups, FRACTIONS, "one")
    assert first == assign_splits(list(reversed(groups)), FRACTIONS, "one")
    assert first != assign_splits(groups, FRACTIONS, "two")


def test_thin_splits_are_reported() -> None:
    counts = {("rgb", "drone"): Counter(test=5), ("rgb", "bird"): Counter(test=2)}
    assert splits_too_thin(counts, "test", 3) == ["rgb bird: 2 test clips"]


def test_hamming_counts_differing_bits() -> None:
    assert hamming(signature(3), signature(0)) == 3
    assert hamming(signature(3), signature(3)) == 0
    assert hamming(signature(1, start=0), signature(1, start=5)) == 2


def test_lookalike_pairs_only_compare_the_two_named_splits() -> None:
    signatures = {
        "a": signature(4),
        "b": signature(3),
        "c": signature(0),
        "d": signature(4),
    }
    splits = {"a": "train", "b": "test", "c": "test", "d": "val"}
    assert lookalike_pairs(signatures, splits, "train", "test", 1) == [("a", "b")]


def test_exact_copies_are_dropped_keeping_the_first_path() -> None:
    entries = [
        {"path": "B_019.wav", "sha256": "same"},
        {"path": "B_010.wav", "sha256": "same"},
        {"path": "B_011.wav", "sha256": "other"},
    ]
    kept, excluded = drop_exact_copies(entries)
    assert [e["path"] for e in kept] == ["B_010.wav", "B_011.wav"]
    assert excluded == [{"path": "B_019.wav", "reason": "exact copy of B_010.wav"}]
