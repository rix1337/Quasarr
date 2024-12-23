# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

def render_centered_html(inner_content):
    style_outer = """
    display: flex;
    justify-content: center;
    align-items: center;
    height: 100vh;
    max-height: 100vh;
    overflow-y: auto;
    overflow-x: hidden; /* Prevent horizontal scrolling */
    width: 100%; /* Ensure it spans full width */
    background-color: #212529;
    color: #fff;
    font-family: system-ui,-apple-system,'Segoe UI',Roboto,'Helvetica Neue',
    'Noto Sans','Liberation Sans',Arial,sans-serif,'Apple Color Emoji',
    'Segoe UI Emoji','Segoe UI Symbol','Noto Color Emoji';
    """
    style_inner = """
    background-color: #fff;
    border-radius: 0.375rem;
    box-shadow: 0 0.5rem 1rem rgba(0, 0, 0, 0.15);
    padding: 4px;
    text-align: center;
    color: #212529;
    font-size: 1rem;
    font-weight: 400;
    line-height: 1.5;
    box-sizing: border-box; /* Ensure padding doesn’t exceed boundaries */
    max-width: 100%; /* Allow content to shrink */
    margin: auto;
    """

    return f'''
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Quasarr</title>
    </head>
    <body>
    <div style="{style_outer.strip()}">
        <div style="{style_inner.strip()}">
            {inner_content}
        </div>
    </div>
    </body>
    </html>
    '''


def render_button(text, button_type="primary", attributes=None):
    base_style = (
        "padding: 0.375rem 0.75rem; font-size: 1rem; line-height: 1.5; "
        "border-radius: 0.375rem; color: #fff; display: inline-block; "
        "font-weight: 400; text-align: center; vertical-align: middle; "
        "cursor: pointer; -webkit-user-select: none; -moz-user-select: none; "
        "user-select: none; transition: color 0.15s ease-in-out, "
        "background-color 0.15s ease-in-out, border-color 0.15s ease-in-out, "
        "box-shadow 0.15s ease-in-out; "
    )

    if button_type == "primary":
        style = base_style + "background-color: #0d6efd; border: 1px solid #0d6efd; "
    else:
        style = base_style + "background-color: #6c757d; border: 1px solid #6c757d; "

    attr_str = ' '.join(f'{key}="{value}"' for key, value in attributes.items()) if attributes else ""

    return f'<button style="{style}" {attr_str}>{text}</button>'


def render_form(header, form="", script=""):
    styles = """
    <style>
        input, select {
            display: block;
            padding: .375rem .75rem;
            width: 100%;
            font-size: 1rem;
            font-weight: 400;
            line-height: 1.5;
            color: #212529;
            background-color: #fff;
            border: 1px solid #dee2e6;
            border-radius: .375rem;
            transition: border-color .15s ease-in-out, box-shadow .15s ease-in-out;
            text-align: center;
            margin: 10px auto;
        }
    </style>
    """
    content = f'''
    <h1>Quasarr</h1>
    <h3>{header}</h3>
    {styles}
    {form}
    {script}
    '''
    return render_centered_html(content)


def render_success(message, timeout=10):
    button_html = render_button(f"Wait time... {timeout}", "secondary", {"id": "nextButton", "disabled": "true"})
    script = f"""
                <script>
                    var counter = {timeout};
                    var interval = setInterval(function() {{
                        counter--;
                        document.getElementById('nextButton').innerText = 'Wait time... ' + counter;
                        if (counter === 0) {{
                            clearInterval(interval);
                            document.getElementById('nextButton').innerText = 'Continue';
                            document.getElementById('nextButton').disabled = false;
                            document.getElementById('nextButton').onclick = function() {{
                                window.location.href='/';
                            }};
                            // Change button style to primary
                            document.getElementById('nextButton').style.backgroundColor = '#0d6efd';
                            document.getElementById('nextButton').style.borderColor = '#0d6efd';
                        }}
                    }}, 1000);
                </script>
                """
    content = f"""<h1>Quasarr</h1>
                <h3>{message}</h3>
                {button_html}
                {script}
                """
    return render_centered_html(content)


def render_fail(message):
    button_html = render_button("Back", "secondary", {"onclick": "window.location.href='/'"})
    return render_centered_html(f"""<h1>Quasarr</h1>
                        <h3>{message}</h3>
                        {button_html}
                        """)
