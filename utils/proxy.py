import os
import json
from datetime import datetime
from urllib.parse import urlparse
from threading import Lock
from config import BASE_DIR

class ProxyManager:
    def __init__(self):
        self.lock = Lock()
        self.proxy_file = os.path.join(BASE_DIR, 'data', "proxies.json")
        os.makedirs(os.path.dirname(self.proxy_file), exist_ok=True)

    def _load_proxies(self):
        """Load all proxies from file"""
        if not os.path.exists(self.proxy_file):
            return []

        with open(self.proxy_file, 'r') as f:
            return json.load(f)

    def _save_proxies(self, proxies):
        """Save proxies to file"""
        with open(self.proxy_file, 'w') as f:
            json.dump(proxies, f, indent=2)

    def acquire_proxy(self, username):
        """Acquire an available proxy for a user"""
        with self.lock:
            proxies = self._load_proxies()

            # First check if user already has an assigned proxy
            for proxy in proxies:
                if proxy.get('used_by') == username and proxy['in_use']:
                    # Update last used time
                    proxy['last_used'] = datetime.now().isoformat()
                    self._save_proxies(proxies)

                    # Return the existing proxy
                    return {
                        'host': proxy['host'],
                        'port': proxy['port'],
                        'username': proxy.get('username'),
                        'password': proxy.get('password')
                    }

            # If no existing proxy for this user, find first available proxy
            for proxy in proxies:
                if not proxy['in_use']:
                    proxy['in_use'] = True
                    proxy['used_by'] = username
                    proxy['last_used'] = datetime.now().isoformat()
                    self._save_proxies(proxies)

                    # Return the proxy dict without the management fields
                    return {
                        'host': proxy['host'],
                        'port': proxy['port'],
                        'username': proxy.get('username'),
                        'password': proxy.get('password')
                    }

            return None  # No available proxies

    def release_proxy(self, host, port):
        """Release a proxy back to the pool"""
        with self.lock:
            proxies = self._load_proxies()

            for proxy in proxies:
                if proxy['host'] == host and proxy['port'] == port:
                    proxy['in_use'] = False
                    proxy['used_by'] = None
                    proxy['last_used'] = datetime.now().isoformat()
                    self._save_proxies(proxies)
                    break

    def release_proxy_by_user(self, username):
        """Release all proxies used by a specific user"""
        with self.lock:
            proxies = self._load_proxies()
            released = False

            for proxy in proxies:
                if proxy['used_by'] == username:
                    proxy['in_use'] = False
                    proxy['used_by'] = None
                    proxy['last_used'] = datetime.now().isoformat()
                    released = True

            if released:
                self._save_proxies(proxies)

            return released

    def get_stats(self):
        """Get proxy pool statistics"""
        with self.lock:
            proxies = self._load_proxies()

            return {
                'total': len(proxies),
                'available': len([p for p in proxies if not p['in_use']]),
                'in_use': len([p for p in proxies if p['in_use']])
            }
    def add_proxy(self, host, port, username=None, password=None):
        proxy = {
            'host': host,
            'port': port,
            'username': username,
            'password': password,
            'in_use': False,
            'used_by': None,
            'last_used': None
        }
    
        with self.lock:
            proxies = []
            if os.path.exists(self.proxy_file):
                with open(self.proxy_file, 'r') as f:
                    proxies = json.load(f)
            
            proxies.append(proxy)
            
            with open(self.proxy_file, 'w') as f:
                json.dump(proxies, f, indent=2)
        return True
    def remove_proxy(self, host, port):
        with self.lock:
            proxies = []
            if os.path.exists(self.proxy_file):
                with open(self.proxy_file, 'r') as f:
                    proxies = json.load(f)

            proxies = [p for p in proxies if not (p['host'] == host and p['port'] == port)]

            with open(self.proxy_file, 'w') as f:
                json.dump(proxies, f, indent=2)

        return True

    def get_proxy_list(self):
        proxies = []
        if os.path.exists(self.proxy_file):
            with open(self.proxy_file, 'r') as f:
                proxies = json.load(f)
        return proxies