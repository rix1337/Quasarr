# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import quasarr.providers.html_images as images
from quasarr.providers.version import get_version


def render_centered_html(inner_content, footer_content=""):
    head = (
        '''
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Quasarr</title>
        <link rel="icon" href="'''
        + images.favicon
        + """" type="image/png">
        <style>
            /* Theme variables */
            :root {
                --bg-color: #ffffff;
                --fg-color: #212529;
                --card-bg: #ffffff;
                --card-shadow: rgba(0, 0, 0, 0.1);
                --card-border: #dee2e6;
                --primary: #0d6efd;
                --secondary: #6c757d;
                --code-bg: #f8f9fa;
                --spacing: 1rem;
                --info-border: #2d5a2d;
                --setup-border: var(--primary);
                --divider-color: #dee2e6;
                --border-color: #dee2e6;
                --btn-subtle-bg: #e9ecef;
                --btn-subtle-border: #ced4da;
                --text-muted: #666;
                --link-color: #0d6efd;
                --success-color: #198754;
                --success-bg: #d1e7dd;
                --success-border: #a3cfbb;
                --error-color: #dc3545;
                --error-bg: #f8d7da;
                --error-border: #f1aeb5;
            }
            @media (prefers-color-scheme: dark) {
                :root {
                    --bg-color: #181a1b;
                    --fg-color: #f1f1f1;
                    --card-bg: #2d3748;
                    --card-shadow: rgba(0, 0, 0, 0.5);
                    --card-border: #4a5568;
                    --code-bg: #2c2f33;
                    --info-border: #4a8c4a;
                    --setup-border: var(--primary);
                    --divider-color: #4a5568;
                    --border-color: #4a5568;
                    --btn-subtle-bg: #444;
                    --btn-subtle-border: #666;
                    --text-muted: #a0aec0;
                    --link-color: #63b3ed;
                    --success-color: #68d391;
                    --success-bg: #1c4532;
                    --success-border: #276749;
                    --error-color: #fc8181;
                    --error-bg: #3d2d2d;
                    --error-border: #c53030;
                }
            }
            /* Info box styling */
            .info-box {
                border: 1px solid var(--info-border);
                border-radius: 8px;
                padding: 16px;
                margin-bottom: 24px;
            }
            .info-box h3 {
                margin-top: 0;
                color: var(--info-border);
            }
            /* Setup box styling */
            .setup-box {
                border: 1px solid var(--setup-border);
                border-radius: 8px;
                padding: 16px;
                margin-bottom: 24px;
            }
            .setup-box h3 {
                margin-top: 0;
                color: var(--setup-border);
            }
            a.action-card,
            a.action-card {
                text-decoration: none !important;
            }
            /* Status pill styling */
            .status-pill {
                display: inline-flex;
                align-items: center;
                gap: 6px;
                padding: 6px 12px;
                border-radius: 0.5rem;
                font-size: 0.9rem;
                font-weight: 500;
                margin: 8px 0;
            }
            .status-pill.success {
                background: var(--success-bg);
                color: var(--success-color);
                border: 1px solid var(--success-border);
            }
            .status-pill.error {
                background: var(--error-bg);
                color: var(--error-color);
                border: 1px solid var(--error-border);
            }
            /* Subtle button styling (ghost style) */
            .btn-subtle {
                background: transparent;
                color: var(--fg-color);
                border: 1.5px solid var(--btn-subtle-border);
                padding: 8px 16px;
                border-radius: 0.5rem;
                cursor: pointer;
                font-size: 1rem;
                font-weight: 500;
                transition: background-color 0.2s ease, border-color 0.2s ease;
            }
            .btn-subtle:hover {
                background: var(--btn-subtle-bg);
                border-color: var(--fg-color);
            }
            /* Divider styling */
            .section-divider {
                margin-top: 20px;
                padding-top: 20px;
                border-top: 1px solid var(--divider-color);
            }
            /* Logo and heading alignment */
            h1 {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                margin-bottom: 0.5rem;
                font-size: 2rem;
            }
            .logo {
                width: 48px;
                height: 48px;
                margin-right: 0.5rem;
            }
            /* Form labels and inputs */
            label {
                display: block;
                font-weight: 600;
                margin-bottom: 0.5rem;
            }
            input, select {
                display: block;
                width: 100%;
                padding: 0.5rem;
                font-size: 1rem;
                border: 1px solid var(--card-border);
                border-radius: 0.5rem;
                background-color: var(--card-bg);
                color: var(--fg-color);
                box-sizing: border-box;
            }
            *, *::before, *::after {
                box-sizing: border-box;
            }
            /* make body a column flex so footer can stick to bottom */
            html, body {
                margin: 0;
                padding: 0;
                width: 100%;
                height: 100%;
                background-color: var(--bg-color);
                color: var(--fg-color);
                font-family: system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue',
                    'Noto Sans', Arial, sans-serif;
                line-height: 1.6;
                display: flex;
                flex-direction: column;
                min-height: 100vh;
            }
            .outer {
                flex: 1;
                display: flex;
                justify-content: center;
                align-items: center;
                padding: var(--spacing);
            }
            .inner {
                background-color: var(--card-bg);
                border-radius: 1rem;
                box-shadow: 0 0.5rem 1.5rem var(--card-shadow);
                padding: calc(var(--spacing) * 2);
                text-align: center;
                width: 100%;
                max-width: 600px;
            }
            h2 {
                margin-top: var(--spacing);
                margin-bottom: 0.75rem;
                font-size: 1.5rem;
            }
            h3 {
                margin-top: var(--spacing);
                margin-bottom: 0.5rem;
                font-size: 1.125rem;
                font-weight: 500;
            }
            p {
                margin: 0.5rem 0;
            }
            .copy-input {
                background-color: var(--code-bg);
            }
            .url-wrapper .api-key-wrapper {
                display: flex;
                gap: 0.5rem;
                flex-wrap: wrap;
                justify-content: center;
                margin-bottom: var(--spacing);
            }
            .captcha-container {
                background-color: var(--secondary);
            }
            /* Responsive scaling for fixed-width CAPTCHA iframe (370px) */
            /* PROBLEM: The drag and drop breaks */
            @media (max-width: 400px) {
                #puzzle-captcha {
                    zoom: 0.75;
                }
            }
            button {
                padding: 0.5rem 1rem;
                font-size: 1rem;
                border-radius: 0.5rem;
                font-weight: 500;
                cursor: pointer;
                transition: background-color 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
                margin-top: 0.5rem;
            }
            .btn-primary {
                background-color: var(--primary);
                color: #fff;
                border: 1.5px solid #0856c7;
            }
            .btn-primary:hover {
                background-color: #0b5ed7;
                border-color: #084298;
                box-shadow: 0 2px 6px rgba(13, 110, 253, 0.4);
            }
            .btn-secondary {
                background-color: var(--secondary);
                color: #fff;
                border: 1.5px solid #565e64;
            }
            .btn-secondary:hover {
                background-color: #5c636a;
                border-color: #41464b;
                box-shadow: 0 2px 6px rgba(108, 117, 125, 0.4);
            }
            a {
                color: var(--link-color);
                text-decoration: none;
            }
            a:hover {
                text-decoration: underline;
            }
            /* footer styling */
            footer {
                text-align: center;
                font-size: 0.75rem;
                color: var(--text-muted);
                padding: 0.5rem 0;
            }
            footer a {
                color: var(--text-muted);
                margin: 0 0;
            }
            footer a:hover {
                color: var(--fg-color);
            }
            /* Global Modal Styles */
            .status-modal-overlay {
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: rgba(0, 0, 0, 0.5);
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 9999;
                visibility: hidden;
                opacity: 0;
                transition: visibility 0s, opacity 0.2s;
            }
            .status-modal-overlay.active {
                visibility: visible;
                opacity: 1;
            }
            .status-modal {
                background: var(--card-bg);
                border-radius: 0.5rem;
                padding: 1.5rem;
                max-width: 400px;
                width: 90%;
                box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
                transform: scale(0.9);
                transition: transform 0.2s;
            }
            .status-modal-overlay.active .status-modal {
                transform: scale(1);
            }
            .status-modal h3 {
                margin: 0 0 1rem 0;
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }
            .status-modal p {
                margin: 0 0 1rem 0;
                word-break: break-word;
            }
            .status-modal .btn-row {
                display: flex;
                gap: 0.5rem;
                justify-content: flex-end;
            }
        </style>
    </head>"""
    )

    # Build footer content
    version_text = f"Quasarr v.{get_version()}"
    if footer_content:
        footer_html = f"{footer_content} · {version_text}"
    else:
        footer_html = version_text

    # Global modal script
    modal_script = """
    <script>
        function showModal(title, content, buttonsHtml) {
            let overlay = document.getElementById('global-modal-overlay');
            if (!overlay) {
                overlay = document.createElement('div');
                overlay.id = 'global-modal-overlay';
                overlay.className = 'status-modal-overlay';
                overlay.innerHTML = `
                    <div class="status-modal">
                        <h3 id="global-modal-title"></h3>
                        <div id="global-modal-content"></div>
                        <div class="btn-row" id="global-modal-buttons"></div>
                    </div>
                `;
                document.body.appendChild(overlay);
                
                overlay.addEventListener('click', function(e) {
                    if (e.target === overlay) closeModal();
                });
            }
            
            document.getElementById('global-modal-title').innerHTML = title;
            document.getElementById('global-modal-content').innerHTML = content;
            
            let btns = buttonsHtml || '<button class="btn-secondary" onclick="closeModal()">Close</button>';
            document.getElementById('global-modal-buttons').innerHTML = btns;
            
            // Small timeout to allow CSS transition
            requestAnimationFrame(() => {
                overlay.classList.add('active');
            });
        }
        
        function closeModal() {
            const overlay = document.getElementById('global-modal-overlay');
            if (overlay) {
                overlay.classList.remove('active');
                setTimeout(() => {
                    if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
                }, 200);
            }
        }
    </script>
    """

    body = f"""
    {head}
    <body>
        <div class="outer">
            <div class="inner">
                {inner_content}
            </div>
        </div>
        <footer>
            {footer_html}
        </footer>
        {modal_script}
    </body>
    """
    return f"<html>{body}</html>"


def render_button(text, button_type="primary", attributes=None):
    cls = "btn-primary" if button_type == "primary" else "btn-secondary"
    attr_str = ""
    if attributes:
        attr_str = " ".join(f'{key}="{value}"' for key, value in attributes.items())
    return f'<button class="{cls}" {attr_str}>{text}</button>'


def render_form(header, form="", script="", footer_content=""):
    content = f'''
    <h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
    <h2>{header}</h2>
    {form}
    {script}
    '''
    return render_centered_html(content, footer_content)


def render_success(message, timeout=10, optional_text=""):
    button_html = render_button(
        f"Wait time... {timeout}", "secondary", {"id": "nextButton", "disabled": "true"}
    )
    script = f"""
        <script>
            let counter = {timeout};
            const btn = document.getElementById('nextButton');
            const interval = setInterval(() => {{
                counter--;
                btn.innerText = `Wait time... ${{counter}}`;
                if (counter === 0) {{
                    clearInterval(interval);
                    btn.innerText = 'Continue';
                    btn.disabled = false;
                    btn.className = 'btn-primary';
                    btn.onclick = () => window.location.href = '/';
                }}
            }}, 1000);
        </script>
    """
    content = f'''<h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
    <h2>{message}</h2>
    {optional_text}
    {button_html}
    {script}
    '''
    return render_centered_html(content)


def render_fail(message):
    button_html = render_button(
        "Back", "secondary", {"onclick": "window.location.href='/'"}
    )
    return render_centered_html(f"""<h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
        <h2>{message}</h2>
        {button_html}
    """)
