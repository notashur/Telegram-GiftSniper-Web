# models.py
from dataclasses import dataclass
from typing import Dict, Optional
import json
import os
import shutil
from datetime import datetime

@dataclass
class User:
    username: str
    password_hash: str
    expire_date: str
    is_admin: bool = False
    is_owner: bool = False
    settings: Optional[Dict] = None
    active: bool = True


class UserManager:
    def __init__(self, storage_file='data/users.json'):
        self.storage_file = storage_file
        self.users = {}
        self.load_users()

    def load_users(self):
        if os.path.exists(self.storage_file):
            with open(self.storage_file, 'r') as f:
                data = json.load(f)
                self.users = {k: User(**v) for k, v in data.items()}

    def save_users(self):
        with open(self.storage_file, 'w') as f:
            json.dump({k: v.__dict__ for k, v in self.users.items()}, f, indent=2)

    def add_user(self, username, password_hash, expire_date,  is_admin=False):
        if username in self.users:
            return False
        self.users[username] = User(username, password_hash, expire_date, is_admin)
        self.save_users()
        return True

    def delete_user(self, username):
        if username not in self.users:
            return False
        
        try:
            # Delete user from memory and save
            del self.users[username]
            self.save_users()
            
            # Define all data paths to clean up
            data_paths = [
                f"data/logs/{username}.log",
                f"data/sent_gifts/{username}.json",
                f"data/user_configs/{username}.json",
                f"data/bot_states/{username}.json",
                # f"data/sessions/[{username}]*"  # Session files pattern
            ]
            
            # Delete each file that exists
            for path in data_paths:
                try:
                    if '*' in path:  # Handle glob patterns for session files
                        import glob
                        for session_file in glob.glob(path):
                            os.remove(session_file)
                    elif os.path.exists(path):
                        if os.path.isdir(path):
                            shutil.rmtree(path)
                        else:
                            os.remove(path)
                except Exception as e:
                    print(f"Warning: Failed to delete {path}: {str(e)}")
                    continue
            
            return True
        
        except Exception as e:
            print(f"Error deleting user {username}: {str(e)}")
            return False

    def update_user_expiry(self, username, new_expiry):
        user = self.users.get(username)
        if user:
            user.expire_date = new_expiry
            self.save_users()
            return True
        return False
    def authenticate(self, username, password_hash):
        user = self.users.get(username)
        if user and user.password_hash == password_hash and user.active:
            return user
        return None

    def is_expired(self, username) -> bool:
        user = self.users.get(username)
        if user and datetime.now().date() > datetime.strptime(user.expire_date, "%Y-%m-%d").date():
            return True
        return False
    def is_admin(self, username) -> bool:
        user = self.users.get(username)
        return user.is_admin if user else False

    def is_owner(self, username):
        user = self.users.get(username)
        return user.is_owner if user else False

    def promote_to_admin(self, username):
        user = self.users.get(username)
        if user and not user.is_owner:  # Don't allow modifying owner status
            user.is_admin = True
            self.save_users()
            return True
        return False

    def demote_admin(self, username):
        user = self.users.get(username)
        if user and not user.is_owner and user.is_admin:  # Can't demote owner
            user.is_admin = False
            self.save_users()
            return True
        return False

    def get_user(self, username):
        return self.users.get(username) or {}

    def toggle_user_active(self, username, active=None):
        user = self.users.get(username)
        if user:
            if active is None:
                user.active = not user.active
            else:
                user.active = active
            self.save_users()
            return True
        return False

    def update_user_password(self, username, new_password):
        user = self.users.get(username)
        if user:
            user.password_hash = new_password  # In production, hash this password!
            self.save_users()
            return True
        return False
    def get_user_bot_status(self, username):
        from bot_manager import is_bot_running  # Import here to avoid circular imports

        return {
            'is_running': is_bot_running(username),
            'can_disable': True
            # 'can_disable': not self.is_admin(username)
        }
    def can_edit_user(self, editor_username, target_username):
        editor = self.users.get(editor_username)
        target = self.users.get(target_username)
        
        if not editor or not target:
            return False
            
        # Owner can edit anyone
        if editor.is_owner:
            return True
            
        # Admins can edit non-admin users
        if editor.is_admin and not target.is_admin:
            return True
            
        # Users can edit themselves (if needed)
        if editor_username == target_username:
            return True
            
        return False