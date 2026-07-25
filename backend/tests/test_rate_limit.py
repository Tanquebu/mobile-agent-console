from app.services.rate_limit import FixedWindowRateLimiter


def test_rate_limiter_rejects_and_recovers_after_window() -> None:
    now = [10.0]
    limiter = FixedWindowRateLimiter(lambda: now[0])
    assert limiter.check("client", 2, 60) is None
    assert limiter.check("client", 2, 60) is None
    assert limiter.check("client", 2, 60) == 60
    assert limiter.check("other", 2, 60) is None
    now[0] = 70.1
    assert limiter.check("client", 2, 60) is None
