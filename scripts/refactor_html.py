import os
import re
from pathlib import Path

PAGES_DIR = Path(r"c:\Users\HP\OneDrive\Documents\Lmao Exchange Site\pages")

def refactor_html(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    original = content

    # 1. Replace tailwind config script
    tailwind_pattern = re.compile(r'<script>\s*tailwind\.config\s*=\s*\{[\s\S]*?\}\s*</script>', re.MULTILINE)
    content = tailwind_pattern.sub(r'<script src="/assets/js/tailwind-config.js"></script>', content)

    # 2. Add components.js before </head> if not exists
    if '/assets/js/components.js' not in content:
        content = content.replace('</head>', '    <script src="/assets/js/components.js" defer></script>\n</head>')

    # 3. Remove noise-overlay
    content = re.sub(r'<div class="noise-overlay.*?</div>\s*', '', content)

    # 4. Remove custom-cursor
    content = re.sub(r'<div class="custom-cursor.*?id="cursor".*?</div>\s*', '', content)

    # 5. Remove navbar
    navbar_pattern = re.compile(r'<!-- Floating Pill Navbar -->\s*<nav id="navbar"[\s\S]*?</nav>\s*', re.MULTILINE)
    content = navbar_pattern.sub('', content)
    # Generic fallback if comment is missing
    generic_navbar = re.compile(r'<nav id="navbar"[\s\S]*?</nav>\s*', re.MULTILINE)
    content = generic_navbar.sub('', content)

    # 6. Remove footer
    footer_pattern = re.compile(r'<!-- Premium Footer Section -->\s*<footer[\s\S]*?</footer>\s*', re.MULTILINE)
    content = footer_pattern.sub('', content)
    generic_footer = re.compile(r'<footer[\s\S]*?</footer>\s*', re.MULTILINE)
    content = generic_footer.sub('', content)

    # 7. Remove mobile overlay and its associated inline script
    mobile_overlay_pattern = re.compile(r'<!-- Mobile Menu Overlay -->\s*<div id="mobile-overlay"[\s\S]*?</div>\s*<script>[\s\S]*?mobile-menu-trigger[\s\S]*?</script>', re.MULTILINE)
    content = mobile_overlay_pattern.sub('', content)

    # Secondary mobile overlay removal (just the div if script is separated)
    generic_mobile_overlay = re.compile(r'<div id="mobile-overlay"[\s\S]*?</div>\s*', re.MULTILINE)
    content = generic_mobile_overlay.sub('', content)

    # 8. Remove old mobile menu (id="mobile-menu" that was present in index.html)
    old_mobile_menu = re.compile(r'<!-- Mobile Full Screen Menu Overlay -->\s*<div id="mobile-menu"[\s\S]*?</div>\s*', re.MULTILINE)
    content = old_mobile_menu.sub('', content)

    # 9. Remove auth-aware navbar inline script
    auth_script_pattern = re.compile(r'<script>\s*// Auth-aware navbar toggle[\s\S]*?</script>\s*', re.MULTILINE)
    content = auth_script_pattern.sub('', content)

    # 10. Remove initial drop-in entrance script
    dropin_script_pattern = re.compile(r'<script>\s*const navbar = document\.getElementById\(\'navbar\'\);[\s\S]*?// Mobile menu logic[\s\S]*?</script>\s*', re.MULTILINE)
    content = dropin_script_pattern.sub('', content)

    if original != content:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Refactored {file_path.name}")
    else:
        print(f"No changes needed for {file_path.name}")

if __name__ == '__main__':
    for file in PAGES_DIR.glob('*.html'):
        refactor_html(file)
