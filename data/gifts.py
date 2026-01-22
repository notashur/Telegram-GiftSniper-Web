import os
import json
import requests

GIFT_URL = "https://cdn.changes.tg/gifts/id-to-name.json"
LOCAL_GIFT_FILE = os.path.join(os.path.dirname(__file__), "gifts.json")

def load_gift_mappings():
    """
    Load gift mappings from local file if present,
    otherwise fetch from remote and save.
    """
    if os.path.exists(LOCAL_GIFT_FILE):
        with open(LOCAL_GIFT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    # First run → fetch from remote
    response = requests.get(GIFT_URL, timeout=10)
    if response.status_code == 200:
        gift_mappings = response.json()
        with open(LOCAL_GIFT_FILE, "w", encoding="utf-8") as f:
            json.dump(gift_mappings, f, indent=4, ensure_ascii=False)
        return gift_mappings
    else:
        raise RuntimeError(f"Failed to fetch gift mappings: {response.status_code}")

# Export for import in Flask
GIFT_MAPPINGS = load_gift_mappings()

BACKDROP_CENTER_COLORS = {
    "Black": "#363738", "Electric Purple": "#ca70c6", "Lavender": "#b789e4", "Cyberpunk": "#858ff3",
    "Electric Indigo": "#a980f3", "Neon Blue": "#7596f9", "Navy Blue": "#6c9edd", "Sapphire": "#58a3c8",
    "Sky Blue": "#58b4c8", "Azure Blue": "#5db1cb", "Pacific Cyan": "#5abea6", "Aquamarine": "#60b195",
    "Pacific Green": "#6fc793", "Emerald": "#78c585", "Mint Green": "#7ecb82", "Malachite": "#95b457",
    "Shamrock Green": "#8ab163", "Lemongrass": "#aeb85a", "Light Olive": "#c2af64", "Satin Gold": "#bf9b47",
    "Pure Gold": "#ccab41", "Amber": "#dab345", "Caramel": "#d09932", "Orange": "#d19a3a",
    "Carrot Juice": "#db9867", "Coral Red": "#da896b", "Persimmon": "#e7a75a", "Strawberry": "#dd8e6f",
    "Raspberry": "#e07b85", "Mystic Pearl": "#d08b6d", "Fandango": "#e28ab6", "Dark Lilac": "#b17da5",
    "English Violet": "#b186bb", "Moonstone": "#7eb1b4", "Pine Green": "#6ba97c", "Hunter Green": "#8fae78",
    "Pistachio": "#97b07c", "Khaki Green": "#adb070", "Desert Sand": "#b39f82", "Cappuccino": "#b1907e",
    "Rosewood": "#b77a77", "Ivory White": "#bab6b1", "Platinum": "#b2aea7", "Roman Silver": "#a3a8b5",
    "Steel Grey": "#97a2ac", "Silver Blue": "#80a4b8", "Burgundy": "#a35e66", "Indigo Dye": "#537991",
    "Midnight Blue": "#5c6985", "Onyx Black": "#4d5254", "Battleship Grey": "#8c8c85", "Purple": "#ae6cae",
    "Grape": "#9d74c1", "Cobalt Blue": "#6088cf", "French Blue": "#5c9bc4", "Turquoise": "#5ec0b8",
    "Jade Green": "#55c49c", "Copper": "#d08656", "Chestnut": "#be6f54", "Chocolate": "#a46e58",
    "Marine Blue": "#4e689c", "Tactical Pine": "#44826b", "Gunship Green": "#558a65", "Dark Green": "#516341",
    "Seal Brown": "#664d45", "Rifle Green": "#64695c", "Ranger Green": "#5f7849", "Camo Green": "#75944d",
    "Feldgrau": "#899288", "Gunmetal": "#4c5d63", "Deep Cyan": "#31b5aa", "Mexican Pink": "#e36692",
    "Tomato": "#e6793e", "Fire Engine": "#f05f4f", "Celtic Blue": "#45b8ed", "Old Gold": "#b58d38",
    "Burnt Sienna": "#d66f3c", "Carmine": "#e0574a", "Mustard": "#d4980d", "French Violet": "#c260e6"
}
