# config_manager.py
import json
import os
from threading import Lock
from pathlib import Path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SUBSCRIPTIONS_FILE = os.path.join(BASE_DIR, 'data', "subscriptions.json")
HISTORY_RETENTION_DAYS = 7

SETTINGS_LOCK = Lock()
os.makedirs(os.path.join(BASE_DIR, 'data', "sessions"), exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, 'data', "logs"), exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, 'data', "sent_gifts"), exist_ok=True)

class UserConfigManager:
    def __init__(self, config_dir=os.path.join(BASE_DIR, 'data', 'user_configs')):
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(exist_ok=True)
        self.locks = {}  # Per-user config locks
        self.default_config = {
            "ADMIN_RECIPIENT_USER": "",
            "DEFAULT_GIFTS_TO_BUY_MAX_PRICE": 200,
            "GIFTS_NOT_TO_BUY": [],
            "BACKDROPS_NOT_TO_BUY": [],
            "SLEEP_BETWEEN_CYCLES": 3,
            "APP_API_ID": "",
            "APP_API_HASH": "",
            "APP_PHONE_NUMBER": "",
            "BUYER_API_ID": "",
            "BUYER_API_HASH": "",
            "BUYER_PHONE_NUMBER": "",
            "GIFT_LIMITS": {}
        }

    def get_user_lock(self, username):
        if username not in self.locks:
            self.locks[username] = Lock()
        return self.locks[username]

    def get_config_path(self, username):
        return self.config_dir / f"{username}.json"

    def load_config(self, username):
        config_path = self.get_config_path(username)
        if not config_path.exists():
            return self.default_config.copy()

        with self.get_user_lock(username):
            with open(config_path, 'r') as f:
                user_config = json.load(f)
                # Remove '@' from ADMIN_RECIPIENT_USER if it exists
                if 'ADMIN_RECIPIENT_USER' in user_config:
                    user_config['ADMIN_RECIPIENT_USER'] = user_config['ADMIN_RECIPIENT_USER'].lstrip('@')
                # Merge with defaults to ensure all keys exist
                return {**self.default_config, **user_config}

    def save_config(self, username, new_data):
        config_path = self.get_config_path(username)
        with self.get_user_lock(username):
            # Load the existing config or default if not exists
            if config_path.exists():
                with open(config_path, 'r') as f:
                    existing_config = json.load(f)
            else:
                existing_config = self.default_config.copy()

            # Merge the new data into the existing config
            updated_config = {**existing_config, **new_data}

            with open(config_path, 'w') as f:
                json.dump(updated_config, f, indent=2)

    def delete_config(self, username):
        config_path = self.get_config_path(username)
        if config_path.exists():
            with self.get_user_lock(username):
                config_path.unlink()


def load_subscriptions():
    """Load subscriptions from file with error handling"""
    if not os.path.exists(SUBSCRIPTIONS_FILE):
        return []

    try:
        with open(SUBSCRIPTIONS_FILE, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError:
        return []
    except IOError as e:
        return []


# def load_settings():
#     return UserConfigManager().load_config(g.username)


def initialize_gift_limits(username):
    """Initialize GIFT_LIMITS for any new gifts not already in settings"""
    from data.gifts import GIFT_MAPPINGS  # Import your gift mappings
    a = UserConfigManager()
    settings = a.load_config(username)
    current_limits = settings.get('GIFT_LIMITS', {})
    default_limit = settings.get('DEFAULT_GIFTS_TO_BUY_MAX_PRICE', 200)

    # Find any gifts in GIFT_MAPPINGS that aren't in current_limits
    new_limits = {
        gift_name: current_limits.get(gift_name, default_limit)
        for gift_name in GIFT_MAPPINGS.values()
        if gift_name not in current_limits
    }

    if new_limits:
        # Only update if we found new gifts
        updated_limits = {**current_limits, **new_limits}
        a.save_config(username, {'GIFT_LIMITS': updated_limits})
        return updated_limits

    return current_limits


def load_settings(username):
    """Get settings for the current request context"""

    settings = UserConfigManager().load_config(username)

    # Initialize gift limits for any new gifts
    settings['GIFT_LIMITS'] = initialize_gift_limits(username)

    return settings


def save_settings(username, new_data):
    return UserConfigManager().save_config(username, new_data)

def get_log_file(username):
    return os.path.join(BASE_DIR, 'data', 'logs', f"{username}.log")

def get_history_file(username):
    return os.path.join(BASE_DIR, 'data', 'sent_gifts', f"{username}.json")