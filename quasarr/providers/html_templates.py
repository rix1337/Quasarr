# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import quasarr.providers.html_images as images
from quasarr.providers.version import get_version


def render_centered_html(inner_content):
    head = '''
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Quasarr</title>
        <link rel="icon" href="''' + images.logo + '''" type="image/png">
        <style>
            /* Theme variables */
            :root {
                --bg-color: #ffffff;
                --fg-color: #212529;
                --card-bg: #ffffff;
                --card-shadow: rgba(0, 0, 0, 0.1);
                --primary: #0d6efd;
                --secondary: #6c757d;
                --code-bg: #f8f9fa;
                --spacing: 1rem;
            }
            @media (prefers-color-scheme: dark) {
                :root {
                    --bg-color: #181a1b;
                    --fg-color: #f1f1f1;
                    --card-bg: #242526;
                    --card-shadow: rgba(0, 0, 0, 0.5);
                    --code-bg: #2c2f33;
                }
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
                border: 1px solid #ced4da;
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
                max-width: fit-content;
            }
            /* No padding on the sides for captcha view on small screens */
            @media (max-width: 600px) {
                body:has(iframe) .outer {
                    padding-left: 0;
                    padding-right: 0;
                }
                body:has(iframe) .inner {
                    padding-left: 0;
                    padding-right: 0;
                }
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
            button {
                padding: 0.5rem 1rem;
                font-size: 1rem;
                border-radius: 0.5rem;
                font-weight: 500;
                cursor: pointer;
                transition: background-color 0.2s ease, border-color 0.2s ease;
                border: none;
                margin-top: 0.5rem;
            }
            .btn-primary {
                background-color: var(--primary);
                color: #fff;
            }
            .btn-secondary {
                background-color: var(--secondary);
                color: #fff;
            }
            a {
                color: var(--primary);
                text-decoration: none;
            }
            a:hover {
               
            }
            /* footer styling */
            footer {
                text-align: center;
                font-size: 0.75rem;
                color: var(--secondary);
                padding: 0.5rem 0;
            }
        </style>
    </head>'''

    body = f'''
    {head}
    <body>
        <div class="outer">
            <div class="inner">
                {inner_content}
            </div>
        </div>
        <footer>
            Quasarr v.{get_version()}
        </footer>
    </body>
    '''
    return f'<html>{body}</html>'


def render_button(text, button_type="primary", attributes=None):
    cls = "btn-primary" if button_type == "primary" else "btn-secondary"
    attr_str = ''
    if attributes:
        attr_str = ' '.join(f'{key}="{value}"' for key, value in attributes.items())
    return f'<button class="{cls}" {attr_str}>{text}</button>'


def render_form(header, form="", script=""):
    content = f'''
    <h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
    <h2>{header}</h2>
    {form}
    {script}
    '''
    return render_centered_html(content)


def render_success(message, timeout=10, optional_text=""):
    button_html = render_button(f"Wait time... {timeout}", "secondary", {"id": "nextButton", "disabled": "true"})
    script = f'''
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
    '''
    content = f'''<h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
    <h2>{message}</h2>
    {optional_text}
    {button_html}
    {script}
    '''
    return render_centered_html(content)


def render_fail(message):
    button_html = render_button("Back", "secondary", {"onclick": "window.location.href='/'"})
    return render_centered_html(f"""<h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
        <h2>{message}</h2>
        {button_html}
    """)
