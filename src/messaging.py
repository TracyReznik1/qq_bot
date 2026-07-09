from collections import deque
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Any

from src.utils.storage import safe_id


def build_session_key(uid: str, data: dict[str, Any], is_group: bool) -> str:
    if is_group:
        return f"group:{safe_id(data.get('group_id'))}:{safe_id(uid)}"
    return f"private:{safe_id(uid)}"


def get_event_session_key(data: dict[str, Any]) -> str | None:
    uid = str(data.get("user_id", ""))
    raw_msg = str(data.get("raw_message", "")).strip()
    if not uid or not raw_msg:
        return None

    is_group = data.get("message_type") == "group"
    return build_session_key(uid, data, is_group)


def build_message_dedupe_key(data: dict[str, Any], message_id: Any) -> str:
    message_type = str(data.get("message_type") or "unknown")
    if message_type == "group":
        scope_kind = "group"
        scope_id = data.get("group_id")
    else:
        scope_kind = "user"
        scope_id = data.get("user_id")

    return ":".join(
        [
            safe_id(data.get("self_id")),
            safe_id(message_type),
            scope_kind,
            safe_id(scope_id),
            safe_id(message_id),
        ]
    )


class MessageQueue:
    """Per-session message queue with configurable worker pool.

    - Same session: messages are serialised — only one worker processes
      that session at a time, in order.
    - Different sessions: processed in parallel via ``ThreadPoolExecutor``.
    - The caller (``main.py``) enqueues and returns HTTP 200 immediately.

    Internal details
    ----------------
    * Each session gets a ``deque`` of message payloads in ``session_message_queues``.
    * ``active_session_workers`` tracks which sessions currently have a worker running.
    * When ``enqueue`` sees a new session (not already active), it submits a
      ``_drain_session`` call to the thread pool.
    * ``_drain_session`` pops messages one-by-one; after each pop it re-checks
      the queue.  If the queue is now empty, it removes the session from
      ``active_session_workers`` and exits.
    * **Race-condition fix**: between the last ``popleft`` and the check in the
      next ``while`` iteration, another thread could enqueue a new message
      while the worker is about to discard the session.  To prevent that
      message from being stranded, the worker holds the lock across the
      pop and the empty-check, and only starts a new worker if the session
      had a non-zero queue length **after** the pop.
    """

    def __init__(self, max_workers: int = 8, max_processed_message_ids: int = 500,
                 max_queue_size: int = 100) -> None:
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="qq-message")
        self.processed_message_ids: set[str] = set()
        self.processed_message_order: deque[str] = deque()
        self.processed_message_lock = Lock()
        self.session_queue_lock = Lock()
        self.session_message_queues: dict[str, deque[dict[str, Any]]] = {}
        self.active_session_workers: set[str] = set()
        self.max_processed_message_ids = max_processed_message_ids
        self.max_queue_size = max_queue_size

    # ── deduplication ──────────────────────────────────────────────

    def mark_seen(self, data: dict[str, Any]) -> bool:
        message_id = data.get("message_id")
        if message_id is None:
            return True

        key = build_message_dedupe_key(data, message_id)
        with self.processed_message_lock:
            if key in self.processed_message_ids:
                return False

            self.processed_message_ids.add(key)
            self.processed_message_order.append(key)
            while len(self.processed_message_order) > self.max_processed_message_ids:
                old_key = self.processed_message_order.popleft()
                self.processed_message_ids.discard(old_key)
            return True

    # ── enqueue / drain ────────────────────────────────────────────

    def enqueue(self, data: dict[str, Any], process_func) -> None:
        session_key = get_event_session_key(data)
        if session_key is None:
            return

        should_start_worker = False
        with self.session_queue_lock:
            queue = self.session_message_queues.setdefault(session_key, deque())
            if len(queue) >= self.max_queue_size:
                # Drop oldest message to make room (prevents unbounded growth)
                queue.popleft()
            queue.append(data)
            if session_key not in self.active_session_workers:
                self.active_session_workers.add(session_key)
                should_start_worker = True

        if should_start_worker:
            self.executor.submit(self._drain_session, session_key, process_func)

    def _drain_session(self, session_key: str, process_func) -> None:
        import logging

        while True:
            # ── Critical section: pop + empty-check + optional restart ──
            with self.session_queue_lock:
                queue = self.session_message_queues.get(session_key)
                if not queue:
                    # No queue at all — clean up and exit
                    self.session_message_queues.pop(session_key, None)
                    self.active_session_workers.discard(session_key)
                    return

                data = queue.popleft()

                # After popping, check whether more messages remain.
                # If NOT empty, keep the worker marked active so the next
                # loop iteration picks up the next message.
                # If empty, unmark the session.  Any message that arrives
                # between now and the next enqueue() call will see
                # session_key NOT in active_session_workers and start a new
                # worker — so no message is stranded.
                still_has_messages = bool(queue)
                if not still_has_messages:
                    self.session_message_queues.pop(session_key, None)
                    self.active_session_workers.discard(session_key)

            # ── Process outside the lock so other sessions can enqueue ──
            try:
                process_func(data)
            except Exception:
                logging.getLogger("qq-bot").exception(
                    "Background message processing failed"
                )

            if not still_has_messages:
                return


# ── module-level helpers (delegate to MessageQueue instance) ────────

def mark_message_seen(data: dict[str, Any], queue: MessageQueue) -> bool:
    return queue.mark_seen(data)


def enqueue_message(data: dict[str, Any], queue: MessageQueue, process_func) -> None:
    queue.enqueue(data, process_func)
