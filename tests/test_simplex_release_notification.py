import contextlib
import importlib.util
import io
import json
import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

SCRIPT = Path(__file__).parents[1] / ".github" / "scripts" / "notify_simplex.py"
SPEC = importlib.util.spec_from_file_location("notify_simplex", SCRIPT)
notify_simplex = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(notify_simplex)


class Response:
    def __init__(self, status=200, body=None):
        self.status = status
        self.body = json.dumps(body).encode("utf-8") if body is not None else b""

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


class SimplexReleaseNotificationTests(unittest.TestCase):
    base_env = {
        "SIMPLEX_WEBHOOK_URL": "https://webhook.invalid/simplex",
        "SIMPLEX_WEBHOOK_TOKEN": "synthetic-token",
        "VERSION": "1.2.3",
        "GH_REPO": "owner/repo",
        "RELEASE_TAG": "stable",
        "RELEASE_COMMIT": "ignored-stable-commit",
        "GHCR_ENDPOINT": "ghcr.io/owner/quasarr",
    }

    def run_script(
        self, *, response=None, gh_stdout=None, env=None, urlopen_side_effect=None
    ):
        values = {**self.base_env, **(env or {})}
        gh = Mock(
            returncode=0,
            stdout=gh_stdout or json.dumps({"url": "https://releases.invalid/example"}),
        )
        output = io.StringIO()
        with (
            patch.dict(os.environ, values, clear=True),
            patch.object(notify_simplex.subprocess, "run", return_value=gh) as run,
            patch.object(
                notify_simplex.urllib.request,
                "urlopen",
                return_value=(response or Response(body={"status": "accepted_by_smp"})),
                side_effect=urlopen_side_effect,
            ) as send,
            contextlib.redirect_stdout(output),
        ):
            try:
                notify_simplex.main()
            except SystemExit as error:
                return error.code, output.getvalue(), run, send
        return 0, output.getvalue(), run, send

    def request_body(self, send):
        request = send.call_args.args[0]
        return request, json.loads(request.data.decode("utf-8"))

    def test_stable_message_uses_release_link_latest_and_upgrade(self):
        code, output, _run, send = self.run_script()

        self.assertEqual(0, code)
        self.assertIn("SimpleX notification accepted by SMP.", output)
        request, body = self.request_body(send)
        self.assertEqual({"text": body["text"]}, body)
        self.assertEqual("Bearer synthetic-token", request.get_header("Authorization"))
        self.assertEqual("application/json", request.get_header("Content-type"))
        self.assertEqual(
            "Quasarr-release-notifier/1.0", request.get_header("User-agent")
        )
        self.assertIn("🚀 Quasarr stable released", body["text"])
        self.assertIn("https://releases.invalid/example", body["text"])
        self.assertIn("docker pull ghcr.io/owner/quasarr:latest", body["text"])
        self.assertIn("uv tool upgrade quasarr", body["text"])
        self.assertNotIn("ignored-stable-commit", body["text"])
        self.assertLessEqual(len(request.get_header("Idempotency-key")), 256)

    def test_beta_message_uses_beta_image_download_instruction_and_commit(self):
        code, _output, _run, send = self.run_script(
            env={"RELEASE_TAG": "beta", "RELEASE_COMMIT": "abcdef1234567890"}
        )

        self.assertEqual(0, code)
        _request, body = self.request_body(send)
        self.assertIn("🚀 Quasarr 1.2.3 beta available", body["text"])
        self.assertIn("docker pull ghcr.io/owner/quasarr:beta", body["text"])
        self.assertIn("Download from release page above.", body["text"])
        self.assertIn("Commit:\nabcdef1", body["text"])

    def test_pending_response_reports_pending_after_valid_response(self):
        code, output, _run, send = self.run_script(
            response=Response(202, {"status": "pending"})
        )

        self.assertEqual(0, code)
        self.assertIn("SimpleX notification pending.", output)
        self.assertNotIn("accepted by SMP", output)
        self.request_body(send)

    def test_stable_rerun_reuses_key_and_ignores_commit(self):
        first = self.run_script()[3]
        second = self.run_script(env={"RELEASE_COMMIT": "different-commit"})[3]

        first_request, first_body = self.request_body(first)
        second_request, second_body = self.request_body(second)
        self.assertEqual(
            first_request.get_header("Idempotency-key"),
            second_request.get_header("Idempotency-key"),
        )
        self.assertEqual(first_body, second_body)

    def test_beta_commit_change_changes_key(self):
        first = self.run_script(
            env={"RELEASE_TAG": "beta", "RELEASE_COMMIT": "abcdef1234567890"}
        )[3]
        second = self.run_script(
            env={"RELEASE_TAG": "beta", "RELEASE_COMMIT": "fedcba0987654321"}
        )[3]

        first_request, _first_body = self.request_body(first)
        second_request, _second_body = self.request_body(second)
        self.assertNotEqual(
            first_request.get_header("Idempotency-key"),
            second_request.get_header("Idempotency-key"),
        )

    def test_missing_secret_skips_metadata_lookup_and_send(self):
        code, output, run, send = self.run_script(env={"SIMPLEX_WEBHOOK_TOKEN": ""})

        self.assertEqual(0, code)
        self.assertIn("configuration missing", output)
        run.assert_not_called()
        send.assert_not_called()

    def test_beta_without_commit_fails_before_metadata_lookup_or_send(self):
        code, output, run, send = self.run_script(
            env={"RELEASE_TAG": "beta", "RELEASE_COMMIT": ""}
        )

        self.assertEqual(1, code)
        self.assertIn("beta release commit missing", output)
        run.assert_not_called()
        send.assert_not_called()

    def test_metadata_failure_does_not_send_or_leak_endpoint_or_token(self):
        gh = Mock(returncode=1, stdout="", stderr="private details")
        with (
            patch.object(notify_simplex.subprocess, "run", return_value=gh),
            patch.object(notify_simplex.urllib.request, "urlopen") as send,
            patch.dict(os.environ, {**self.base_env}, clear=True),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            with self.assertRaises(SystemExit) as raised:
                notify_simplex.main()

        self.assertEqual(1, raised.exception.code)
        self.assertNotIn(self.base_env["SIMPLEX_WEBHOOK_URL"], output.getvalue())
        self.assertNotIn(self.base_env["SIMPLEX_WEBHOOK_TOKEN"], output.getvalue())
        send.assert_not_called()

    def test_invalid_metadata_json_fails_without_send(self):
        code, output, _run, send = self.run_script(gh_stdout="not-json")

        self.assertEqual(1, code)
        self.assertIn("invalid release metadata", output)
        send.assert_not_called()

    def test_http_failure_invalid_json_and_unexpected_status_fail_without_success(self):
        cases = [
            (
                notify_simplex.urllib.error.HTTPError(
                    "https://webhook.invalid", 500, "", {}, None
                ),
                "HTTP 500",
            ),
            (Response(200, None), "unexpected 200 response"),
            (Response(418, {"status": "accepted_by_smp"}), "unexpected HTTP 418"),
        ]
        for response, expected in cases:
            with self.subTest(expected=expected):
                code, output, _run, _send = self.run_script(
                    urlopen_side_effect=response
                    if isinstance(response, Exception)
                    else None,
                    response=None if isinstance(response, Exception) else response,
                )
                self.assertEqual(1, code)
                self.assertIn(expected, output)
                self.assertNotIn("SimpleX notification accepted by SMP.", output)
                self.assertNotIn(self.base_env["SIMPLEX_WEBHOOK_TOKEN"], output)
                self.assertNotIn(self.base_env["SIMPLEX_WEBHOOK_URL"], output)


if __name__ == "__main__":
    unittest.main()
