import re
from pathlib import Path

css_path = Path(r"c:\Users\HP\OneDrive\Documents\Lmao Exchange Site\assets\css\styles.css")
with open(css_path, "r", encoding="utf-8") as f:
    content = f.read()

# This simple regex assumes the @media block doesn't contain nested media queries (which it doesn't in standard CSS).
# We match @media (max-width: 768px) { ... } safely avoiding nested braces issues by using a balanced bracket matcher or a simpler approach.
# Since python regex doesn't support recursive balanced brackets easily, we'll iterate through the string.

def extract_and_remove_media(text, target_media):
    extracted_rules = []
    idx = 0
    while True:
        idx = text.find(target_media, idx)
        if idx == -1:
            break
        # Find the opening brace
        open_brace = text.find('{', idx)
        if open_brace == -1:
            break
        brace_count = 1
        curr = open_brace + 1
        while brace_count > 0 and curr < len(text):
            if text[curr] == '{':
                brace_count += 1
            elif text[curr] == '}':
                brace_count -= 1
            curr += 1
        
        # We found the end of the block
        block = text[idx:curr]
        inner_content = text[open_brace+1:curr-1].strip()
        extracted_rules.append(inner_content)
        
        # Remove the block from text
        text = text[:idx] + text[curr:]
    
    return text, extracted_rules

new_content, rules = extract_and_remove_media(content, "@media (max-width: 768px)")

if rules:
    merged_block = "\n@media (max-width: 768px) {\n"
    for r in rules:
        merged_block += "    " + r.replace("\n", "\n    ") + "\n\n"
    merged_block += "}\n"
    
    new_content = new_content.strip() + "\n" + merged_block
    
    with open(css_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    print("Successfully merged media queries!")
else:
    print("No media queries found to merge.")

