# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337


def get_dj_download_links(shared_state, url, mirror, title, password):
    """
    KEEP THE SIGNATURE EVEN IF SOME PARAMETERS ARE UNUSED!

    DJ source handler - the site itself acts as a protected crypter.
    Returns the URL for CAPTCHA solving via userscript.
    """

    return {"links": [[url, "junkies"]]}
