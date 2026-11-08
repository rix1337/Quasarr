# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""The userscript template for sites users set up themselves.

Unlike the shipped userscripts it is readable and has no update URL: users add
their own code to it, and Quasarr must never overwrite that code.
"""

_TEMPLATE = r"""// ==UserScript==
// @name         Quasarr: my own site (template)
// @namespace    quasarr-own-sites
// @version      1.0
// @description  Sends the download links of a release page back to Quasarr. Does nothing until you add your code.
{matches}
// @grant        none
// @run-at       document-idle
// ==/UserScript==

/*
 * This template does NOT work out of the box.
 *
 * Quasarr opens a release page of your site with the transfer details in its
 * address. The connection part below keeps them while you click through the
 * site and sends the links you collect back to Quasarr. Finding those links,
 * and solving whatever the site asks for first, is up to the code you write
 * in "Your code".
 *
 * Adjust the @match lines above to the pages your code runs on. The script has
 * no update URL on purpose, so your code is never overwritten.
 */

(function () {
  "use strict";

  // ===== Quasarr connection: do not modify ===================================
  const STORAGE_KEY = "quasarr-transfer";
  const query = new URLSearchParams(window.location.search);
  if (query.get("transfer_url") && query.get("pkg_id")) {
    sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        transferUrl: query.get("transfer_url"),
        packageId: query.get("pkg_id"),
        title: query.get("pkg_title") || "",
        password: query.get("pkg_pass") || "",
      })
    );
  }
  // null unless Quasarr opened this page
  const transfer = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || "null");

  async function deflateRaw(text) {
    const stream = new Blob([text]).stream().pipeThrough(new CompressionStream("deflate-raw"));
    return new Uint8Array(await new Response(stream).arrayBuffer());
  }

  function base64Url(bytes) {
    let binary = "";
    bytes.forEach((byte) => (binary += String.fromCharCode(byte)));
    return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  function backToQuasarr(parameter, value) {
    sessionStorage.removeItem(STORAGE_KEY);
    window.location.href =
      transfer.transferUrl + "?pkg_id=" + encodeURIComponent(transfer.packageId) + "&" + parameter + "=" + value;
  }

  // Sends the links to Quasarr, which hands them to JDownloader.
  async function sendLinksToQuasarr(links) {
    if (!transfer) return;
    const clean = links.map((link) => String(link).trim()).filter(Boolean);
    if (!clean.length) return reportFailureToQuasarr("No download links found");
    backToQuasarr("links", base64Url(await deflateRaw(clean.join("\n"))));
  }

  // Tells Quasarr that this release cannot be downloaded.
  function reportFailureToQuasarr(reason) {
    if (!transfer) return;
    backToQuasarr("error", encodeURIComponent(reason));
  }
  // ===== End of the Quasarr connection =======================================

  // ===== Your code ===========================================================
  // transfer.title and transfer.password describe the release Quasarr asked for.
  // Return the download links of this page, for example crypter or hoster links.
  // Return [] to wait, for example while you solve something on the page; call
  // sendLinksToQuasarr(links) yourself once the links appear.
  async function collectLinks() {
    // Example:
    // return [...document.querySelectorAll('a[href*="filecrypt."]')].map((a) => a.href);
    return [];
  }
  // ===== End of your code ====================================================

  if (transfer) {
    collectLinks().then((links) => {
      if (links.length) sendLinksToQuasarr(links);
    });
  }
})();
"""


def custom_user_js(hostnames):
    """The template, matching the sites the user set up for it."""
    hosts = sorted(set(hostnames)) or ["example.invalid"]
    matches = "\n".join(
        f"// @match        *://{host}/*\n// @match        *://*.{host}/*"
        for host in hosts
    )
    return _TEMPLATE.replace("{matches}", matches)
