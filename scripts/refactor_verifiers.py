import os
import re
from pathlib import Path

CHAINS_DIR = Path(r"c:\Users\HP\OneDrive\Documents\Lmao Exchange Site\backend\services\tx_verifier\chains")

# Pattern matches the dataclass import, the VerificationResult dataclass definition
dataclass_import = re.compile(r'from dataclasses import dataclass\n', re.MULTILINE)
verification_class = re.compile(
    r'@dataclass\nclass VerificationResult:\n\s+valid: bool\n\s+confirmations: int = 0\n\s+required_confirmations: int = 0\n\s+amount_detected: float = 0\.0\n\s+recipient_address: str = ""\n\s+explorer_url: str = ""\n\s+error: Optional\[str\] = None\n*',
    re.MULTILINE
)

for file in CHAINS_DIR.glob("*.py"):
    if file.name == "__init__.py":
        continue
    
    with open(file, 'r', encoding='utf-8') as f:
        content = f.read()

    original = content

    # Replace dataclass import with the model import
    if "from dataclass" in content or "from dataclasses" in content:
        content = dataclass_import.sub('', content)

    # Replace the class definition with import
    if "class VerificationResult:" in content:
        content = verification_class.sub('from ..models import VerificationResult\n\n', content)

    if original != content:
        with open(file, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Refactored VerificationResult in {file.name}")
