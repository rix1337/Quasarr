# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

from quasarr.storage.setup.arr import (
    missing_arr_client_requirement,
    select_arr_client_config,
    split_arr_required_sites,
)
from quasarr.storage.setup.common import (
    add_no_cache_headers,
    render_reconnect_success,
    setup_auth,
)
from quasarr.storage.setup.crypters import (
    get_crypter_settings_data,
    initialize_crypter_settings,
    refresh_crypter_settings,
    save_crypter_settings,
)
from quasarr.storage.setup.flaresolverr import (
    delete_skip_flaresolverr_preference,
    flaresolverr_config,
    flaresolverr_form_html,
    get_flaresolverr_status_data,
    save_flaresolverr_url,
)
from quasarr.storage.setup.hostnames import (
    check_credentials,
    clear_skip_login,
    get_skip_login,
    hostname_credentials_config,
    hostname_form_html,
    hostnames_config,
    import_hostnames_from_url,
    save_hostnames,
)
from quasarr.storage.setup.jdownloader import (
    jdownloader_config,
    save_jdownloader_settings,
    verify_jdownloader_credentials,
)
from quasarr.storage.setup.notifications import (
    get_notification_settings_data,
    initialize_notification_settings,
    refresh_notification_settings,
    save_notification_settings,
    send_notification_test,
)
from quasarr.storage.setup.path import path_config
from quasarr.storage.setup.radarr import (
    delete_skip_radarr_preference,
    get_radarr_settings_data,
    initialize_radarr_client,
    is_radarr_configured,
    is_radarr_skipped,
    radarr_config,
    refresh_radarr_client,
    save_radarr_settings,
)
from quasarr.storage.setup.sonarr import (
    delete_skip_sonarr_preference,
    get_sonarr_settings_data,
    initialize_sonarr_client,
    is_sonarr_configured,
    is_sonarr_skipped,
    refresh_sonarr_client,
    save_sonarr_settings,
    sonarr_config,
)
from quasarr.storage.setup.timeouts import (
    get_timeout_slow_mode_settings_data,
    initialize_timeout_slow_mode_settings,
    refresh_timeout_slow_mode_settings,
    save_timeout_slow_mode_settings,
)

__all__ = [
    "add_no_cache_headers",
    "check_credentials",
    "clear_skip_login",
    "delete_skip_flaresolverr_preference",
    "delete_skip_radarr_preference",
    "delete_skip_sonarr_preference",
    "flaresolverr_config",
    "flaresolverr_form_html",
    "get_crypter_settings_data",
    "get_flaresolverr_status_data",
    "get_notification_settings_data",
    "get_radarr_settings_data",
    "get_skip_login",
    "get_sonarr_settings_data",
    "hostname_credentials_config",
    "hostname_form_html",
    "hostnames_config",
    "import_hostnames_from_url",
    "initialize_crypter_settings",
    "initialize_notification_settings",
    "initialize_radarr_client",
    "initialize_sonarr_client",
    "is_radarr_configured",
    "is_radarr_skipped",
    "is_sonarr_configured",
    "is_sonarr_skipped",
    "jdownloader_config",
    "missing_arr_client_requirement",
    "path_config",
    "radarr_config",
    "refresh_crypter_settings",
    "refresh_notification_settings",
    "refresh_radarr_client",
    "refresh_sonarr_client",
    "render_reconnect_success",
    "save_crypter_settings",
    "save_flaresolverr_url",
    "save_hostnames",
    "save_jdownloader_settings",
    "save_notification_settings",
    "save_radarr_settings",
    "save_sonarr_settings",
    "save_timeout_slow_mode_settings",
    "select_arr_client_config",
    "split_arr_required_sites",
    "send_notification_test",
    "setup_auth",
    "sonarr_config",
    "get_timeout_slow_mode_settings_data",
    "initialize_timeout_slow_mode_settings",
    "refresh_timeout_slow_mode_settings",
    "verify_jdownloader_credentials",
]
