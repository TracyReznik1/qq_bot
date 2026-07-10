"""Tests for session-level concurrency in MessageQueue.

All slow tasks are simulated — no real network or LLM calls.
"""

import threading
import time
import unittest

from src.messaging import (
    MessageQueue,
    build_session_key,
    get_event_session_key,
    build_message_dedupe_key,
)


# ── helpers ────────────────────────────────────────────────────────────

def _msg(user_id, raw_msg, message_type="private", group_id=None, self_id="123", msg_id=None):
    data = {
        "user_id": user_id,
        "raw_message": raw_msg,
        "message_type": message_type,
        "group_id": group_id,
        "self_id": self_id,
        "message_id": msg_id or f"msg_{user_id}_{raw_msg}_{time.time()}",
    }
    return data


# ── tests ──────────────────────────────────────────────────────────────

class SessionKeyTests(unittest.TestCase):
    def test_private_session_key(self):
        data = _msg("10001", "hello")
        sk = get_event_session_key(data)
        self.assertEqual(sk, "private:10001")

    def test_group_session_key(self):
        data = _msg("10001", "hello", message_type="group", group_id="999")
        sk = get_event_session_key(data)
        self.assertEqual(sk, "group:999:10001")

    def test_build_session_key_explicit(self):
        self.assertEqual(build_session_key("42", {}, False), "private:42")
        self.assertEqual(build_session_key("42", {"group_id": "888"}, True), "group:888:42")


class DeduplicationTests(unittest.TestCase):
    def test_duplicate_message_id_is_rejected(self):
        q = MessageQueue(max_workers=2)
        data = _msg("1", "A", msg_id="dupe_001")
        self.assertTrue(q.mark_seen(data))
        self.assertFalse(q.mark_seen(data))

    def test_null_message_id_always_accepted(self):
        q = MessageQueue(max_workers=2)
        # Each call with msg_id=None generates a unique dedupe key from
        # the other fields, so every call should return True
        data1 = _msg("1", "A", msg_id=None)
        data2 = _msg("1", "B", msg_id=None)
        self.assertTrue(q.mark_seen(data1))
        self.assertTrue(q.mark_seen(data2))

    def test_null_message_id_with_same_data_returns_false_second_time(self):
        q = MessageQueue(max_workers=2)
        # Same data object → same dedupe key → second call returns False
        data = _msg("1", "A", msg_id=None)
        self.assertTrue(q.mark_seen(data))
        self.assertFalse(q.mark_seen(data))

    def test_old_messages_evicted(self):
        q = MessageQueue(max_workers=2, max_processed_message_ids=3)
        # Insert 5 unique dedupe keys → evicts 0 and 1
        for i in range(5):
            data = {"user_id": str(i), "raw_message": str(i),
                    "message_type": "private", "group_id": None,
                    "self_id": "123", "message_id": f"evict_{i}"}
            q.mark_seen(data)
        # Only keys 2,3,4 remain — re-adding 0 and 1 succeeds (evicted),
        # re-adding 2 fails (still tracked)
        self.assertTrue(q.mark_seen({"user_id": "0", "raw_message": "0",
                                     "message_type": "private", "group_id": None,
                                     "self_id": "123", "message_id": "evict_0"}))
        self.assertFalse(q.mark_seen({"user_id": "0", "raw_message": "0",
                                      "message_type": "private", "group_id": None,
                                      "self_id": "123", "message_id": "evict_0"}))


class SameSessionSerialTests(unittest.TestCase):
    """Messages for the same session must be processed in order."""

    def test_same_session_processed_serially(self):
        results = []
        lock = threading.Lock()

        def process(data):
            with lock:
                results.append(data["raw_message"])
            time.sleep(0.01)

        q = MessageQueue(max_workers=2)
        q.enqueue(_msg("A", "first", msg_id="1"), process)
        q.enqueue(_msg("A", "second", msg_id="2"), process)
        q.enqueue(_msg("A", "third", msg_id="3"), process)

        # Wait for drain to complete
        time.sleep(0.5)
        self.assertEqual(results, ["first", "second", "third"])


class DifferentSessionParallelTests(unittest.TestCase):
    """Messages for different sessions must be processed in parallel."""

    def test_different_sessions_run_in_parallel(self):
        barrier = threading.Barrier(2, timeout=5)
        processed = set()
        lock = threading.Lock()

        def make_process(name):
            def process(data):
                with lock:
                    processed.add(name)
                # Both workers must reach the barrier → proves parallelism
                barrier.wait()
            return process

        q = MessageQueue(max_workers=4)
        q.enqueue(_msg("A", "slow", msg_id="a1"), make_process("A"))
        q.enqueue(_msg("B", "fast", msg_id="b1"), make_process("B"))

        time.sleep(1.0)
        self.assertIn("A", processed)
        self.assertIn("B", processed)


class CallbackQuickReturnTests(unittest.TestCase):
    """enqueue() must return quickly — it must not wait for processing."""

    def test_enqueue_returns_before_processing_completes(self):
        started = threading.Event()
        done = threading.Event()

        def process(data):
            started.set()
            time.sleep(0.5)
            done.set()

        q = MessageQueue(max_workers=2)

        t0 = time.perf_counter()
        q.enqueue(_msg("X", "hello", msg_id="quick"), process)
        elapsed = time.perf_counter() - t0

        # enqueue should return in well under the processing time
        self.assertLess(elapsed, 0.1)
        # Processing should have started (or will start shortly)
        self.assertTrue(started.wait(2))


class SameSessionNoConcurrentWorkerTests(unittest.TestCase):
    """Only one worker may process a given session at a time."""

    def test_enqueue_while_first_message_is_processing_stays_serial(self):
        first_started = threading.Event()
        second_started = threading.Event()
        second_done = threading.Event()
        release_first = threading.Event()
        state_lock = threading.Lock()
        active = 0
        max_active = 0
        order = []

        def process(data):
            nonlocal active, max_active
            with state_lock:
                active += 1
                max_active = max(max_active, active)
                order.append(data["raw_message"])
            try:
                if data["raw_message"] == "first":
                    first_started.set()
                    release_first.wait(timeout=5)
                else:
                    second_started.set()
            finally:
                with state_lock:
                    active -= 1
                if data["raw_message"] == "second":
                    second_done.set()

        q = MessageQueue(max_workers=2)
        try:
            q.enqueue(_msg("R", "first", msg_id="race_1"), process)
            self.assertTrue(first_started.wait(timeout=2))

            q.enqueue(_msg("R", "second", msg_id="race_2"), process)
            q.executor.submit(lambda: None).result(timeout=2)

            self.assertFalse(
                second_started.is_set(),
                "second message started before the first message completed",
            )

            release_first.set()
            self.assertTrue(second_done.wait(timeout=2))
            self.assertEqual(order, ["first", "second"])
            self.assertEqual(max_active, 1)
        finally:
            release_first.set()
            q.executor.shutdown(wait=True)

    def test_same_session_never_has_two_active_workers(self):
        active_counts = []
        lock = threading.Lock()

        def process(data):
            with lock:
                active_counts.append(data["raw_message"])
            time.sleep(0.05)

        q = MessageQueue(max_workers=8)
        for i in range(20):
            q.enqueue(_msg("Z", f"msg_{i}", msg_id=f"z_{i}"), process)

        time.sleep(2.0)
        # Verify all messages were processed in order
        self.assertEqual(len(active_counts), 20)
        self.assertEqual(active_counts, [f"msg_{i}" for i in range(20)])


class QueueMaxSizeTests(unittest.TestCase):
    def test_queue_max_size_drops_oldest(self):
        """Verify that when the queue exceeds max size, oldest messages are dropped.

        Because the worker starts promptly, we need to be careful to
        observe the drop.  We pre-fill 3 messages without a worker
        (session already active), then add a 4th.
        """
        results = []
        started = threading.Event()
        slow_done = threading.Event()

        def process(data):
            started.set()
            results.append(data["raw_message"])
            # Hold the worker open so the queue builds up
            if data["raw_message"] == "1":
                slow_done.wait(timeout=5)

        q = MessageQueue(max_workers=1, max_queue_size=3)
        # First enqueue starts the worker immediately
        q.enqueue(_msg("QQ", "1", msg_id="q1"), process)
        # Wait for worker to start and block on slow_done
        started.wait(5)

        # Now queue more messages while worker is blocked
        q.enqueue(_msg("QQ", "2", msg_id="q2"), process)
        q.enqueue(_msg("QQ", "3", msg_id="q3"), process)
        # Queue is now [2, 3], 1 is being processed
        # Adding a 4th should push it to [2, 3, 4] — still OK
        # Adding a 5th should drop "2"
        q.enqueue(_msg("QQ", "4", msg_id="q4"), process)
        q.enqueue(_msg("QQ", "5", msg_id="q5"), process)

        # Release the worker
        slow_done.set()
        time.sleep(1.5)

        # "1" was processed, "2" should have been dropped
        self.assertIn("1", results)
        self.assertNotIn("2", results)
        # Remaining should be in order
        self.assertEqual(results, results[:1] + sorted(results[1:]))


if __name__ == "__main__":
    unittest.main()
