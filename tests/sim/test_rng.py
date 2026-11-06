from cuas.sim.rng import stream


def draws(*args: object) -> list[float]:
    return stream(*args).random(5).tolist()  # type: ignore[arg-type]


def test_same_seed_and_names_repeat() -> None:
    assert draws(7, "bearing", "st1") == draws(7, "bearing", "st1")


def test_seed_changes_the_stream() -> None:
    assert draws(7, "bearing", "st1") != draws(8, "bearing", "st1")


def test_each_name_gets_its_own_stream() -> None:
    assert draws(7, "bearing", "st1") != draws(7, "bearing", "st2")


def test_name_order_matters() -> None:
    assert draws(7, "a", "b") != draws(7, "b", "a")


def test_drawing_from_one_stream_does_not_disturb_another() -> None:
    first = stream(7, "bearing", "st1")
    expected = first.random(3).tolist()
    noisy_neighbour = stream(7, "bearing", "st2")
    second = stream(7, "bearing", "st1")
    noisy_neighbour.random(1000)
    assert second.random(3).tolist() == expected
