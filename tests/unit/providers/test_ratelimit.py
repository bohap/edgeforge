import pytest

from edgeforge.providers.ratelimit import RateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_first_request_is_immediate_then_spaced_by_rate() -> None:
    clock = FakeClock()
    limiter = RateLimiter(0.5, clock=clock, sleep=clock.sleep)

    for _ in range(3):
        limiter.acquire()

    assert clock.sleeps == pytest.approx([2.0, 2.0])


def test_idle_time_refills_up_to_burst() -> None:
    clock = FakeClock()
    limiter = RateLimiter(1.0, burst=2, clock=clock, sleep=clock.sleep)
    limiter.acquire()
    limiter.acquire()

    clock.now += 10
    limiter.acquire()
    limiter.acquire()
    limiter.acquire()

    assert clock.sleeps == pytest.approx([1.0])


def test_partial_refill_waits_only_for_the_remainder() -> None:
    clock = FakeClock()
    limiter = RateLimiter(1.0, clock=clock, sleep=clock.sleep)
    limiter.acquire()

    clock.now += 0.25
    limiter.acquire()

    assert clock.sleeps == pytest.approx([0.75])


@pytest.mark.parametrize(("rate", "burst"), [(0, 1), (-1, 1), (1, 0)])
def test_rejects_invalid_configuration(rate: float, burst: int) -> None:
    with pytest.raises(ValueError, match="must be"):
        RateLimiter(rate, burst)
