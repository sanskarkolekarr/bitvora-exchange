import os
import re

nav_links = [
    ('index.html', 'Home'),
    ('exchange.html', 'Exchange'),
    ('dashboard.html', 'Dashboard'),
    ('profile.html', 'Profile'),
    ('support.html', 'Support')
]

for filename in os.listdir('.'):
    if not filename.endswith('.html'):
        continue
    
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()
    
    match = re.search(r'<(nav|div)\s+class="hidden\s+md:flex[^>]*>.*?</\1>', content, flags=re.DOTALL)
    
    if match:
        tag = match.group(1)
        classes = match.group(0).split('>', 1)[0] + '>'
        classes = re.sub(r'gap-\d+', 'gap-4', classes)
        
        new_links = []
        for href, text in nav_links:
            is_active = (href == filename)
            
            font_size = "text-[10px]" if "tracking-widest" in match.group(0) else "text-xs"
            color_active = "text-zinc-100 opacity-100"
            color_inactive = "text-zinc-500 hover:text-zinc-100 transition-colors"
            
            c = f"font-label {font_size} uppercase tracking-widest " + (color_active if is_active else color_inactive)
            new_links.append(f'        <a class="{c}" href="{href}">{text}</a>')
            
        new_nav = f"<{tag} class=\"hidden md:flex gap-4 items-center\">\n" + "\n".join(new_links) + f"\n    </{tag}>"
        
        content = content[:match.start()] + new_nav + content[match.end():]
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Updated nav in {filename}")
