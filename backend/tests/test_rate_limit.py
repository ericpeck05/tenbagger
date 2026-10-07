import threading
import time

from app.providers.base import RateLimiter


def test_spaces_calls_at_the_rate():
    limiter = RateLimiter(rate=20, per=1.0)  # one every 50 ms
    start = time.monotonic()
    for _ in range(5):
        limiter.wait()
    assert time.monotonic() - start >= 0.18  # first call is free, then 4 x 50 ms


def test_background_reserve_leaves_tokens_for_foreground_calls():
    limiter = RateLimiter(rate=10, per=1.0, burst=4)
    # Background work drains the bucket down to its reserve of 3 ...
    limiter.wait(reserve=3)
    # ... so a foreground call still gets a token immediately.
    start = time.monotonic()
    limiter.wait()
    assert time.monotonic() - start < 0.02


def test_background_waits_when_only_reserve_is_left():
    limiter = RateLimiter(rate=10, per=1.0, burst=4)
    limiter.wait(reserve=3)
    done = threading.Event()
    threading.Thread(target=lambda: (limiter.wait(reserve=3), done.set()), daemon=True).start()
    assert not done.wait(0.05)  # needs a refill first (100 ms per token)
    assert done.wait(0.5)
