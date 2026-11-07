import hashlib
import json
from pathlib import Path

from cuas.station.recorder import Recorder, verify_recordings


def test_a_recording_is_stored_with_its_known_hash(tmp_path: Path) -> None:
    digest = Recorder(tmp_path).save("st1", "abcd", ".mp4", b"abc")
    expected = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert digest == expected
    assert (tmp_path / "station_st1" / "abcd.mp4").read_bytes() == b"abc"
    hashes = json.loads((tmp_path / "station_st1" / "hashes.json").read_text("utf-8"))
    assert hashes == {"abcd.mp4": expected}


def test_each_file_gets_its_own_hash(tmp_path: Path) -> None:
    recorder = Recorder(tmp_path)
    recorder.save("st1", "aaaa", ".mp4", b"one")
    recorder.save("st1", "bbbb", ".wav", b"two")
    hashes = json.loads((tmp_path / "station_st1" / "hashes.json").read_text("utf-8"))
    assert hashes == {
        "aaaa.mp4": hashlib.sha256(b"one").hexdigest(),
        "bbbb.wav": hashlib.sha256(b"two").hexdigest(),
    }


def test_each_station_has_its_own_folder(tmp_path: Path) -> None:
    recorder = Recorder(tmp_path)
    recorder.save("st1", "aaaa", ".mp4", b"one")
    recorder.save("pk4", "aaaa", ".mp4", b"one")
    assert (tmp_path / "station_st1" / "aaaa.mp4").exists()
    assert (tmp_path / "station_pk4" / "aaaa.mp4").exists()


def test_untouched_recordings_verify(tmp_path: Path) -> None:
    Recorder(tmp_path).save("st1", "abcd", ".mp4", b"abc")
    assert verify_recordings(tmp_path) == []


def test_changing_one_byte_fails_verification(tmp_path: Path) -> None:
    Recorder(tmp_path).save("st1", "abcd", ".mp4", b"abc")
    path = tmp_path / "station_st1" / "abcd.mp4"
    path.write_bytes(b"abd")
    problems = verify_recordings(tmp_path)
    assert len(problems) == 1
    assert "hash mismatch" in problems[0]


def test_a_deleted_recording_fails_verification(tmp_path: Path) -> None:
    Recorder(tmp_path).save("st1", "abcd", ".mp4", b"abc")
    (tmp_path / "station_st1" / "abcd.mp4").unlink()
    assert "missing" in verify_recordings(tmp_path)[0]
