import os

BASE_DIR = r"C:\Users\saisu\.gemini\antigravity-ide\scratch\modbus-web-app"

with open(os.path.join(BASE_DIR, "static", "index.html"), "r", encoding="utf-8") as f:
    html = f.read()

with open(os.path.join(BASE_DIR, "static", "style.css"), "r", encoding="utf-8") as f:
    css = f.read()

with open(os.path.join(BASE_DIR, "static", "app.js"), "r", encoding="utf-8") as f:
    js = f.read()

# Replace <link rel="stylesheet" href="/static/style.css"> with inline <style>
html = html.replace('<link rel="stylesheet" href="/static/style.css">', f'<style>\n{css}\n</style>')

# Replace <script src="/static/app.js"></script> with inline <script>
html = html.replace('<script src="/static/app.js"></script>', f'<script>\n{js}\n</script>')

# Save bundled index.html
with open(os.path.join(BASE_DIR, "bundled_index.html"), "w", encoding="utf-8") as f:
    f.write(html)

print(f"Bundled HTML created successfully. Size: {len(html)} bytes")
