# -*- coding: utf-8 -*-

import threading
import unittest
from unittest.mock import MagicMock, patch

from quasarr.providers import cloudflare


class _Response:
    def __init__(self, status_code=200, status="ok", session=None, sessions=None):
        self.status_code = status_code
        self._status = status
        self._session = session
        self._sessions = sessions

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        result = {"status": self._status}
        if self._session is not None:
            result["session"] = self._session
        if self._sessions is not None:
            result["sessions"] = self._sessions
        return result


class CloudflareSessionCleanupTests(unittest.TestCase):
    def setUp(self):
        with cloudflare._session_cleanup_condition:
            self.assertFalse(cloudflare._session_cleanup_worker_running)
            cloudflare._session_cleanup_pending.clear()

    def tearDown(self):
        with cloudflare._session_cleanup_condition:
            self.assertFalse(cloudflare._session_cleanup_pending)
            self.assertFalse(cloudflare._session_cleanup_worker_running)

    def _state(self):
        state = MagicMock()
        state.values = {"config": lambda section: {"url": "http://solver.invalid/v1"}}
        return state

    def test_create_uses_explicit_uuid_and_queues_failed_create(self):
        with (
            patch.object(cloudflare, "is_flaresolverr_available", return_value=True),
            patch.object(cloudflare.requests, "post", side_effect=TimeoutError) as post,
            patch.object(cloudflare, "_schedule_session_cleanup") as schedule,
            patch.object(cloudflare.uuid, "uuid4", return_value="generated-id"),
        ):
            result = cloudflare.flaresolverr_create_session(self._state())

        self.assertIsNone(result)
        schedule.assert_called_once_with("http://solver.invalid/v1", "generated-id")
        self.assertEqual("generated-id", post.call_args.kwargs["json"]["session"])

    def test_successful_create_does_not_queue_cleanup(self):
        response = _Response(session="explicit-id")
        with (
            patch.object(cloudflare, "is_flaresolverr_available", return_value=True),
            patch.object(cloudflare.requests, "post", return_value=response) as post,
            patch.object(cloudflare, "_schedule_session_cleanup") as schedule,
        ):
            result = cloudflare.flaresolverr_create_session(
                self._state(), "explicit-id"
            )

        self.assertEqual("explicit-id", result)
        schedule.assert_not_called()
        self.assertEqual("explicit-id", post.call_args.kwargs["json"]["session"])

    def test_explicit_failed_create_queues_same_uuid(self):
        with (
            patch.object(cloudflare, "is_flaresolverr_available", return_value=True),
            patch.object(cloudflare.requests, "post", side_effect=TimeoutError) as post,
            patch.object(cloudflare, "_schedule_session_cleanup") as schedule,
        ):
            result = cloudflare.flaresolverr_create_session(
                self._state(), "failed-explicit-id"
            )

        self.assertIsNone(result)
        self.assertEqual("failed-explicit-id", post.call_args.kwargs["json"]["session"])
        schedule.assert_called_once_with(
            "http://solver.invalid/v1", "failed-explicit-id"
        )

    def test_success_without_session_id_is_queued_as_uncertain(self):
        with (
            patch.object(cloudflare, "is_flaresolverr_available", return_value=True),
            patch.object(cloudflare.requests, "post", return_value=_Response()),
            patch.object(cloudflare, "_schedule_session_cleanup") as schedule,
        ):
            result = cloudflare.flaresolverr_create_session(
                self._state(), "missing-result-id"
            )

        self.assertIsNone(result)
        schedule.assert_called_once_with(
            "http://solver.invalid/v1", "missing-result-id"
        )

    def test_worker_start_failure_does_not_leave_stuck_pending_item(self):
        with patch.object(cloudflare, "threading") as threading_module:
            threading_module.Thread.return_value.start.side_effect = RuntimeError
            cloudflare._schedule_session_cleanup(
                "http://solver.invalid/v1", "start-failed-id"
            )

        with cloudflare._session_cleanup_condition:
            self.assertFalse(cloudflare._session_cleanup_pending)
            self.assertFalse(cloudflare._session_cleanup_worker_running)

    def test_late_registration_after_201_seconds_is_eventually_destroyed(self):
        clock = [0.0]
        calls = []

        def wait(seconds):
            clock[0] += seconds

        def post(url, **kwargs):
            calls.append(kwargs["json"]["cmd"])
            if clock[0] < 201:
                return _Response(sessions=[])
            if kwargs["json"]["cmd"] == "sessions.list":
                return _Response(sessions=["very-late-id"])
            return _Response()

        with (
            patch.object(cloudflare.threading.Thread, "start"),
            patch.object(cloudflare.time, "monotonic", side_effect=lambda: clock[0]),
            patch.object(
                cloudflare._session_cleanup_condition, "wait", side_effect=wait
            ),
            patch.object(cloudflare.requests, "post", side_effect=post),
        ):
            cloudflare._schedule_session_cleanup(
                "http://solver.invalid/v1", "very-late-id"
            )
            cloudflare._session_cleanup_worker()

        self.assertGreaterEqual(clock[0], 201)
        self.assertEqual(1, calls.count("sessions.destroy"))

    def test_pending_cleanup_stops_at_600_second_deadline(self):
        clock = [0.0]
        calls = []
        timeouts = []

        def wait(seconds):
            clock[0] += seconds

        def post(url, **kwargs):
            calls.append(kwargs["json"]["cmd"])
            timeouts.append((kwargs["timeout"], clock[0]))
            return _Response(sessions=[])

        with (
            patch.object(cloudflare.threading.Thread, "start"),
            patch.object(cloudflare.time, "monotonic", side_effect=lambda: clock[0]),
            patch.object(
                cloudflare._session_cleanup_condition, "wait", side_effect=wait
            ),
            patch.object(cloudflare.requests, "post", side_effect=post),
            patch.object(cloudflare, "SESSION_REQUEST_TIMEOUT_SECONDS", 1000),
            patch.object(cloudflare, "warn") as warning,
        ):
            cloudflare._schedule_session_cleanup(
                "http://solver.invalid/v1", "deadline-id"
            )
            cloudflare._session_cleanup_worker()

        self.assertEqual(600, clock[0])
        self.assertNotIn("sessions.destroy", calls)
        self.assertTrue(all(timeout <= 600 - at for timeout, at in timeouts))
        warning.assert_called_once()

    def test_destroy_timeout_uses_remaining_deadline_after_list(self):
        clock = [0.0]
        destroy_timeout = []

        def wait(seconds):
            clock[0] += seconds

        def post(url, **kwargs):
            if kwargs["json"]["cmd"] == "sessions.list":
                clock[0] += 5
                return _Response(sessions=["remaining-id"])
            destroy_timeout.append(kwargs["timeout"])
            return _Response()

        with (
            patch.object(cloudflare.threading.Thread, "start"),
            patch.object(cloudflare.time, "monotonic", side_effect=lambda: clock[0]),
            patch.object(
                cloudflare._session_cleanup_condition, "wait", side_effect=wait
            ),
            patch.object(cloudflare.requests, "post", side_effect=post),
            patch.object(cloudflare, "SESSION_REQUEST_TIMEOUT_SECONDS", 1000),
        ):
            cloudflare._schedule_session_cleanup(
                "http://solver.invalid/v1", "remaining-id"
            )
            cloudflare._session_cleanup_worker()

        self.assertEqual([297], destroy_timeout)

    def test_due_second_id_is_cleaned_while_first_id_is_backing_off(self):
        clock = [0.0]
        first_pending_during_second = []

        def wait(seconds):
            clock[0] += seconds

        # sessions.list has no session field, so identify the current item by
        # observing call order: first-id is absent, second-id is registered.
        list_count = [0]

        def fair_post(url, **kwargs):
            if kwargs["json"]["cmd"] == "sessions.list":
                list_count[0] += 1
                if list_count[0] == 1:
                    return _Response(sessions=[])
                return _Response(sessions=["second-id"])
            with cloudflare._session_cleanup_condition:
                first_pending_during_second.append(
                    ("http://solver.invalid/v1", "first-id")
                    in cloudflare._session_cleanup_pending
                )
            return _Response()

        with (
            patch.object(cloudflare.threading.Thread, "start"),
            patch.object(cloudflare.time, "monotonic", side_effect=lambda: clock[0]),
            patch.object(
                cloudflare._session_cleanup_condition, "wait", side_effect=wait
            ),
            patch.object(cloudflare.requests, "post", side_effect=fair_post),
        ):
            cloudflare._schedule_session_cleanup("http://solver.invalid/v1", "first-id")
            cloudflare._schedule_session_cleanup(
                "http://solver.invalid/v1", "second-id"
            )
            cloudflare._session_cleanup_worker()

        self.assertEqual([True], first_pending_during_second)

    def test_burst_of_eleven_ids_does_not_starve_the_tail(self):
        clock = [0.0]
        session_ids = [f"burst-{index}" for index in range(11)]
        destroyed = []
        list_calls = 0

        def wait(seconds):
            clock[0] += seconds

        def post(url, **kwargs):
            if kwargs["json"]["cmd"] == "sessions.list":
                nonlocal list_calls
                list_calls += 1
                clock[0] += 29
                return _Response(sessions=session_ids)
            destroyed.append(kwargs["json"]["session"])
            clock[0] += min(29, kwargs["timeout"])
            if kwargs["timeout"] < 29:
                raise TimeoutError("destroy response exceeded timeout")
            return _Response()

        with (
            patch.object(cloudflare.threading.Thread, "start"),
            patch.object(cloudflare.time, "monotonic", side_effect=lambda: clock[0]),
            patch.object(
                cloudflare._session_cleanup_condition, "wait", side_effect=wait
            ),
            patch.object(cloudflare.requests, "post", side_effect=post),
            patch.object(cloudflare, "warn") as warning,
        ):
            for session_id in session_ids:
                cloudflare._schedule_session_cleanup(
                    "http://solver.invalid/v1", session_id
                )
            cloudflare._session_cleanup_worker()

        self.assertEqual(session_ids, destroyed)
        self.assertEqual(1, list_calls)
        self.assertLess(clock[0], 600)
        warning.assert_not_called()

    def test_large_burst_keeps_destroy_attempts_fair_after_lost_replies(self):
        clock = [0.0]
        session_ids = [f"large-{index}" for index in range(40)]
        server_sessions = set(session_ids)
        destroyed = []
        list_calls = 0

        def wait(seconds):
            clock[0] += seconds

        def post(url, **kwargs):
            if kwargs["json"]["cmd"] == "sessions.list":
                nonlocal list_calls
                list_calls += 1
                clock[0] += 29
                return _Response(sessions=list(server_sessions))
            session_id = kwargs["json"]["session"]
            server_sessions.discard(session_id)
            destroyed.append(session_id)
            clock[0] += min(29, kwargs["timeout"])
            if kwargs["timeout"] < 29:
                raise TimeoutError("destroy response exceeded its fair timeout")
            return _Response()

        with (
            patch.object(cloudflare.threading.Thread, "start"),
            patch.object(cloudflare.time, "monotonic", side_effect=lambda: clock[0]),
            patch.object(
                cloudflare._session_cleanup_condition, "wait", side_effect=wait
            ),
            patch.object(cloudflare.requests, "post", side_effect=post),
            patch.object(cloudflare, "warn") as warning,
        ):
            for session_id in session_ids:
                cloudflare._schedule_session_cleanup(
                    "http://solver.invalid/v1", session_id
                )
            cloudflare._session_cleanup_worker()

        self.assertEqual(session_ids, destroyed)
        self.assertEqual(set(), server_sessions)
        self.assertEqual(2, list_calls)
        self.assertLess(clock[0], 600)
        warning.assert_not_called()

    def test_list_batching_does_not_cross_endpoints(self):
        clock = [0.0]
        listed = []
        destroyed = []
        endpoint_a = "http://solver-a.invalid/v1"
        endpoint_b = "http://solver-b.invalid/v1"

        def wait(seconds):
            clock[0] += seconds

        def post(url, **kwargs):
            command = kwargs["json"]["cmd"]
            if command == "sessions.list":
                listed.append(url)
                session = "a-id" if url == endpoint_a else "b-id"
                return _Response(sessions=[session])
            destroyed.append((url, kwargs["json"]["session"]))
            return _Response()

        with (
            patch.object(cloudflare.threading.Thread, "start"),
            patch.object(cloudflare.time, "monotonic", side_effect=lambda: clock[0]),
            patch.object(
                cloudflare._session_cleanup_condition, "wait", side_effect=wait
            ),
            patch.object(cloudflare.requests, "post", side_effect=post),
        ):
            cloudflare._schedule_session_cleanup(endpoint_a, "a-id")
            cloudflare._schedule_session_cleanup(endpoint_b, "b-id")
            cloudflare._session_cleanup_worker()

        self.assertEqual({endpoint_a, endpoint_b}, set(listed))
        self.assertEqual([(endpoint_a, "a-id"), (endpoint_b, "b-id")], destroyed)

    def test_endpoint_burst_cannot_starve_one_pending_other_endpoint(self):
        clock = [0.0]
        endpoint_a = "http://solver-a.invalid/v1"
        endpoint_b = "http://solver-b.invalid/v1"
        a_ids = [f"a-{index}" for index in range(40)]
        b_id = "b-only"
        destroyed = []
        warnings = []

        def wait(seconds):
            clock[0] += seconds

        def post(url, **kwargs):
            command = kwargs["json"]["cmd"]
            if command == "sessions.list":
                clock[0] += 29
                if url == endpoint_a:
                    return _Response(sessions=a_ids)
                return _Response(sessions=[b_id])
            session_id = kwargs["json"]["session"]
            destroyed.append((url, session_id))
            latency = 13.8 if url == endpoint_a else 0.1
            clock[0] += min(latency, kwargs["timeout"])
            return _Response()

        with (
            patch.object(cloudflare.threading.Thread, "start"),
            patch.object(cloudflare.time, "monotonic", side_effect=lambda: clock[0]),
            patch.object(
                cloudflare._session_cleanup_condition, "wait", side_effect=wait
            ),
            patch.object(cloudflare.requests, "post", side_effect=post),
            patch.object(cloudflare, "warn", side_effect=warnings.append),
        ):
            for session_id in a_ids:
                cloudflare._schedule_session_cleanup(endpoint_a, session_id)
            cloudflare._schedule_session_cleanup(endpoint_b, b_id)
            cloudflare._session_cleanup_worker()

        self.assertEqual(
            set(a_ids) | {b_id}, {session_id for _, session_id in destroyed}
        )
        self.assertEqual([], warnings)
        self.assertLess(clock[0], 600)

    def test_two_backlogs_cannot_postpone_a_third_endpoint(self):
        clock = [0.0]
        endpoint_a = "http://solver-a.invalid/v1"
        endpoint_b = "http://solver-b.invalid/v1"
        endpoint_c = "http://solver-c.invalid/v1"
        a_ids = [f"a-{index}" for index in range(40)]
        b_ids = [f"b-{index}" for index in range(40)]
        c_id = "c-only"
        destroyed = []
        warnings = []

        def wait(seconds):
            clock[0] += seconds

        def post(url, **kwargs):
            command = kwargs["json"]["cmd"]
            if command == "sessions.list":
                clock[0] += 29
                if url == endpoint_a:
                    return _Response(sessions=list(a_ids))
                if url == endpoint_b:
                    return _Response(sessions=list(b_ids))
                return _Response(sessions=[c_id])
            session_id = kwargs["json"]["session"]
            destroyed.append((url, session_id))
            latency = 0.1 if url == endpoint_c else 13.8
            clock[0] += min(latency, kwargs["timeout"])
            return _Response()

        with (
            patch.object(cloudflare.threading.Thread, "start"),
            patch.object(cloudflare.time, "monotonic", side_effect=lambda: clock[0]),
            patch.object(
                cloudflare._session_cleanup_condition, "wait", side_effect=wait
            ),
            patch.object(cloudflare.requests, "post", side_effect=post),
            patch.object(cloudflare, "warn", side_effect=warnings.append),
        ):
            for session_id in a_ids:
                cloudflare._schedule_session_cleanup(endpoint_a, session_id)
            for session_id in b_ids:
                cloudflare._schedule_session_cleanup(endpoint_b, session_id)
            cloudflare._schedule_session_cleanup(endpoint_c, c_id)
            cloudflare._session_cleanup_worker()

        self.assertEqual(
            set(a_ids) | set(b_ids) | {c_id},
            {session_id for _, session_id in destroyed},
        )
        self.assertEqual([], warnings)
        self.assertLess(clock[0], 600)

    def test_absence_before_registration_does_not_finish_cleanup(self):
        first_cleanup = _Response(sessions=[])
        second_cleanup = _Response(sessions=["late-id"])
        calls = []

        def post(url, **kwargs):
            calls.append(kwargs["json"])
            if kwargs["json"]["cmd"] == "sessions.create":
                raise TimeoutError
            if len(calls) == 2:
                response = first_cleanup
            elif len(calls) == 3:
                response = second_cleanup
            else:
                response = _Response(sessions=[])
            if kwargs["json"]["cmd"] == "sessions.destroy":
                return _Response()
            return response

        with (
            patch.object(cloudflare.threading.Thread, "start"),
            patch.object(cloudflare.requests, "post", side_effect=post),
            patch.object(cloudflare, "is_flaresolverr_available", return_value=True),
            patch.object(cloudflare, "_SESSION_CLEANUP_INITIAL_DELAY_SECONDS", 0),
            patch.object(cloudflare, "_SESSION_CLEANUP_MAX_DELAY_SECONDS", 0),
        ):
            self.assertIsNone(
                cloudflare.flaresolverr_create_session(self._state(), "late-id")
            )
            cloudflare._session_cleanup_worker()

        self.assertEqual(
            [
                "sessions.create",
                "sessions.list",
                "sessions.list",
                "sessions.destroy",
            ],
            [call["cmd"] for call in calls],
        )

    def test_cleanup_retries_rejected_json_and_connection_errors(self):
        attempts = 0
        list_attempts = 0

        def post(url, **kwargs):
            nonlocal attempts, list_attempts
            if kwargs["json"]["cmd"] == "sessions.create":
                raise TimeoutError
            if kwargs["json"]["cmd"] == "sessions.list":
                list_attempts += 1
                if list_attempts == 1:
                    return _Response(status="error", sessions=[])
                if list_attempts == 2:
                    return _Response()
                if list_attempts == 3:
                    return _Response(status_code=500)
                if list_attempts == 4:
                    raise ValueError("malformed response")
                return _Response(sessions=["retry-id"])
            attempts += 1
            if attempts == 1:
                return _Response(status_code=200, status="error")
            if attempts == 2:
                raise OSError("connection lost")
            return _Response()

        with (
            patch.object(cloudflare.threading.Thread, "start"),
            patch.object(cloudflare.requests, "post", side_effect=post),
            patch.object(cloudflare, "is_flaresolverr_available", return_value=True),
            patch.object(cloudflare, "_SESSION_CLEANUP_INITIAL_DELAY_SECONDS", 0),
            patch.object(cloudflare, "_SESSION_CLEANUP_MAX_DELAY_SECONDS", 0),
        ):
            cloudflare.flaresolverr_create_session(self._state(), "retry-id")
            cloudflare._session_cleanup_worker()

        self.assertEqual(3, attempts)
        self.assertEqual(7, list_attempts)

    def test_lost_destroy_response_is_confirmed_by_later_absence(self):
        calls = []

        def post(url, **kwargs):
            command = kwargs["json"]["cmd"]
            calls.append(command)
            if command == "sessions.create":
                raise TimeoutError
            if command == "sessions.list":
                if calls.count("sessions.list") == 1:
                    return _Response(sessions=["lost-ack-id"])
                return _Response(sessions=[])
            raise TimeoutError("destroy response was lost")

        with (
            patch.object(cloudflare.threading.Thread, "start"),
            patch.object(cloudflare.requests, "post", side_effect=post),
            patch.object(cloudflare, "is_flaresolverr_available", return_value=True),
            patch.object(cloudflare, "_SESSION_CLEANUP_INITIAL_DELAY_SECONDS", 0),
            patch.object(cloudflare, "_SESSION_CLEANUP_MAX_DELAY_SECONDS", 0),
        ):
            cloudflare.flaresolverr_create_session(self._state(), "lost-ack-id")
            cloudflare._session_cleanup_worker()

        self.assertEqual(
            ["sessions.create", "sessions.list", "sessions.destroy", "sessions.list"],
            calls,
        )

    def test_cleanup_worker_is_shared_by_multiple_ids(self):
        list_entered = threading.Event()
        release_list = threading.Event()
        cleanup_ids = []
        worker_threads = []

        def post(url, **kwargs):
            if kwargs["json"]["cmd"] == "sessions.create":
                raise TimeoutError
            if kwargs["json"]["cmd"] == "sessions.list":
                worker_threads.append(threading.current_thread())
                list_entered.set()
                self.assertTrue(release_list.wait(1))
                return _Response(sessions=["first-id", "second-id"])
            cleanup_ids.append(kwargs["json"]["session"])
            return _Response()

        with (
            patch.object(cloudflare.requests, "post", side_effect=post),
            patch.object(cloudflare, "is_flaresolverr_available", return_value=True),
            patch.object(cloudflare, "_SESSION_CLEANUP_INITIAL_DELAY_SECONDS", 0),
        ):
            cloudflare.flaresolverr_create_session(self._state(), "first-id")
            self.assertTrue(list_entered.wait(1))
            cloudflare.flaresolverr_create_session(self._state(), "second-id")
            active_workers = [
                thread
                for thread in threading.enumerate()
                if thread.name == "flaresolverr-session-cleanup"
            ]
            self.assertEqual(1, len(active_workers))
            release_list.set()
            active_workers[0].join(1)
            self.assertFalse(active_workers[0].is_alive())

        self.assertEqual({"first-id", "second-id"}, set(cleanup_ids))
        self.assertEqual(1, len({thread.ident for thread in worker_threads}))


if __name__ == "__main__":
    unittest.main()
