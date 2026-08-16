import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LOCALES_DIR = BASE_DIR / "web" / "locales"

def get_translations(lang: str = "en") -> dict:
    file_path = LOCALES_DIR / f"{lang}.json"
    if not file_path.exists():
        file_path = LOCALES_DIR / "en.json"

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception as e:
        print(f"Localization loading error: {e}")
        return {}