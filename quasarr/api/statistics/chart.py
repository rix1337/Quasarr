# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

from json import dumps

_STYLE = """
<style>
    .hist-card {
        background: var(--card-bg, #f8f9fa);
        border: 1px solid var(--card-border, #dee2e6);
        border-radius: 8px;
        padding: 15px;
    }
    .hist-wrap { position: relative; }
    .hist-svg { width: 100%; height: auto; display: block; }
    .hist-legend { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }
    .hist-legend button {
        display: inline-flex; align-items: center; gap: 6px;
        background: transparent; color: inherit; cursor: pointer;
        border: 1px solid var(--card-border, #dee2e6); border-radius: 999px;
        padding: 3px 10px; font-size: 12px;
    }
    .hist-legend button i { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
    .hist-legend button.off { opacity: .4; }
    .hist-legend button.off i { background: transparent !important; border: 1px solid currentColor; }
    .hist-card .stat-subtitle { font-size: 12px; opacity: .7; margin-top: 8px; }
    .hist-tip {
        position: absolute; top: 0; pointer-events: none; font-size: 12px; line-height: 1.5;
        background: var(--card-bg, #fff); color: inherit; white-space: nowrap;
        border: 1px solid var(--card-border, #dee2e6); border-radius: 6px;
        padding: 6px 10px; box-shadow: 0 4px 12px rgba(0,0,0,.15);
    }
    .hist-svg text { fill: currentColor; opacity: .6; font-size: 11px; }
</style>
"""

# Plain string (not an f-string) so the JS braces stay untouched.
_CHART = """
<div class="hist-card">
    <div class="hist-legend" id="__ID__-legend"></div>
    <div class="hist-wrap" id="__ID__-wrap">
        <svg class="hist-svg" id="__ID__-svg" viewBox="0 0 800 260" role="img" aria-label="__LABEL__"></svg>
        <div class="hist-tip" id="__ID__-tip" hidden></div>
    </div>
    <div class="stat-subtitle" id="__ID__-empty" hidden>__EMPTY__</div>
</div>
<script>
(function () {
    var H = __DATA__;
    var W = 800, HT = 260, L = 36, R = 12, T = 10, B = 24;
    var META = __META__;
    var off = {};
    var wrap = document.getElementById("__ID__-wrap");
    var svg = document.getElementById("__ID__-svg");
    var tip = document.getElementById("__ID__-tip");
    var NS = "http://www.w3.org/2000/svg";
    var n = H.days.length;
    var x = function (i) { return L + (W - L - R) * i / (n - 1); };

    var total = 0;
    META.forEach(function (m) { H.series[m[0]].forEach(function (v) { total += v; }); });
    if (!total) document.getElementById("__ID__-empty").hidden = false;

    function el(name, attrs, parent) {
        var e = document.createElementNS(NS, name);
        for (var k in attrs) e.setAttribute(k, attrs[k]);
        (parent || svg).appendChild(e);
        return e;
    }

    function draw() {
        // viewBox tracks the real pixel width so text stays 11px on phones
        W = Math.max(280, wrap.clientWidth);
        svg.setAttribute("viewBox", "0 0 " + W + " " + HT);
        svg.textContent = "";
        var visible = META.filter(function (m) { return !off[m[0]]; });
        var max = 4;
        visible.forEach(function (m) { max = Math.max(max, Math.max.apply(null, H.series[m[0]])); });
        var step = Math.pow(10, Math.floor(Math.log10(max / 4)));
        [1, 2, 5, 10].some(function (f) { if (step * f * 4 >= max) { step *= f; return true; } });
        var top = step * 4;
        var y = function (v) { return T + (HT - T - B) * (1 - v / top); };

        var defs = el("defs", {});
        for (var g = 0; g <= 4; g++) {
            el("line", {x1: L, x2: W - R, y1: y(g * step), y2: y(g * step), stroke: "currentColor", "stroke-opacity": .12});
            var t = el("text", {x: L - 6, y: y(g * step) + 4, "text-anchor": "end"});
            t.textContent = g * step;
        }
        for (var i = 0; i < n; i += W < 500 ? 7 : 5) {
            var xt = el("text", {x: x(i), y: HT - 6, "text-anchor": "middle"});
            xt.textContent = H.days[i].slice(5);
        }

        visible.forEach(function (m) {
            // null = nothing recorded: break the line instead of inventing values
            var v = H.series[m[0]], lines = [], area = "", d = "", start = -1;
            for (var i = 0; i <= n; i++) {
                if (i < n && v[i] !== null) {
                    if (start < 0) { start = i; d = "M" + x(i) + " " + y(v[i]); }
                    else {
                        var mx = (x(i - 1) + x(i)) / 2;
                        d += "C" + mx + " " + y(v[i - 1]) + " " + mx + " " + y(v[i]) + " " + x(i) + " " + y(v[i]);
                    }
                } else if (start >= 0) {
                    lines.push(d);
                    area += d + "L" + x(i - 1) + " " + y(0) + "L" + x(start) + " " + y(0) + "Z";
                    start = -1;
                }
            }
            var grad = el("linearGradient", {id: "__ID__-hg-" + m[0], x1: 0, y1: 0, x2: 0, y2: 1}, defs);
            el("stop", {offset: "0%", "stop-color": m[2], "stop-opacity": .28}, grad);
            el("stop", {offset: "100%", "stop-color": m[2], "stop-opacity": 0}, grad);
            el("path", {d: area, fill: "url(#__ID__-hg-" + m[0] + ")"});
            lines.forEach(function (l) {
                el("path", {d: l, fill: "none", stroke: m[2], "stroke-width": 2, "stroke-linecap": "round"});
            });
        });

        var cursor = el("line", {y1: T, y2: HT - B, stroke: "currentColor", "stroke-opacity": .3, visibility: "hidden"});
        var dots = visible.map(function (m) {
            return el("circle", {r: 4, fill: m[2], style: "stroke:var(--card-bg,#fff)", "stroke-width": 1.5, visibility: "hidden"});
        });

        svg.onmousemove = function (e) {
            var r = svg.getBoundingClientRect();
            var px = (e.clientX - r.left) / r.width * W;
            var i = Math.max(0, Math.min(n - 1, Math.round((px - L) / (W - L - R) * (n - 1))));
            cursor.setAttribute("x1", x(i)); cursor.setAttribute("x2", x(i));
            cursor.setAttribute("visibility", "visible");
            var html = "<b>" + H.days[i] + "</b>";
            visible.forEach(function (m, k) {
                var val = H.series[m[0]][i];
                dots[k].setAttribute("cx", x(i)); dots[k].setAttribute("cy", val === null ? 0 : y(val));
                dots[k].setAttribute("visibility", val === null ? "hidden" : "visible");
                html += "<br><span style='color:" + m[2] + "'>\\u25CF</span> " + m[1] + ": " + (val === null ? "no data" : val);
                var names = (H.details[m[0]] || [])[i];
                if (names && names.length) html += " (" + names.join(", ") + ")";
            });
            tip.innerHTML = html;
            tip.hidden = false;
            var left = x(i) / W * r.width + 12;
            if (left + tip.offsetWidth > r.width) left -= tip.offsetWidth + 24;
            tip.style.left = Math.max(0, left) + "px";
        };
        svg.onmouseleave = function () {
            cursor.setAttribute("visibility", "hidden");
            dots.forEach(function (d) { d.setAttribute("visibility", "hidden"); });
            tip.hidden = true;
        };
    }

    var legend = document.getElementById("__ID__-legend");
    META.forEach(function (m) {
        var b = document.createElement("button");
        b.type = "button";
        b.innerHTML = "<i style='background:" + m[2] + "'></i>" + m[1];
        b.onclick = function () { off[m[0]] = !off[m[0]]; b.classList.toggle("off", !!off[m[0]]); draw(); };
        legend.appendChild(b);
    });
    draw();
    window.addEventListener("resize", draw);
})();
</script>
"""


def _json(value):
    # "</" escaped so data can never close the script tag
    return dumps(value).replace("</", "<\\/")


def _chart(chart_id, label, empty, days, series, meta, details=None):
    return (
        _CHART.replace("__ID__", chart_id)
        .replace("__LABEL__", label)
        .replace("__EMPTY__", empty)
        .replace("__META__", _json(meta))
        .replace(
            "__DATA__",
            _json({"days": days, "series": series, "details": details or {}}),
        )
    )


def render_history_charts(history):
    downloads = _chart(
        "dl",
        "Daily downloads, last 30 days",
        "No downloads recorded yet.",
        history["days"],
        history["series"],
        [
            ["packages", "Packages downloaded", "#22c55e"],
            ["failed", "Failed downloads", "#ef4444"],
        ],
    )
    captchas = _chart(
        "cap",
        "Daily CAPTCHA decryptions, last 30 days",
        "No CAPTCHA decryptions recorded yet.",
        history["days"],
        history["series"],
        [
            ["auto", "Automatic", "#3b82f6"],
            ["manual", "Manual", "#f59e0b"],
            ["decrypt_failed", "Failed decryptions", "#ef4444"],
        ],
    )
    issues = _chart(
        "iss",
        "Daily hostname availability, last 30 days",
        "No hostname data recorded yet.",
        history["days"],
        {
            "hosts": history["hosts"],
            "issues": history["issues"],
            "timeouts": history["timeouts"],
        },
        [
            ["hosts", "Configured hostnames", "#22c55e"],
            ["issues", "Hostnames with errors", "#ef4444"],
            ["timeouts", "Hostnames with timeouts", "#f59e0b"],
        ],
        {"issues": history["issue_hosts"], "timeouts": history["timeout_hosts"]},
    )
    return f"{_STYLE}<h3>📦 Downloads</h3>{downloads}<h3>🧩 CAPTCHAs</h3>{captchas}<h3>🌐 Hostnames</h3>{issues}"
