"""Publisher tests: bounded queue, critical retention, nonblocking, bounded retry."""

import threading
import time

from wheelway_bridge.publisher import NoOpPublisher, Publisher


class _Resp:
    def __init__(self, status_code=201):
        self.status_code = status_code


def test_submit_never_blocks_when_backend_unavailable():
    done = threading.Event()

    def boom(url, json, headers, timeout):
        done.set()
        raise ConnectionError("backend down")

    pub = Publisher("http://127.0.0.1:5999", post_fn=boom, queue_size=5)
    pub.start()
    t0 = time.time()
    assert pub.submit({"hello": "world"}, critical=True) is True
    # submit returns immediately regardless of the (failing) network worker.
    assert time.time() - t0 < 0.2
    assert done.wait(2.0)
    pub.stop()
    assert pub.last_attempt_ok is False  # failed, but pipeline never blocked


def test_bounded_retry_for_critical():
    calls = {"n": 0}
    reached = threading.Event()

    def boom(url, json, headers, timeout):
        calls["n"] += 1
        if calls["n"] >= 3:
            reached.set()
        raise TimeoutError("slow")

    pub = Publisher("http://x", post_fn=boom, queue_size=5, max_critical_retries=2)
    pub.start()
    pub.submit({"a": 1}, critical=True)
    reached.wait(2.0)
    pub.stop()
    # 1 initial + 2 retries == 3 attempts, then it gives up (no infinite loop).
    assert calls["n"] == 3


def test_successful_delivery_posts_observation():
    seen = []
    got = threading.Event()

    def ok(url, json, headers, timeout):
        seen.append((url, json))
        got.set()
        return _Resp(201)

    pub = Publisher("http://host:5000", post_fn=ok)
    pub.start()
    pub.submit({"source": "vision_modal"}, critical=False)
    assert got.wait(2.0)
    pub.stop()
    assert seen[0][0].endswith("/observations")
    assert seen[0][1]["source"] == "vision_modal"
    assert pub.last_attempt_ok is True


def test_queue_full_preserves_newest_critical():
    # Worker NOT started -> queue accumulates so we can assert eviction policy.
    pub = Publisher("http://x", post_fn=lambda *a, **k: _Resp(), queue_size=2)
    pub.submit({"n": "A"}, critical=False)
    pub.submit({"n": "B"}, critical=False)            # full: [A, B]
    pub.submit({"n": "C"}, critical=True)             # evict oldest non-crit A -> [B, C]
    pub.submit({"n": "D"}, critical=False)            # evict oldest non-crit B -> [C, D]
    names = [obs["n"] for obs, _crit in pub._q]
    assert "C" in names                                # newest critical retained
    assert "A" not in names and "B" not in names


def test_noncritical_does_not_displace_critical_when_full():
    pub = Publisher("http://x", post_fn=lambda *a, **k: _Resp(), queue_size=1)
    assert pub.submit({"n": "C"}, critical=True) is True   # [C]
    assert pub.submit({"n": "X"}, critical=False) is False  # dropped, critical kept
    names = [obs["n"] for obs, _crit in pub._q]
    assert names == ["C"]
    assert pub.dropped == 1


def test_noop_publisher_is_disabled():
    pub = NoOpPublisher()
    assert pub.submit({"x": 1}) is False
    pub.start(); pub.stop()  # no-ops
