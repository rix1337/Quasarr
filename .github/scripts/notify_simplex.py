import hashlib
import json
import os
import subprocess
import urllib.error
import urllib.request


def fail(message):
    print(f"::error::SimpleX notification failed: {message}.")
    raise SystemExit(1)


def main():
    endpoint = os.environ.get("SIMPLEX_WEBHOOK_URL", "").strip()
    token = os.environ.get("SIMPLEX_WEBHOOK_TOKEN", "").strip()
    if not endpoint or not token:
        print("::warning::SimpleX notification skipped: webhook configuration missing.")
        return

    version = os.environ["VERSION"]
    repository = os.environ["GH_REPO"]
    tag = os.environ["RELEASE_TAG"]
    is_beta = tag == "beta"
    commit = os.environ.get("RELEASE_COMMIT", "")
    if is_beta and not commit:
        fail("beta release commit missing")
    try:
        release = subprocess.run(
            ["gh", "release", "view", tag, "--repo", repository, "--json", "url"],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        fail("release metadata lookup error")
    if release.returncode != 0:
        fail("release metadata lookup failed")
    try:
        release_url = json.loads(release.stdout)["url"]
    except (KeyError, TypeError, ValueError):
        fail("invalid release metadata")

    title = (
        f"🚀 Quasarr {version} beta available"
        if is_beta
        else f"🚀 Quasarr {tag} released"
    )
    docker_tag = "beta" if is_beta else "latest"
    python_line = (
        "Download from release page above." if is_beta else "uv tool upgrade quasarr"
    )
    message = (
        f"{title}\n\n"
        f"Release notes and downloads:\n{release_url}\n\n"
        f"Docker:\ndocker pull {os.environ['GHCR_ENDPOINT']}:{docker_tag}\n\n"
        f"Python:\n{python_line}"
    )
    if is_beta:
        message += f"\n\nCommit:\n{commit[:7]}"

    identity = f"{repository}:{tag}"
    if is_beta:
        identity += f":{commit}"
    idempotency_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    try:
        request = urllib.request.Request(
            endpoint,
            data=json.dumps({"text": message}).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Idempotency-Key": idempotency_key,
                "User-Agent": "Quasarr-release-notifier/1.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            status = response.status
            response_data = response.read()
    except urllib.error.HTTPError as error:
        fail(f"HTTP {error.code}")
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        fail("webhook request error")

    if status == 200:
        try:
            response_status = json.loads(response_data.decode("utf-8")).get("status")
        except (UnicodeDecodeError, AttributeError, TypeError, ValueError):
            response_status = None
        if response_status != "accepted_by_smp":
            fail("unexpected 200 response")
        print("SimpleX notification accepted by SMP.")
    elif status == 202:
        try:
            response_status = json.loads(response_data.decode("utf-8")).get("status")
        except (UnicodeDecodeError, AttributeError, TypeError, ValueError):
            response_status = None
        if response_status != "pending":
            fail("unexpected 202 response")
        print("SimpleX notification pending.")
    else:
        fail(f"unexpected HTTP {status}")


if __name__ == "__main__":
    main()
