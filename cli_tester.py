# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import argparse
import concurrent.futures
import os
import re
import sys
import threading
import time
import webbrowser
import xml.etree.ElementTree as ET
from base64 import urlsafe_b64decode
from datetime import datetime
from html import escape
from urllib.parse import urlparse

import requests

# Try importing dependencies
try:
    import questionary
    from prompt_toolkit import Application, PromptSession
    from prompt_toolkit.formatted_text import HTML, to_formatted_text
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.layout.containers import HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.layout import Layout
    from prompt_toolkit.utils import get_cwidth
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import (
        BarColumn,
        Progress,
        SpinnerColumn,
        TaskProgressColumn,
        TextColumn,
    )
    from rich.table import Table
except ImportError:
    print("Please install 'rich' and 'questionary' to use this tool.")
    print("uv sync --group dev")
    sys.exit(1)

from dotenv import load_dotenv

load_dotenv(override=True)

# --- Configuration & Constants ---
DEFAULT_URL = f"http://localhost:{int(os.environ.get('PORT', '8080'))}"
USER_AGENT_RADARR = "Radarr/3.0.0.0 (Mock Client for Testing)"
USER_AGENT_SONARR = "Sonarr/3.0.0.0 (Mock Client for Testing)"
USER_AGENT_LIDARR = "Lidarr/3.0.0.0 (Mock Client for Testing)"
USER_AGENT_MAGAZARR = "Magazarr/1.7.0 (Mock Client for Testing)"

BASE_SEARCH_CATEGORY_CONFIG = {
    2000: {
        "mode": "movie",
        "user_agent": USER_AGENT_RADARR,
        "download_category": "movies",
        "query_param": "imdbid",
        "query_validator": "imdb",
        "default_query": "tt0499549",
        "supports_season_episode": False,
        "search_capability": "movie",
    },
    3000: {
        "mode": "music",
        "user_agent": USER_AGENT_LIDARR,
        "download_category": "music",
        "query_param": "title",
        "query_validator": None,
        "default_query": "Taylor Swift",
        "supports_season_episode": False,
        "search_capability": "generic",
    },
    5000: {
        "mode": "tvsearch",
        "user_agent": USER_AGENT_SONARR,
        "download_category": "tv",
        "query_param": "imdbid",
        "query_validator": "imdb",
        "default_query": "tt0944947",
        "supports_season_episode": True,
        "search_capability": "tv",
    },
    7000: {
        "mode": "book",
        "user_agent": USER_AGENT_MAGAZARR,
        "download_category": "docs",
        "query_param": "title",
        "query_validator": None,
        "default_query": "PC Gamer UK",
        "supports_season_episode": False,
        "search_capability": "generic",
    },
}

BASE_CATEGORY_ICONS = {
    2000: "🎬",
    3000: "🎵",
    5000: "📺",
    7000: "📚",
}
ANIME_CATEGORY_ICON = "⛩️"

SEARCH_CATEGORY_CACHE_FAMILIES = {
    2000: (2000, 2040, 2045),
    3000: (3000, 3010, 3040),
    5000: (5000, 5040, 5045),
    5070: (5070,),
    5080: (5080,),
    6000: (6000,),
    7000: (7000,),
}

SEARCH_CACHE_OWNER_BY_CATEGORY = {
    category_id: owner_id
    for owner_id, category_ids in SEARCH_CATEGORY_CACHE_FAMILIES.items()
    for category_id in category_ids
}

console = Console()
IS_TTY = sys.stdin.isatty()


class Status:
    def __init__(self):
        self.text = ""


# --- Custom Loading Screen ---
class LoadingScreen:
    def __init__(self, title, func, *args, status_obj=None, **kwargs):
        """
        Runs 'func' in a separate thread while showing a spinner.
        Allows cancellation via Left/Backspace.
        Uses threading instead of asyncio to avoid RuntimeWarnings.
        """
        self.title = title
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.status_obj = status_obj

        # Spinner animation frames
        self.frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.start_time = time.time()

        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.future = None
        self.cancelled = False
        self.app = None

    def get_text(self):
        # Calculate frame based on elapsed time
        frame_idx = int((time.time() - self.start_time) * 10) % len(self.frames)
        spinner = self.frames[frame_idx]

        lines = []
        lines.append(
            HTML(f"<b><ansicyan>--- {escape(self.title.upper())} ---</ansicyan></b>")
        )
        lines.append(HTML("<grey>Keys: [Backspace/←] Cancel Operation</grey>"))
        lines.append(HTML(""))

        if self.cancelled:
            lines.append(HTML("<ansired>❌ Cancelled by user.</ansired>"))
        elif self.future and self.future.done():
            lines.append(HTML("<ansigreen>✔ Done.</ansigreen>"))
        else:
            lines.append(
                HTML(f"<ansigreen>{spinner} Processing request...</ansigreen>")
            )

        if self.status_obj and self.status_obj.text:
            # Escape text to prevent XML parsing errors
            safe_text = escape(self.status_obj.text)
            lines.append(HTML(f"<grey>{safe_text}</grey>"))

        result = []
        for line in lines:
            result.extend(to_formatted_text(line))
            result.append(("", "\n"))
        return result

    def _monitor_task(self):
        """
        Runs in a background thread. Monitors the future and exits the app when done.
        """
        while not self.cancelled:
            if self.future.done():
                try:
                    result = self.future.result()
                except Exception:
                    result = None

                # Signal the app to exit
                if self.app and self.app.is_running:
                    self.app.exit(result=result)
                break
            time.sleep(0.1)

    def run(self):
        kb = KeyBindings()

        @kb.add(Keys.Backspace)
        @kb.add(Keys.Left)
        def _(event):
            self.cancelled = True
            event.app.exit(result=None)

        @kb.add(Keys.ControlC)
        def _(event):
            sys.exit(0)

        text_control = FormattedTextControl(text=self.get_text, show_cursor=False)
        layout = Layout(HSplit([Window(content=text_control)]))

        # refresh_interval is critical here to keep the spinner animating
        self.app = Application(
            layout=layout, key_bindings=kb, full_screen=False, refresh_interval=0.1
        )

        # 1. Start the actual work
        self.future = self.executor.submit(self.func, *self.args, **self.kwargs)

        # 2. Start the monitor thread (daemon ensures it dies if main app dies)
        monitor_thread = threading.Thread(target=self._monitor_task, daemon=True)
        monitor_thread.start()

        # 3. Block until app.exit() is called
        return self.app.run()


# --- Custom Paginated Selector ---
class PaginatedSelector:
    def __init__(
        self,
        title,
        items,
        page_size=10,
        initial_index=0,
        duration=None,
        allowed_sorts=None,
    ):
        self.title = title
        self.original_items = list(items)  # Keep a copy of original order
        self.items = items
        self.page_size = page_size
        self.selected_index = min(initial_index, len(items) - 1) if items else 0
        self.result = None
        self.cancelled = False
        self.duration = duration

        # Define all possible sort logic
        # Key: (Display Label, Sort Function)
        self.all_sort_logic = {
            "newest": (
                "Newest",
                lambda: (
                    self.items[:]
                    if not self.original_items
                    else list(self.original_items)
                ),
            ),
            "oldest": ("Oldest", lambda: list(reversed(self.original_items))),
            "a-z": ("A-Z", lambda: sorted(self.items, key=lambda x: x[0])),
            "z-a": (
                "Z-A",
                lambda: sorted(self.items, key=lambda x: x[0], reverse=True),
            ),
            "size_desc": (
                "Size ⬇",
                lambda: sorted(self.items, key=self._get_size_key, reverse=True),
            ),
            "size_asc": ("Size ⬆", lambda: sorted(self.items, key=self._get_size_key)),
        }

        # If no specific sorts provided, default to full list
        if allowed_sorts is None:
            self.allowed_sorts = [
                "newest",
                "a-z",
                "z-a",
                "size_desc",
                "size_asc",
                "oldest",
            ]
        else:
            self.allowed_sorts = allowed_sorts

        self.sort_index = 0
        # If "newest" isn't available, apply the first allowed sort immediately
        if self.allowed_sorts and self.allowed_sorts[0] != "newest":
            self._apply_sort()

    def _get_size_key(self, item_tuple):
        # item_tuple is (label, dict)
        try:
            return float(item_tuple[1].get("size", 0))
        except (ValueError, TypeError):
            return 0

    def _apply_sort(self):
        if not self.allowed_sorts:
            return

        current_sort_key = self.allowed_sorts[self.sort_index]
        if current_sort_key in self.all_sort_logic:
            _, sort_func = self.all_sort_logic[current_sort_key]
            self.items = sort_func()

        # Reset selection to top
        self.selected_index = 0

    def get_current_page_indices(self):
        page_idx = self.selected_index // self.page_size
        start = page_idx * self.page_size
        end = min(len(self.items), start + self.page_size)
        return start, end, page_idx

    def get_text(self):
        start, end, page_idx = self.get_current_page_indices()
        total_pages = max(1, (len(self.items) + self.page_size - 1) // self.page_size)

        lines = []
        lines.append(
            HTML(f"<b><ansicyan>--- {escape(self.title.upper())} ---</ansicyan></b>")
        )

        # Header with Sort Info
        current_sort_key = self.allowed_sorts[self.sort_index]
        sort_label = self.all_sort_logic.get(current_sort_key, ("Unknown",))[0]

        lines.append(
            HTML(
                f"<grey>Keys: [↑/↓] Nav | [Enter] Select | [Tab] Sort: <b>{escape(sort_label)}</b> | [Back] Exit</grey>"
            )
        )

        summary = f"Page {page_idx + 1}/{total_pages} (Total: {len(self.items)})"
        if self.duration is not None:
            summary += f" | Took {self.duration:.2f}s"

        lines.append(HTML(f"<i>{escape(summary)}</i>"))
        lines.append(HTML(""))

        for i in range(start, end):
            label, _ = self.items[i]
            safe_label = escape(normalize_menu_label(label))

            if i == self.selected_index:
                lines.append(HTML(f"<reverse>  {safe_label}  </reverse>"))
            else:
                lines.append(HTML(f"  {safe_label}"))

        lines_used = end - start
        if lines_used < self.page_size:
            for _ in range(self.page_size - lines_used):
                lines.append(HTML(""))

        result = []
        for line in lines:
            result.extend(to_formatted_text(line))
            result.append(("", "\n"))

        return result

    def run(self):
        kb = KeyBindings()

        @kb.add(Keys.Up)
        @kb.add("k")
        def _(event):
            self.selected_index = max(0, self.selected_index - 1)

        @kb.add(Keys.Down)
        @kb.add("j")
        def _(event):
            self.selected_index = min(len(self.items) - 1, self.selected_index + 1)

        @kb.add(Keys.Left)
        @kb.add("h")
        def _(event):
            page_idx = self.selected_index // self.page_size
            if page_idx == 0:
                self.cancelled = True
                event.app.exit()
            else:
                new_idx = self.selected_index - self.page_size
                self.selected_index = max(0, new_idx)

        @kb.add(Keys.Right)
        @kb.add("l")
        def _(event):
            new_idx = self.selected_index + self.page_size
            if new_idx < len(self.items):
                self.selected_index = new_idx
            else:
                self.selected_index = len(self.items) - 1

        # Tab Binding for Sorting
        @kb.add(Keys.Tab)
        def _(event):
            if not self.allowed_sorts:
                return
            self.sort_index = (self.sort_index + 1) % len(self.allowed_sorts)
            self._apply_sort()

        @kb.add(Keys.Enter)
        def _(event):
            self.result = (self.items[self.selected_index][1], self.selected_index)
            event.app.exit()

        @kb.add(Keys.Backspace)
        def _(event):
            self.cancelled = True
            event.app.exit()

        @kb.add(Keys.ControlC)
        def _(event):
            sys.exit(0)

        text_control = FormattedTextControl(text=self.get_text, show_cursor=False)
        layout = Layout(HSplit([Window(content=text_control)]))
        app = Application(layout=layout, key_bindings=kb, full_screen=False)
        app.run()

        if self.cancelled:
            return None
        return self.result


# --- Custom Menu Selector ---
class MenuSelector:
    def __init__(self, title, items, allow_back=True):
        self.title = title
        self.items = items
        self.selected_index = 0
        self.result = None
        self.cancelled = False
        self.allow_back = allow_back

    def get_text(self):
        lines = []
        lines.append(
            HTML(f"<b><ansicyan>--- {escape(self.title.upper())} ---</ansicyan></b>")
        )

        if self.allow_back:
            lines.append(
                HTML(
                    "<grey>Keys: [↑/↓] Navigate | [Enter/→] Select | [Backspace/←] Back</grey>"
                )
            )
        else:
            lines.append(
                HTML(
                    "<grey>Keys: [↑/↓] Navigate | [Enter/→] Select | [Ctrl+C] Quit</grey>"
                )
            )

        lines.append(HTML(""))

        for i, (label, _) in enumerate(self.items):
            safe_label = escape(normalize_menu_label(label))
            if i == self.selected_index:
                lines.append(HTML(f"<reverse>  {safe_label}  </reverse>"))
            else:
                lines.append(HTML(f"  {safe_label}"))

        result = []
        for line in lines:
            result.extend(to_formatted_text(line))
            result.append(("", "\n"))
        return result

    def run(self):
        kb = KeyBindings()

        @kb.add(Keys.Up)
        @kb.add("k")
        def _(event):
            self.selected_index = max(0, self.selected_index - 1)

        @kb.add(Keys.Down)
        @kb.add("j")
        def _(event):
            self.selected_index = min(len(self.items) - 1, self.selected_index + 1)

        @kb.add(Keys.Enter)
        @kb.add(Keys.Right)
        @kb.add("l")
        def _(event):
            self.result = self.items[self.selected_index][1]
            event.app.exit()

        if self.allow_back:

            @kb.add(Keys.Backspace)
            @kb.add(Keys.Left)
            @kb.add("h")
            def _(event):
                self.cancelled = True
                event.app.exit()

        @kb.add(Keys.ControlC)
        def _(event):
            sys.exit(0)

        text_control = FormattedTextControl(text=self.get_text, show_cursor=False)
        layout = Layout(HSplit([Window(content=text_control)]))
        app = Application(layout=layout, key_bindings=kb, full_screen=False)
        app.run()

        if self.cancelled:
            return None
        return self.result


# --- Custom Text Input ---
class TextInput:
    def __init__(self, title, default="", validator=None):
        self.title = title
        self.default = default
        self.validator = validator

    def run(self):
        kb = KeyBindings()

        @kb.add(Keys.Escape)
        def _(event):
            event.app.exit(result=None)

        @kb.add("left")
        def _(event):
            if not event.current_buffer.text:
                event.app.exit(result=None)
            else:
                event.current_buffer.cursor_position = max(
                    0, event.current_buffer.cursor_position - 1
                )

        @kb.add("right")
        def _(event):
            buff = event.current_buffer
            if buff.cursor_position == len(buff.text):
                event.app.exit(result=buff.text)
            else:
                buff.cursor_position = min(len(buff.text), buff.cursor_position + 1)

        @kb.add("backspace")
        def _(event):
            if not event.current_buffer.text:
                event.app.exit(result=None)
            else:
                event.current_buffer.delete_before_cursor(1)

        session = PromptSession(key_bindings=kb)

        while True:
            try:
                prompt_text = HTML(
                    f"<b><ansicyan>--- {escape(self.title.upper())} ---</ansicyan></b>\n<grey>Keys: [Enter] Confirm | [Esc] Cancel</grey>\n[{escape(self.default)}]: "
                )
                result = session.prompt(prompt_text, default=self.default)

                if result is None:
                    return None

                if self.validator:
                    if self.validator(result):
                        return result
                    else:
                        clear_screen()
                        console.print(
                            "[bold red]Invalid input. Please try again.[/bold red]"
                        )
                        time.sleep(1)
                        continue
                return result
            except (KeyboardInterrupt, EOFError):
                return None


def press_any_key(message="Press any key to continue..."):
    kb = KeyBindings()

    def exit_app(event):
        event.app.exit()

    @kb.add("<any>")
    def _(event):
        exit_app(event)

    for key in [
        Keys.Up,
        Keys.Down,
        Keys.Left,
        Keys.Right,
        Keys.Enter,
        Keys.Backspace,
        Keys.Escape,
        Keys.Tab,
    ]:
        kb.add(key)(exit_app)

    text_control = FormattedTextControl(
        text=HTML(f"<grey>{escape(message)}</grey>"), show_cursor=False
    )
    layout = Layout(HSplit([Window(content=text_control, height=1)]))
    app = Application(layout=layout, key_bindings=kb, full_screen=False)
    app.run()


def validate_imdb(text):
    if text is None:
        return False
    return bool(re.match(r"^tt\d+$", text))


def normalize_menu_label(label):
    """
    Normalize selector labels containing leading icon tokens.

    Emoji width varies across terminals/fonts. Keep emoji on the left and align
    text using a fixed display-width icon column.
    """
    if not isinstance(label, str):
        return str(label)
    label = label.replace("\t", " ")

    stripped = label.lstrip()
    if not stripped:
        return label

    leading_spaces = len(label) - len(stripped)
    parts = stripped.split(maxsplit=1)
    if len(parts) < 2:
        return label

    icon, text = parts
    if re.search(r"[A-Za-z0-9]", icon):
        return label

    icon_width = get_cwidth(icon)
    icon_column_width = 2
    spacing = max(1, icon_column_width - icon_width + 1)
    return f"{' ' * leading_spaces}{icon}{' ' * spacing}{text}"


def is_main_search_category_id(cat_id):
    try:
        cat_id = int(cat_id)
    except (TypeError, ValueError):
        return False
    return cat_id > 0 and cat_id % 1000 == 0


def is_anime_search_category(category):
    if not isinstance(category, dict):
        return False

    category_name = (category.get("category_name") or "").strip().lower()
    category_key = (category.get("key") or "").strip().lower()
    return "anime" in category_name or "anime" in category_key


def is_main_priority_search_category(category):
    return is_main_search_category_id(
        category.get("category_id")
    ) or is_anime_search_category(category)


def get_base_search_category_id(cat_id):
    try:
        cat_id = int(cat_id)
    except (TypeError, ValueError):
        return None

    if cat_id <= 0:
        return None

    normalized_id = cat_id - 100000 if cat_id >= 100000 else cat_id
    if normalized_id <= 0:
        return None

    base = (normalized_id // 1000) * 1000
    return base if base > 0 else None


def get_search_cache_owner_category_id(cat_id):
    try:
        cat_id = int(cat_id)
    except (TypeError, ValueError):
        return cat_id

    if cat_id >= 100000:
        return cat_id

    return SEARCH_CACHE_OWNER_BY_CATEGORY.get(cat_id, cat_id)


def get_search_cache_family_groups(categories):
    grouped = {}
    for category in categories:
        owner_id = get_search_cache_owner_category_id(category.get("category_id"))
        grouped.setdefault(owner_id, []).append(category)

    return [
        (
            owner_id,
            sorted(
                grouped[owner_id],
                key=lambda category: (
                    category.get("category_id") or 0,
                    category.get("key") or "",
                ),
            ),
        )
        for owner_id in sorted(grouped)
    ]


# --- API Client ---
class QuasarrClient:
    def __init__(self, url, api_key):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.session = requests.Session()
        self._search_caps = None
        self._search_input_state = {}

    def get_search_input_state(self, category_key):
        """
        Returns remembered search input defaults for a category key.
        """
        state = self._search_input_state.get(category_key) or {}
        return {
            "query": state.get("query"),
            "season": state.get("season"),
            "episode": state.get("episode"),
        }

    def remember_search_input_state(
        self, category_key, query=None, season=None, episode=None
    ):
        """
        Remembers user-entered search defaults for a category key.
        """
        if not category_key:
            return

        state = self._search_input_state.get(category_key, {})
        if query is not None:
            state["query"] = str(query)
        if season is not None:
            state["season"] = str(season)
        if episode is not None:
            state["episode"] = str(episode)
        self._search_input_state[category_key] = state

    def _get(self, params, user_agent):
        request_params = params.copy()
        request_params["apikey"] = self.api_key
        headers = {"User-Agent": user_agent}
        try:
            response = self.session.get(
                f"{self.url}/api", params=request_params, headers=headers, timeout=120
            )
            response.raise_for_status()
            return response
        except requests.RequestException:
            return None

    def get_downloads(self):
        q_resp = self._get({"mode": "queue"}, USER_AGENT_RADARR)
        h_resp = self._get({"mode": "history"}, USER_AGENT_RADARR)
        queue, history = [], []
        linkgrabber_state = {"is_collecting": False, "is_stopped": True}
        if q_resp:
            try:
                queue_data = q_resp.json().get("queue", {})
                queue = queue_data.get("slots", [])
                if isinstance(queue_data.get("linkgrabber"), dict):
                    linkgrabber_state = queue_data.get("linkgrabber")
            except:
                pass
        if h_resp:
            try:
                history_data = h_resp.json().get("history", {})
                history = history_data.get("slots", [])
                if linkgrabber_state.get("is_collecting") is False and isinstance(
                    history_data.get("linkgrabber"), dict
                ):
                    linkgrabber_state = history_data.get("linkgrabber")
            except:
                pass
        return queue, history, linkgrabber_state

    def wait_for_linkgrabber_idle(self, timeout=120, poll_interval=2):
        end_time = time.time() + timeout
        not_grabbing_streak = 0

        while time.time() < end_time:
            _, _, state = self.get_downloads()
            not_grabbing = state.get("is_stopped") or not state.get("is_collecting")
            if not_grabbing:
                not_grabbing_streak += 1
                if not_grabbing_streak >= 2:
                    return True
                # First "not grabbing" can be transient, confirm after 3 seconds.
                time.sleep(3)
                continue
            not_grabbing_streak = 0
            time.sleep(poll_interval)
        return False

    def _parse_indexer_capabilities(self, response):
        caps = {"categories": {}}

        if not response:
            return caps

        def parse_available_tag(searching_node, tag_name):
            if searching_node is None:
                return None
            node = searching_node.find(tag_name)
            if node is None:
                return None
            available_attr = (node.attrib.get("available") or "").strip().lower()
            if available_attr == "yes":
                return True
            if available_attr == "no":
                return False
            return None

        try:
            root = ET.fromstring(response.content)
        except Exception:
            return caps

        searching = root.find(".//searching")
        supports_movie = parse_available_tag(searching, "movie-search")
        supports_tv = parse_available_tag(searching, "tv-search")
        supports_generic = parse_available_tag(searching, "search")

        for category in root.findall(".//categories/category"):
            cat_id_raw = category.attrib.get("id")
            cat_name = (category.attrib.get("name") or "").strip()
            if not cat_name:
                cat_name = str(cat_id_raw or "")
            if not cat_name:
                continue

            try:
                cat_id = int(cat_id_raw)
            except (TypeError, ValueError):
                continue

            base_cat_id = get_base_search_category_id(cat_id_raw)
            base_config = BASE_SEARCH_CATEGORY_CONFIG.get(base_cat_id)
            if not base_config:
                continue

            capability = base_config["search_capability"]
            if capability == "movie":
                enabled = supports_movie is not False
            elif capability == "tv":
                enabled = supports_tv is not False
            else:
                enabled = supports_generic is not False

            icon = BASE_CATEGORY_ICONS.get(base_cat_id, "📁")
            if cat_id == 5070 or "anime" in cat_name.lower():
                icon = ANIME_CATEGORY_ICON
            default_query = base_config["default_query"]
            if base_config["query_validator"] == "imdb" and (
                cat_id == 5070 or "anime" in cat_name.lower()
            ):
                default_query = "tt0994314"
            query_prompt = (
                f"{cat_name}: IMDb ID"
                if base_config["query_validator"] == "imdb"
                else f"{cat_name}: Query"
            )
            search_suffix = (
                "(IMDb)" if base_config["query_validator"] == "imdb" else "(Query)"
            )
            category_key = f"cat_{cat_id}"

            caps["categories"][category_key] = {
                "key": category_key,
                "category_id": cat_id,
                "category_name": cat_name,
                "base_category_id": base_cat_id,
                "enabled": enabled,
                "mode": base_config["mode"],
                "user_agent": base_config["user_agent"],
                "download_category": base_config["download_category"],
                "query_param": base_config["query_param"],
                "query_validator": base_config["query_validator"],
                "default_query": default_query,
                "query_prompt": query_prompt,
                "supports_season_episode": base_config["supports_season_episode"],
                "feed_label": f"{icon} {cat_name} ({cat_id})",
                "search_label": f"{icon} {cat_name} ({cat_id}) {search_suffix}",
            }

        caps["categories"] = dict(
            sorted(
                caps["categories"].items(),
                key=lambda item: item[1]["category_id"],
            )
        )

        return caps

    def get_indexer_capabilities(self, refresh=False):
        if self._search_caps is not None and not refresh:
            return self._search_caps

        response = self._get({"t": "caps"}, USER_AGENT_RADARR)
        caps = self._parse_indexer_capabilities(response)

        # Do not cache an empty/failed caps response - retry should be possible
        # without restarting the CLI session.
        if caps.get("categories"):
            self._search_caps = caps

        return caps

    def get_available_search_types(self, refresh=False):
        return [cat["key"] for cat in self.get_available_categories(refresh=refresh)]

    def get_available_categories(self, refresh=False):
        caps = self.get_indexer_capabilities(refresh=refresh)
        return [
            cat
            for cat in caps.get("categories", {}).values()
            if cat.get("category_id") is not None and cat.get("enabled") is not False
        ]

    def get_category(self, category_key, refresh=False):
        caps = self.get_indexer_capabilities(refresh=refresh)
        return caps.get("categories", {}).get(category_key)

    def _build_search_request(self, category_key, query=None, season=None, ep=None):
        category = self.get_category(category_key)
        if not category:
            return None, None

        if category.get("enabled") is False:
            return None, None

        params = {"t": category["mode"], "cat": str(category["category_id"])}
        if query is not None:
            query_param = category.get("query_param")
            if query_param:
                params[query_param] = query

        if category.get("supports_season_episode"):
            if season:
                params["season"] = season
            if ep:
                params["ep"] = ep

        return params, category["user_agent"]

    def get_feed(self, category_key):
        params, user_agent = self._build_search_request(category_key)
        if not params:
            return []
        return self._parse_xml(self._get(params, user_agent))

    def search(self, category_key, query, season=None, ep=None):
        params, user_agent = self._build_search_request(category_key, query, season, ep)
        if not params:
            return []
        return self._fetch_all_results(params, user_agent)

    def _get_default_category_key_by_base(self, base_category_id):
        categories = self.get_available_categories()
        if not categories:
            return None

        for category in categories:
            if category["category_id"] == base_category_id:
                return category["key"]

        for category in categories:
            if category["base_category_id"] == base_category_id:
                return category["key"]

        return None

    def search_movie(self, imdb_id):
        category_key = self._get_default_category_key_by_base(2000)
        if not category_key:
            return []
        return self.search(category_key, imdb_id)

    def search_tv(self, imdb_id, season=None, ep=None):
        category_key = self._get_default_category_key_by_base(5000)
        if not category_key:
            return []
        return self.search(category_key, imdb_id, season, ep)

    def search_music(self, query):
        category_key = self._get_default_category_key_by_base(3000)
        if not category_key:
            return []
        return self.search(category_key, query)

    def search_doc(self, query):
        category_key = self._get_default_category_key_by_base(7000)
        if not category_key:
            return []
        return self.search(category_key, query)

    def _fetch_all_results(self, base_params, user_agent):
        all_items = []
        offset, limit = 0, 100
        while True:
            params = base_params.copy()
            params.update({"offset": offset, "limit": limit})
            items = self._parse_xml(self._get(params, user_agent))
            if not items:
                break
            all_items.extend(items)
            if len(items) < limit:
                break
            offset += limit
        return all_items

    def _parse_xml(self, response):
        if not response:
            return []
        try:
            root = ET.fromstring(response.content)
            items = []
            for item in root.findall(".//item"):
                title_elem = item.find("title")
                link_elem = item.find("link")
                pubdate_elem = item.find("pubDate")
                comments_elem = item.find("comments")
                guid_elem = item.find("guid")
                enclosure_elem = item.find("enclosure")

                title_text = (
                    title_elem.text
                    if title_elem is not None and title_elem.text
                    else ""
                )
                link_text = (
                    link_elem.text if link_elem is not None and link_elem.text else ""
                )
                comments_text = (
                    comments_elem.text
                    if comments_elem is not None and comments_elem.text
                    else ""
                )
                guid_text = (
                    guid_elem.text if guid_elem is not None and guid_elem.text else ""
                )
                enclosure_url = (
                    enclosure_elem.attrib.get("url", "")
                    if enclosure_elem is not None
                    else ""
                )
                enclosure_size = (
                    enclosure_elem.attrib.get("length", "0")
                    if enclosure_elem is not None
                    else "0"
                )

                # Ignore API placeholder items that represent "no results".
                # These are not real releases and can otherwise be mis-read
                # as host candidates (e.g. github.com).
                title_lower = title_text.strip().lower()
                comments_lower = comments_text.strip().lower()
                link_lower = link_text.strip().lower()
                enclosure_url_lower = enclosure_url.strip().lower()
                if title_lower == "no results found" and (
                    guid_text.strip() == "0"
                    or "no results matched your search criteria" in comments_lower
                    or "github.com/rix1337/quasarr" in link_lower
                    or "github.com/rix1337/quasarr" in enclosure_url_lower
                ):
                    continue

                items.append(
                    {
                        "title": title_text,
                        "link": link_text,
                        "size": enclosure_size,
                        "pubdate": (
                            pubdate_elem.text
                            if pubdate_elem is not None and pubdate_elem.text
                            else ""
                        ),
                    }
                )
            return items
        except:
            return []

    def add_download(self, title, link, category=None):
        params = {"mode": "addurl", "name": link}
        if category:
            params["cat"] = category

        # Use appropriate User-Agent if category is known
        user_agent = USER_AGENT_RADARR
        if category == "tv":
            user_agent = USER_AGENT_SONARR
        elif category == "music":
            user_agent = USER_AGENT_LIDARR
        elif category == "docs":
            user_agent = USER_AGENT_MAGAZARR

        resp = self._get(params, user_agent)
        if not resp:
            return None, "Request failed"

        try:
            data = resp.json()
        except Exception:
            return None, "Invalid JSON response"

        # Check for quasarr_error flag
        if data.get("quasarr_error"):
            return None, data.get("quasarr_error")

        # Also check status and nzo_ids as a fallback
        if data.get("status", False) and data.get("nzo_ids"):
            return data.get("nzo_ids"), None
        return None, "Unknown error"

    def delete_download(self, nzo_id, title=None):
        params = {"mode": "queue", "name": "delete", "value": nzo_id}
        if title:
            params["title"] = title

        resp = self._get(params, USER_AGENT_RADARR)
        if not resp:
            return False, "Request failed"

        try:
            data = resp.json()
        except Exception:
            return False, "Invalid JSON response"

        if data.get("quasarr_error"):
            error = data.get("quasarr_error")
            if isinstance(error, str):
                return False, error
            return False, "Delete request rejected"

        if data.get("status", False):
            return True, None
        return False, "Unknown error"

    def fail_download(self, package_id):
        try:
            resp = self.session.delete(
                f"{self.url}/sponsors_helper/api/fail/",
                params={"apikey": self.api_key},
                json={"package_id": package_id},
                timeout=30,
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            if hasattr(e, "response") and e.response is not None:
                console.print(
                    f"[red]Fail download error: {e.response.status_code} - {e.response.text}[/red]"
                )
            else:
                console.print(f"[red]Fail download error: {e}[/red]")
            return False

    def enable_sponsor_status(self):
        try:
            # 1. Enable status
            resp = self.session.put(
                f"{self.url}/sponsors_helper/api/set_sponsor_status/",
                params={"apikey": self.api_key},
                json={"activate": True},
                timeout=30,
            )
            resp.raise_for_status()

            # 2. Call to_decrypt to set the timestamp
            self.session.get(
                f"{self.url}/sponsors_helper/api/to_decrypt/",
                params={"apikey": self.api_key},
                timeout=30,
            )
            return True
        except Exception as e:
            if hasattr(e, "response") and e.response is not None:
                console.print(
                    f"[red]Enable sponsor status error: {e.response.status_code} - {e.response.text}[/red]"
                )
            else:
                console.print(f"[red]Enable sponsor status error: {e}[/red]")
            return False


# --- UI Logic ---
def clear_screen():
    console.clear()


def format_size(size_bytes):
    try:
        s = int(size_bytes)
        if s == 0:
            return "0 MB"
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if s < 1024:
                return f"{s:.2f} {unit}"
            s /= 1024
    except:
        return "Unknown"


def get_download_item_name(item):
    return item.get("filename") or item.get("name") or "Unknown"


def delete_download_items(client, items):
    nzo_id_to_title = {}
    for item in items:
        nzo_id = item.get("nzo_id")
        if not nzo_id:
            continue
        nzo_id_to_title[nzo_id] = get_download_item_name(item)

    if not nzo_id_to_title:
        console.print("[yellow]No deletable packages found.[/yellow]")
        return True

    deleted_count = 0
    deletion_errors = []

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            transient=True,
        ) as progress:
            task_id = progress.add_task(
                "Deleting packages...", total=len(nzo_id_to_title)
            )

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=max(1, min(10, len(nzo_id_to_title)))
            ) as executor:
                future_to_id = {
                    executor.submit(client.delete_download, nzo_id, title): nzo_id
                    for nzo_id, title in nzo_id_to_title.items()
                }

                for future in concurrent.futures.as_completed(future_to_id):
                    nzo_id = future_to_id[future]
                    try:
                        success, error = future.result()
                        if success:
                            deleted_count += 1
                        else:
                            deletion_errors.append(
                                f"{nzo_id_to_title.get(nzo_id, nzo_id)} ({nzo_id}): {error}"
                            )
                    except Exception as exc:
                        deletion_errors.append(
                            f"{nzo_id_to_title.get(nzo_id, nzo_id)} ({nzo_id}): {exc}"
                        )
                    progress.advance(task_id)
    except KeyboardInterrupt:
        console.print("[red]Cancelled delete-all operation.[/red]")
        return False

    total = len(nzo_id_to_title)
    if deletion_errors:
        console.print(f"[yellow]Deleted {deleted_count}/{total} packages.[/yellow]")
        console.print("[red]Failed deletions:[/red]")
        for error in deletion_errors:
            console.print(f"  - {error}")
        return False

    console.print(f"[green]Deleted {deleted_count} packages.[/green]")
    return True


def delete_all_packages(client, interactive=True):
    if interactive:
        clear_screen()
        results = LoadingScreen("Fetching Downloads", client.get_downloads).run()
        clear_screen()
        if results is None:
            return None
    else:
        results = client.get_downloads()

    if isinstance(results, tuple):
        if len(results) == 3:
            queue, history, _ = results
        elif len(results) == 2:
            queue, history = results
        else:
            queue, history = [], []
    else:
        queue, history = [], []

    all_items = []
    for item in queue:
        item = item.copy()
        item["type"] = "queue"
        all_items.append(item)
    for item in history:
        item = item.copy()
        item["type"] = "history"
        all_items.append(item)

    if not all_items:
        console.print(
            Panel("No packages to delete.", title="Downloads", border_style="blue")
        )
        if interactive:
            press_any_key()
            clear_screen()
        return True

    deletable_count = len(
        {item.get("nzo_id") for item in all_items if item.get("nzo_id")}
    )
    if (
        interactive
        and not questionary.confirm(f"Delete all {deletable_count} packages?").ask()
    ):
        return None

    success = delete_download_items(client, all_items)

    if interactive:
        time.sleep(2)

    return success


def show_downloads(client):
    last_idx = 0
    # For downloads, we skip "newest/oldest" as API data might be inconsistent for sorting
    download_sorts = ["a-z", "z-a", "size_desc", "size_asc"]

    while True:
        clear_screen()
        results = LoadingScreen("Fetching Downloads", client.get_downloads).run()
        clear_screen()  # Ensure loading screen is cleared immediately

        if results is None:
            return

        if isinstance(results, tuple):
            if len(results) == 3:
                queue, history, _ = results
            elif len(results) == 2:
                queue, history = results
            else:
                queue, history = [], []
        else:
            queue, history = [], []
        all_items = []
        for item in queue:
            item["type"] = "queue"
            all_items.append(item)
        for item in history:
            item["type"] = "history"
            all_items.append(item)

        if not all_items:
            console.print(
                Panel("No active downloads.", title="Downloads", border_style="blue")
            )
            press_any_key()
            clear_screen()
            return

        selector_items = []
        for item in all_items:
            # Name
            name = (
                item.get("filename")
                if item["type"] == "queue"
                else item.get("name", "Unknown")
            )
            status = item.get("status", "Unknown")

            # Size
            # Queue often has 'size' (total) or 'mb' (total)
            raw_size = item.get("size", "0")
            size_str = format_size(raw_size)

            # Time / ETA
            time_info = ""
            if item["type"] == "queue":
                # Queue usually has 'timeleft'
                eta = item.get("timeleft", "")
                if eta:
                    time_info = f" | ETA: {eta}"
            else:
                # History usually has completion date
                completed = item.get("completed", "") or item.get("date", "")
                if completed:
                    # Try timestamp conversion if it's a timestamp
                    try:
                        ts = int(completed)
                        dt = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
                        time_info = f" | {dt}"
                    except:
                        time_info = f" | {completed}"

            icon = "⬇️" if item["type"] == "queue" else "📜"
            label = f"{icon} {name} (Size: {size_str}{time_info}) [{status}]"
            selector_items.append((label, item))

        result = PaginatedSelector(
            "Downloads",
            selector_items,
            page_size=10,
            initial_index=last_idx,
            allowed_sorts=download_sorts,
        ).run()

        clear_screen()  # Clean up the selector UI immediately

        if result is None:
            break

        item, last_idx = result
        name = item.get("filename") if item["type"] == "queue" else item.get("name")
        nzo_id = item.get("nzo_id")

        menu = []
        if "[CAPTCHA" in name:
            menu.append(("🔓 Solve CAPTCHA", "captcha"))
        menu.append(("🗑️ Delete", "delete"))
        if item.get("status", "").lower() not in ["failed", "error"]:
            menu.append(("❌ Mark Failed", "fail"))

        action = MenuSelector(f"Manage: {name}", menu).run()
        clear_screen()

        if action == "captcha":
            webbrowser.open(f"{client.url}/captcha?package_id={nzo_id}")
            time.sleep(2)
        elif action == "delete":
            if questionary.confirm(f"Delete '{name}'?").ask():
                res = LoadingScreen(
                    f"Deleting {name}", client.delete_download, nzo_id
                ).run()
                if res and res[0]:
                    console.print("[green]Deleted[/green]")
                else:
                    err = res[1] if res else "Cancelled"
                    console.print(f"[red]Failed: {err}[/red]")
                time.sleep(1)
        elif action == "fail":
            if questionary.confirm(f"Mark '{name}' failed?").ask():
                if LoadingScreen(f"Failing {name}", client.fail_download, nzo_id).run():
                    console.print("[green]Marked Failed[/green]")
                else:
                    console.print("[red]Failed[/red]")
                time.sleep(1)


def handle_results_pager(client, results, category=None, duration=None):
    clear_screen()
    if not results:
        console.print(
            Panel("[yellow]No results found.[/yellow]", border_style="yellow")
        )
        press_any_key()
        clear_screen()
        return

    # Default logic for search results includes date sorting
    results.sort(key=lambda x: x.get("pubdate", ""), reverse=True)
    selector_items = [
        (f"{item['title']} ({format_size(item['size'])})", item) for item in results
    ]

    last_idx = 0
    while True:
        clear_screen()
        result = PaginatedSelector(
            "Search Results",
            selector_items,
            page_size=10,
            initial_index=last_idx,
            duration=duration,
        ).run()

        clear_screen()

        if result is None:
            break
        item, last_idx = result

        res = LoadingScreen(
            f"Adding: {item['title']}",
            client.add_download,
            item["title"],
            item["link"],
            category,
        ).run()

        clear_screen()

        if res and res[0]:
            console.print(f"[green]✅ Added '{item['title']}'[/green]")
        elif res:
            console.print(f"[red]❌ Failed to add '{item['title']}': {res[1]}[/red]")
        else:
            console.print("[yellow]⚠️ Cancelled[/yellow]")
        time.sleep(1)


def handle_feeds_menu(client):
    while True:
        clear_screen()
        available_categories = client.get_available_categories()
        choices = [
            (category["feed_label"], category["key"])
            for category in available_categories
        ]
        if not choices:
            console.print(
                Panel(
                    "[yellow]No feed categories are currently exposed by /api?t=caps.[/yellow]",
                    border_style="yellow",
                )
            )
            press_any_key()
            return

        choice = MenuSelector(
            "Select Feed",
            choices,
        ).run()
        clear_screen()

        if not choice:
            break

        selected_category = client.get_category(choice)
        if not selected_category:
            continue

        start = time.time()
        results = LoadingScreen(
            f"Fetching {selected_category['category_name']} Feed",
            client.get_feed,
            choice,
        ).run()
        clear_screen()

        if results is not None:
            handle_results_pager(
                client,
                results,
                selected_category["download_category"],
                time.time() - start,
            )


def handle_searches_menu(client):
    while True:
        clear_screen()
        available_categories = client.get_available_categories()
        choices = [
            (category["search_label"], category["key"])
            for category in available_categories
        ]
        if not choices:
            console.print(
                Panel(
                    "[yellow]No search categories are currently exposed by /api?t=caps.[/yellow]",
                    border_style="yellow",
                )
            )
            press_any_key()
            return

        choice = MenuSelector(
            "Select Search Type",
            choices,
        ).run()
        clear_screen()

        if not choice:
            break

        selected_category = client.get_category(choice)
        if not selected_category:
            continue

        remembered_inputs = client.get_search_input_state(choice)
        validator = (
            validate_imdb if selected_category["query_validator"] == "imdb" else None
        )
        q = TextInput(
            selected_category["query_prompt"],
            default=remembered_inputs.get("query")
            or selected_category["default_query"],
            validator=validator,
        ).run()
        if not q:
            continue
        client.remember_search_input_state(choice, query=q)

        clear_screen()
        start = time.time()

        if selected_category["supports_season_episode"]:
            s = TextInput(
                f"{selected_category['category_name']}: {q}\nSeason",
                default=remembered_inputs.get("season") or "1",
            ).run()
            if s is None:
                continue
            client.remember_search_input_state(choice, season=s)
            clear_screen()
            e = TextInput(
                f"{selected_category['category_name']}: {q} S{s}\nEpisode",
                default=remembered_inputs.get("episode") or "1",
            ).run()
            if e is None:
                continue
            client.remember_search_input_state(choice, episode=e)
            clear_screen()
            res = LoadingScreen(
                f"Searching {selected_category['category_name']}: {q}",
                client.search,
                choice,
                q,
                s,
                e,
            ).run()
        else:
            res = LoadingScreen(
                f"Searching {selected_category['category_name']}: {q}",
                client.search,
                choice,
                q,
            ).run()

        clear_screen()
        if res is not None:
            handle_results_pager(
                client,
                res,
                selected_category["download_category"],
                time.time() - start,
            )


def handle_hostname_test(client, interactive=True):
    if interactive:
        clear_screen()

    console.print("[bold cyan]--- TEST ALL HOSTNAMES ---[/bold cyan]")
    console.print("[dim]Keys: [Ctrl+C] Cancel Operation[/dim]")
    console.print("")

    available_categories = client.get_available_categories()
    categories_by_key = {category["key"]: category for category in available_categories}
    feed_names = {
        category["key"]: f"{category['category_name']} ({category['category_id']})"
        for category in available_categories
    }
    feed_keys = [category["key"] for category in available_categories]
    cache_family_groups = get_search_cache_family_groups(available_categories)
    feed_groups = [
        [
            (category["key"], category["download_category"])
            for category in group_categories
        ]
        for _, group_categories in cache_family_groups
    ]
    feeds = [feed for group in feed_groups for feed in group]
    if not feeds:
        console.print(
            "[bold red]Error: No feed categories are currently exposed by /api?t=caps.[/bold red]"
        )
        if interactive:
            press_any_key()
        return False

    # 1. Fetch Feeds
    console.print("[cyan]Fetching feeds...[/cyan]")
    all_feed_items = []

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=True,
        ) as progress:
            feed_group_positions = {}
            for group in feed_groups:
                for position, (feed_type, _) in enumerate(group):
                    feed_group_positions[feed_type] = position
            task_ids = {}

            # Render all categories up front.
            # Categories within one cache-family group run sequentially.
            # Different cache families run in parallel.
            for feed_type, _ in feeds:
                prefix = "  " if feed_group_positions.get(feed_type, 0) > 0 else ""
                description = f"{prefix}[dim]Pending {feed_names.get(feed_type, feed_type)} feed...[/dim]"
                task_ids[feed_type] = progress.add_task(description, total=None)

            progress_lock = threading.Lock()

            def fetch_family_group(feed_group):
                family_items = []
                for position, (feed_type, download_category) in enumerate(feed_group):
                    prefix = "  " if position > 0 else ""
                    with progress_lock:
                        progress.update(
                            task_ids[feed_type],
                            description=(
                                f"{prefix}Fetching {feed_names.get(feed_type, feed_type)} feed..."
                            ),
                            completed=0,
                            total=None,
                        )
                    try:
                        feed_items = client.get_feed(feed_type)
                        with progress_lock:
                            progress.update(
                                task_ids[feed_type],
                                completed=1,
                                total=1,
                                description=f"{prefix}[green]Fetched {feed_names.get(feed_type, feed_type)} feed[/green]",
                            )
                        if feed_items:
                            for item in feed_items:
                                family_items.append(
                                    (
                                        feed_type,
                                        download_category,
                                        item,
                                    )
                                )
                    except Exception:
                        with progress_lock:
                            progress.update(
                                task_ids[feed_type],
                                completed=1,
                                total=1,
                                description=f"{prefix}[red]Failed {feed_names.get(feed_type, feed_type)} feed[/red]",
                            )
                return family_items

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=max(1, min(3, len(feed_groups)))
            ) as executor:
                future_to_group = {
                    executor.submit(fetch_family_group, feed_group): feed_group
                    for feed_group in feed_groups
                }

                for future in concurrent.futures.as_completed(future_to_group):
                    try:
                        all_feed_items.extend(future.result())
                    except Exception:
                        pass
    except KeyboardInterrupt:
        console.print("[red]Cancelled fetching feeds.[/red]")
        return False

    if not all_feed_items:
        console.print("[bold red]Error: No feed items received.[/bold red]")
        if interactive:
            press_any_key()
        return False

    # Process items to find candidates (group by host, pick oldest)
    items_by_feed_host = {}
    seen_release_keys = set()

    for feed_type, category, item in all_feed_items:
        title = item.get("title") or ""
        link = item.get("link") or ""
        host = None

        # Parse payload to get real info if available
        payload_info = {}
        if link:
            try:
                parsed = urlparse(link)
                if "payload=" in parsed.query:
                    payload = parsed.query.split("payload=")[1].split("&")[0]
                    payload += "=" * (-len(payload) % 4)
                    decoded = urlsafe_b64decode(payload).decode("utf-8")
                    parts = decoded.split("|")
                    if len(parts) >= 6:
                        payload_info = {
                            "title": parts[0],
                            "url": parts[1],
                            "size": parts[2],
                            "pwd": parts[3],
                            "imdb": parts[4],
                            "source": parts[5],
                        }
            except Exception:
                pass

        # 1. Try title prefix [XX]
        match = re.match(r"^\[([A-Za-z0-9\.\-\_]+)\]", title)
        if match:
            host = match.group(1).lower()
            # If title is just prefix, try to use payload title
            if len(title.strip()) <= len(match.group(0)) + 1:
                if payload_info.get("title"):
                    title = payload_info["title"]
                    item["title"] = title

        # 2. Try payload source
        if not host and payload_info.get("source"):
            host = payload_info["source"].lower()
            if not title and payload_info.get("title"):
                title = payload_info["title"]
                item["title"] = title

        # 3. Fallback to domain
        if not host and link:
            try:
                host = urlparse(link).hostname
            except:
                pass

        if not host:
            continue

        dedupe_source = (payload_info.get("source") or host or "").strip().lower()
        dedupe_title = re.sub(r"\s+", " ", (title or "")).strip().lower()
        dedupe_fallback = re.sub(r"\s+", " ", (link or "")).strip().lower()
        # De-duplicate only within the same feed/category at this stage.
        # Cross-category dedupe is handled during add attempts.
        dedupe_key = (feed_type, dedupe_source, dedupe_title or dedupe_fallback)

        if dedupe_key[1] and dedupe_key in seen_release_keys:
            continue
        seen_release_keys.add(dedupe_key)

        _key = (feed_type, host)
        if _key not in items_by_feed_host:
            items_by_feed_host[_key] = []

        items_by_feed_host[_key].append(
            {
                "feed": feed_type,
                "category": category,
                "host": host,
                "item": item,
            }
        )

    # Prepare tasks: one download attempt per hostname per feed.
    # Keep oldest-first ordering with retry candidates from the same source.
    # Process subcategories (e.g. 5070 anime) before their base categories (e.g. 5000 TV)
    # so cross-category dedupe does not starve subcategory coverage.
    tasks_to_process = []
    categories_by_key = {category["key"]: category for category in available_categories}

    def feed_sort_key(feed_key):
        category = categories_by_key.get(feed_key, {})
        category_id = category.get("category_id", 0)
        base_category_id = category.get("base_category_id", category_id)
        is_base_category = 1 if is_main_search_category_id(category_id) else 0
        return (base_category_id, is_base_category, category_id, feed_key)

    ordered_feed_keys = sorted(feed_keys, key=feed_sort_key)

    for feed in ordered_feed_keys:
        feed_hosts = sorted(
            [host for (feed_key, host) in items_by_feed_host.keys() if feed_key == feed]
        )
        for host in feed_hosts:
            candidates = list(reversed(items_by_feed_host[(feed, host)]))
            tasks_to_process.append(
                {
                    "feed": feed,
                    "host": host,
                    "candidates": candidates,
                }
            )

    if interactive:
        clear_screen()
        console.print("[bold cyan]--- TEST ALL HOSTNAMES ---[/bold cyan]")
        console.print("[dim]Keys: [Ctrl+C] Cancel Operation[/dim]")
        console.print("")

    if not tasks_to_process:
        console.print("[bold red]Error: No items to download found.[/bold red]")
        if interactive:
            press_any_key()
        return False

    # 2. Download items
    results = []
    attempted_titles = set()
    attempted_release_keys = set()
    attempted_release_lock = threading.Lock()
    console.print(
        f"[cyan]Attempting to add {len(tasks_to_process)} downloads (with retries)...[/cyan]"
    )

    def process_download_task(task):
        feed = task["feed"]
        host = task["host"]
        candidates = task["candidates"]

        # Try up to 3 real add attempts.
        # Duplicate candidates do not count against this budget.
        max_add_attempts = 3
        add_attempts = 0
        last_error = "No candidates"
        last_title = "Unknown"

        for candidate in candidates:
            title = candidate["item"]["title"]
            link = candidate["item"]["link"]
            category = candidate["category"]
            candidate_host = candidate.get("host") or host
            last_title = title

            release_key_source = (candidate_host or "").strip().lower()
            release_key_title = re.sub(r"\s+", " ", (title or "")).strip().lower()
            release_key_fallback = re.sub(r"\s+", " ", (link or "")).strip().lower()
            release_key = (
                release_key_source,
                release_key_title or release_key_fallback,
            )

            if release_key[1]:
                with attempted_release_lock:
                    if release_key in attempted_release_keys:
                        last_error = "Duplicate across categories"
                        continue
                    attempted_release_keys.add(release_key)

            add_attempts += 1
            nzo_ids, error = client.add_download(title, link, category=category)
            if nzo_ids:
                return {
                    "feed": feed,
                    "host": host,
                    "title": title,
                    "success": True,
                    "nzo_ids": nzo_ids,
                    "error": None,
                }
            last_error = error
            if add_attempts >= max_add_attempts:
                break

        if add_attempts == 0 and candidates:
            last_error = "All candidates were duplicates across categories"

        return {
            "feed": feed,
            "host": host,
            "title": last_title,
            "success": False,
            "nzo_ids": None,
            "error": last_error,
        }

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            transient=True,
        ) as progress:
            task_id = progress.add_task(
                "Adding downloads...", total=len(tasks_to_process)
            )

            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                future_to_task = {
                    executor.submit(process_download_task, task): task
                    for task in tasks_to_process
                }

                for future in concurrent.futures.as_completed(future_to_task):
                    try:
                        res = future.result()
                        attempted_titles.add(res["title"])
                        results.append(res)
                    except Exception:
                        pass
                    progress.advance(task_id)
    except KeyboardInterrupt:
        console.print("[red]Cancelled adding downloads.[/red]")
        # Proceed to summary/cleanup with whatever results we have

    # 3. Summary
    if interactive:
        clear_screen()
    console.print(
        Panel("Summary of Hostname Test", title="Results", border_style="blue")
    )

    # Stats for summary
    stats = {
        feed_type: {
            "results": 0,
            "dl_success": 0,
            "dl_fail": 0,
            "del_success": 0,
            "del_fail": 0,
        }
        for feed_type in feed_keys
    }

    # Group results by feed type
    grouped_results = {}
    for res in results:
        feed = res["feed"]
        if feed not in grouped_results:
            grouped_results[feed] = []
        grouped_results[feed].append(res)

        if feed in stats:
            stats[feed]["results"] += 1
            if res["success"]:
                stats[feed]["dl_success"] += 1
            else:
                stats[feed]["dl_fail"] += 1

    for feed, res_list in grouped_results.items():
        console.print(
            f"[bold underline]{feed_names.get(feed, feed)}[/bold underline] ({len(res_list)} items)"
        )
        for res in res_list:
            color = "green" if res["success"] else "red"
            status = "OK" if res["success"] else "FAIL"
            console.print(
                f"  [{color}]{status}[/{color}] - {res['host'].upper()} - {res['title']}"
            )
        console.print("")

    if interactive:
        console.print(
            "[yellow]Press any key to delete these downloads and exit...[/yellow]"
        )
        press_any_key()

    # 4. Cleanup
    if interactive:
        clear_screen()
        console.print("[bold cyan]--- TEST ALL HOSTNAMES ---[/bold cyan]")
        console.print("[dim]Keys: [Ctrl+C] Cancel Operation[/dim]")
        console.print("")

    console.print("[cyan]Cleaning up...[/cyan]")

    if not client.wait_for_linkgrabber_idle(timeout=120, poll_interval=2):
        console.print(
            "[bold red]Error: Linkgrabber is still active after waiting. Skipping delete cleanup.[/bold red]"
        )
        if interactive:
            press_any_key()
        return False

    # Collect nzo_ids from results
    nzo_ids_to_delete = set()
    nzo_id_to_feed = {}
    nzo_id_to_title = {}
    for res in results:
        if res.get("nzo_ids"):
            for nid in res["nzo_ids"]:
                nzo_ids_to_delete.add(nid)
                nzo_id_to_feed[nid] = res["feed"]
                nzo_id_to_title[nid] = res.get("title")

    # Also fetch current queue/history to find items by name (for failed adds that might be stuck)
    try:
        queue, history, _ = client.get_downloads()
        all_downloads = queue + history

        for item in all_downloads:
            # Check if this item matches any attempted title
            name = item.get("filename") or item.get("name") or ""
            nzo_id = item.get("nzo_id")

            if not nzo_id:
                continue

            # If we already have this ID, skip
            if nzo_id in nzo_ids_to_delete:
                continue

            # Check for title match
            # Simple containment check or exact match
            for title in attempted_titles:
                if title and (title == name or title in name or name in title):
                    nzo_ids_to_delete.add(nzo_id)
                    if name:
                        nzo_id_to_title[nzo_id] = name
                    break
    except Exception:
        pass

    deleted_count = 0
    deletion_errors = []

    if not nzo_ids_to_delete:
        pass
    else:
        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                transient=True,
            ) as progress:
                task_id = progress.add_task(
                    "Deleting downloads...", total=len(nzo_ids_to_delete)
                )

                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=max(1, min(10, len(nzo_ids_to_delete)))
                ) as executor:
                    future_to_id = {
                        executor.submit(
                            client.delete_download, nzo_id, nzo_id_to_title.get(nzo_id)
                        ): nzo_id
                        for nzo_id in nzo_ids_to_delete
                    }

                    for future in concurrent.futures.as_completed(future_to_id):
                        nzo_id = future_to_id[future]
                        feed = nzo_id_to_feed.get(nzo_id)
                        try:
                            success, error = future.result()
                            if success:
                                deleted_count += 1
                                if feed in stats:
                                    stats[feed]["del_success"] += 1
                            else:
                                if feed in stats:
                                    stats[feed]["del_fail"] += 1
                                deletion_errors.append(f"ID {nzo_id}: {error}")
                        except Exception:
                            if feed in stats:
                                stats[feed]["del_fail"] += 1
                            deletion_errors.append(f"ID {nzo_id}: Exception")
                        progress.advance(task_id)

            console.print(f"[green]Deleted {deleted_count} downloads.[/green]")
        except KeyboardInterrupt:
            console.print("[red]Cancelled cleanup.[/red]")

    if interactive:
        time.sleep(2)

    # Print Summary Table
    table = Table(title="Bulk Test Summary")
    table.add_column("Feed", style="cyan")
    table.add_column("Downloads (Success/Total)", justify="right")
    table.add_column("Deletions (Success/Total)", justify="right")

    for feed in feed_keys:
        data = stats[feed]
        total_dl = data["results"]
        dl_success = data["dl_success"]

        total_del = data["del_success"] + data["del_fail"]
        del_success = data["del_success"]

        dl_style = (
            "green"
            if dl_success == total_dl and total_dl > 0
            else "red"
            if dl_success == 0 and total_dl > 0
            else "yellow"
        )
        del_style = (
            "green"
            if del_success == total_del and total_dl > 0
            else "red"
            if del_success == 0 and total_dl > 0
            else "yellow"
        )

        table.add_row(
            feed_names.get(feed, feed),
            f"[{dl_style}]{dl_success}/{total_dl}[/{dl_style}]",
            f"[{del_style}]{del_success}/{total_dl}[/{del_style}]",
        )
    console.print(table)
    console.print("")

    # Show failures
    failures = [r for r in results if not r["success"]]
    if failures or deletion_errors:
        console.print("[bold red]Failures:[/bold red]")
        if failures:
            console.print("[red]Downloads:[/red]")
            for f in failures:
                console.print(
                    f"  - {feed_names.get(f['feed'], f['feed'])} / {f['host'].upper()}: {f['error']} ({f['title']})"
                )

        if deletion_errors:
            console.print("[red]Deletions:[/red]")
            for err in deletion_errors:
                console.print(f"  - {err}")
        console.print("")

    # Error Checks
    successful_downloads = len([r for r in results if r["success"]])

    # If we attempted downloads but none succeeded
    if results and successful_downloads == 0:
        console.print(
            "[bold red]Error: No downloads were successfully added.[/bold red]"
        )
        if interactive:
            press_any_key()
        return False

    # If we deleted fewer than we successfully added (by ID), that's definitely an error.
    # If we deleted more (because we cleaned up failed ones too), that's fine.
    # But strictly speaking, we want to ensure everything we added is gone.
    # Let's just check if we deleted at least the number of successful ones.
    if deleted_count < successful_downloads:
        console.print(
            f"[bold red]Error: Mismatch! Added {successful_downloads} but deleted {deleted_count}.[/bold red]"
        )
        if interactive:
            press_any_key()
        return False

    if interactive:
        press_any_key()

    return True


def run_cli():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--key")
    parser.add_argument("--test-movie", action="store_true")
    parser.add_argument("--test-tv", action="store_true")
    parser.add_argument("--test-music", action="store_true")
    parser.add_argument("--test-doc", action="store_true")
    parser.add_argument("--test-hostnames", action="store_true")
    args = parser.parse_args()

    api_key = args.key or os.environ.get("QUASARR_API_KEY")

    if any(
        [
            args.test_movie,
            args.test_tv,
            args.test_music,
            args.test_doc,
            args.test_hostnames,
        ]
    ):
        if not api_key:
            sys.exit("API Key required for tests")
        client = QuasarrClient(args.url, api_key)
        if args.test_movie:
            sys.exit(0 if client.search_movie("tt0499549") else 1)
        if args.test_tv:
            sys.exit(0 if client.search_tv("tt0944947") else 1)
        if args.test_music:
            sys.exit(0 if client.search_music("Linkin Park") else 1)
        if args.test_doc:
            sys.exit(0 if client.search_doc("PC Gamer UK") else 1)
        if args.test_hostnames:
            sys.exit(0 if handle_hostname_test(client, interactive=False) else 1)
        return

    if not IS_TTY:
        console.print(
            Panel("[yellow]Non-interactive terminal detected[/yellow]", title="Error")
        )
        sys.exit(1)

    clear_screen()
    if not api_key:
        console.print(Panel.fit(f"[bold blue]Quasarr CLI[/bold blue]\n{args.url}"))
        api_key = questionary.password("API Key:").ask()
        if not api_key:
            sys.exit(1)

    client = QuasarrClient(args.url, api_key)

    while True:
        clear_screen()
        try:
            choice = MenuSelector(
                "Main Menu",
                [
                    ("🧪 Test All Hostnames", "test_hostnames"),
                    ("🔍 Searches", "search"),
                    ("🗞️ Feeds", "feeds"),
                    ("⬇️ Downloads", "downloads"),
                    ("🗑️ Delete All Packages", "delete_all_packages"),
                    ("🔓 Enable Sponsor Status", "enable_sponsor"),
                    ("🌐 Open Web UI", "web"),
                    ("🚪 Exit", "exit"),
                ],
                allow_back=False,
            ).run()
            if choice == "feeds":
                handle_feeds_menu(client)
            elif choice == "search":
                handle_searches_menu(client)
            elif choice == "downloads":
                show_downloads(client)
            elif choice == "delete_all_packages":
                delete_all_packages(client, interactive=True)
            elif choice == "test_hostnames":
                handle_hostname_test(client)
            elif choice == "enable_sponsor":
                if LoadingScreen(
                    "Enabling Sponsor Status", client.enable_sponsor_status
                ).run():
                    console.print("[green]Sponsor status enabled![/green]")
                else:
                    console.print("[red]Failed to enable sponsor status.[/red]")
                time.sleep(2)
            elif choice == "web":
                webbrowser.open(client.url)
            elif choice == "exit":
                if questionary.confirm("Are you sure you want to exit?").ask():
                    sys.exit(0)
            elif choice is None:
                sys.exit(0)
        except KeyboardInterrupt:
            sys.exit(0)


if __name__ == "__main__":
    try:
        run_cli()
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        import traceback

        traceback.print_exc()
        sys.exit(1)
