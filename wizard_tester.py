# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337
"""Live check of the site wizard against the built-in sites that need no code.

Every built-in site whose template is pure data must be one a user could set up
in the wizard alone. This drives the real wizard in a WebKit browser for each
such site configured in the running Quasarr, lets it set every step up on its
own, and compares the outcome with the shipped template. Nothing is saved.

    uv run --with playwright python wizard_tester.py [KEY ...]

Needs a running Quasarr, `playwright install webkit` once, and USER, PASS and
QUASARR_API_KEY in .env. Hostnames are never printed.
"""

import argparse
import json
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv(override=True)

DEFAULT_URL = f"http://localhost:{int(os.environ.get('PORT', '8080'))}"
STEP_TIMEOUT_MS = 300_000


def _wait(page, condition, timeout=STEP_TIMEOUT_MS):
    try:
        page.wait_for_function(condition, timeout=timeout)
        return True
    except Exception:
        return False


def _idle(page, step):
    """Wait until a step has stayed idle for a moment: no busy note or button, not locked."""
    section = f"document.querySelector('.wizard-step[data-step={step}]')"
    condition = (
        f"!{section}.hidden && !{section}.hasAttribute('inert')"
        f" && !{section}.querySelector('.note.busy')"
        f" && !{section}.querySelector('[aria-busy=true]')"
    )
    deadline = time.time() + STEP_TIMEOUT_MS / 1000
    while time.time() < deadline:
        if not _wait(page, condition, int((deadline - time.time()) * 1000)):
            return False
        page.wait_for_timeout(1500)
        if page.evaluate(condition):
            return True
    return False


def _text(page, selector):
    try:
        return page.locator(selector).inner_text(timeout=2000)
    except Exception:
        return ""


def run_wizard(page, base, hostname):
    """Walk the wizard the way a user who accepts every suggestion would."""
    page.goto(f"{base}/sources/custom?hostname={hostname}")
    page.wait_for_timeout(1000)
    page.click("#site-next")
    page.wait_for_timeout(500)
    _wait(
        page,
        "document.getElementById('site-next').textContent !== 'Checking the site…'",
    )
    # a built-in match is reported first; the check sets the site up anyway
    if page.locator("#site-next").inner_text() == "Set it up anyway":
        page.click("#site-next")
        page.wait_for_timeout(500)
        _wait(page, "!document.querySelector('.wizard-step[data-step=feed]').hidden")
    _idle(page, "feed")
    result = {"feed": _text(page, "#feed-notes") + "\n" + _text(page, "#feed-results")}
    if page.locator("#feed-next").is_disabled():
        return result, None
    page.click("#feed-next")
    _idle(page, "search")
    result["search"] = (
        _text(page, "#search-notes") + "\n" + _text(page, "#search-results")
    )
    page.click("#search-next")
    _idle(page, "download")
    result["download"] = (
        _text(page, "#download-notes") + "\n" + _text(page, "#download-results")
    )
    page.click("#download-next")
    page.wait_for_timeout(1000)
    template = json.loads(
        page.eval_on_selector("#w-template", "e => e.value") or "null"
    )
    return result, template


def compare(shipped, built):
    """Differences that matter to the apps: kinds read and how search finds titles."""
    problems = []
    if built is None:
        return ["the wizard stopped before the end"]
    shipped_kinds = {feed["category"] for feed in shipped.get("feeds", [])}
    built_kinds = {feed["category"] for feed in built.get("feeds", [])}
    missing = sorted(shipped_kinds - built_kinds)
    if missing:
        problems.append(f"feed misses categories {missing}")
    if shipped.get("search") and not built.get("search"):
        problems.append("search not set up")
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "keys", nargs="*", help="two-letter keys; default: every code-free site"
    )
    parser.add_argument("--url", default=DEFAULT_URL)
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    api_key = os.environ.get("QUASARR_API_KEY", "")
    headers = {"X-API-Key": api_key}
    failed = 0
    with sync_playwright() as playwright:
        browser = playwright.webkit.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(f"{args.url}/login?next=/sources")
        if page.locator("#username").count():
            page.fill("#username", os.environ.get("USER", ""))
            page.fill("#password", os.environ.get("PASS", ""))
            page.click("text=Login")
            page.wait_for_url("**/sources**")
        sites = page.request.get(f"{args.url}/api/sites", headers=headers).json()
        hosts = {
            s["key"]: s["hostname"]
            for s in sites.get("sites", [])
            if s.get("kind") == "builtin"
        }
        for key in args.keys or sorted(hosts):
            if key not in hosts:
                print(f"{key}: not configured, skipped")
                continue
            template = page.request.get(
                f"{args.url}/api/sites/{key.lower()}/template", headers=headers
            ).json()
            if template.get("code_steps"):
                if args.keys:
                    print(
                        f"{key}: runs Python code for {', '.join(template['code_steps'])}, skipped"
                    )
                continue
            errors.clear()
            started = time.time()
            steps, built = run_wizard(page, args.url, hosts[key])
            problems = compare(template.get("shipped") or {}, built) + [
                f"page error: {error}" for error in errors
            ]
            seconds = round(time.time() - started)
            print(f"{key}: {'OK' if not problems else 'PROBLEMS'} in {seconds} s")
            for step, text in steps.items():
                summary = " ".join(text.replace(hosts[key], "{host}").split())[:300]
                print(f"  {step}: {summary}")
            for problem in problems:
                print(f"  ! {problem}")
            failed += bool(problems)
        browser.close()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
