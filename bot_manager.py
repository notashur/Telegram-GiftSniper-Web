# bot_manager.py
from queue import Queue
import os
# import glob
import json
import asyncio
from random import randint
import sqlite3
from typing import Dict, List, Set, Optional, Any
from datetime import datetime, timedelta
from urllib.parse import urlparse
import time
from pyrogram import Client as _PyroClient
from pyrogram.enums import GiftForResaleOrder, GiftAttributeType
from pyrogram.errors import SessionPasswordNeeded, PhoneCodeInvalid, PhoneCodeExpired
from pyrogram.errors import RPCError, BadRequest, Unauthorized
from data.gifts import GIFT_MAPPINGS
from threading import Lock, Thread
import config
from utils.logger import get_logger
from utils.notifications import send_notification_to_user
from utils.proxy import ProxyManager

from types import SimpleNamespace

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def Client(name, api_id, api_hash, *args, **kwargs):
    defaults = {
        "device_model": "GiftSniper",
        "system_version": "Android 13",
        "app_version": "Telegram 11.12.0",  # This is the default if not provided
        "lang_code": "en",
        "system_lang_code": "en-US",
    }
    # Apply defaults only if they're not explicitly provided
    final_kwargs = defaults.copy()
    final_kwargs.update(kwargs)  # Explicit args override defaults
    return _PyroClient(
        name,
        api_id,
        api_hash,
        *args,
        **final_kwargs
    )

def get_config_settings(username):
    """Return settings for the current request/user as a SimpleNamespace."""
    settings_dict = config.load_settings(username)
    return SimpleNamespace(**settings_dict)

proxy_manager = ProxyManager()

class GiftBot:
    def __init__(self, username):
        self.proxy = None
        self.buyer_app: Optional[Client] = None
        self.tried_gift_identifiers: Set[str] = set()
        self.current_balance_stars: Optional[int] = None
        self.current_balance_ton: Optional[int] = None
        self.sent_gifts: Set[str] = set()
        self.app: Optional[Client] = None
        self.app_semaphore = asyncio.Semaphore(10) # Value is too high but, what the hell right ?
        self._username = username
        self.cached_peer = None
        self.bot_state = bot_state_manager.get_state(username)
        self.logger = get_logger(username)
        self._restart_lock = asyncio.Lock()  # Better than Event for this case
        self._should_wait = False  # Simple flag to indicate waiting period
        # Cache all config settings at initialization
        self._cache_config_settings()
        self._load_history()

    def _cache_config_settings(self) -> None:
        """Cache all config settings at initialization"""
        _config_settings = get_config_settings(self._username)  # load once :D

        self.cached_config = {
            'HISTORY_FILE': config.get_history_file(self._username),
            'HISTORY_RETENTION_DAYS': config.HISTORY_RETENTION_DAYS,
            'GIFT_LIMITS': _config_settings.GIFT_LIMITS or {},
            'DEFAULT_GIFTS_TO_BUY_MAX_PRICE': _config_settings.DEFAULT_GIFTS_TO_BUY_MAX_PRICE,
            'GIFTS_NOT_TO_BUY': _config_settings.GIFTS_NOT_TO_BUY or [],
            'BACKDROPS_NOT_TO_BUY': _config_settings.BACKDROPS_NOT_TO_BUY or [],
            'ADMIN_RECIPIENT_USER': int(_config_settings.ADMIN_RECIPIENT_USER) if str(_config_settings.ADMIN_RECIPIENT_USER).isdigit() else _config_settings.ADMIN_RECIPIENT_USER,
            'APP_PHONE_NUMBER': _config_settings.APP_PHONE_NUMBER,
            'APP_API_ID': _config_settings.APP_API_ID,
            'APP_API_HASH': _config_settings.APP_API_HASH,
            'BUYER_PHONE_NUMBER': _config_settings.BUYER_PHONE_NUMBER,
            'BUYER_API_ID': _config_settings.BUYER_API_ID,
            'BUYER_API_HASH': _config_settings.BUYER_API_HASH,
            'SLEEP_BETWEEN_CYCLES': _config_settings.SLEEP_BETWEEN_CYCLES
        }

    def _load_history(self) -> None:
        """Load previously sent gift links with timestamps"""
        try:
            if os.path.exists(self.cached_config['HISTORY_FILE']):
                with open(self.cached_config['HISTORY_FILE'], 'r') as f:
                    history = json.load(f)
                    cutoff = datetime.now() - timedelta(days=self.cached_config['HISTORY_RETENTION_DAYS'])
                    self.sent_gifts = {
                        k for k, v in history.items()
                        if datetime.fromisoformat(v) > cutoff
                    }
        except Exception as e:
            self.logger.error(f"Error loading history: {e}", exc_info=True)

    def _save_history(self) -> None:
        """Save current state of sent gifts"""
        try:
            history = {gift_id: datetime.now().isoformat() for gift_id in self.sent_gifts}
            with open(self.cached_config['HISTORY_FILE'], 'w') as f:
                json.dump(history, f, indent=2)
        except Exception as e:
            self.logger.error(f"Error saving history: {e}", exc_info=True)

    @staticmethod
    def _extract_gift_identifier(link: str) -> Optional[str]:
        """Extract the name-id portion from gift link"""
        parsed = urlparse(link)
        if parsed.path.startswith('/nft/'):
            return parsed.path.split('/')[-1]
        return None

    @staticmethod
    def _escape_markdown(text: str) -> str:
        """Escape special Markdown characters."""
        if not text:
            return ""
        escape_chars = r'\*_`[]()'
        return ''.join(f'\\{char}' if char in escape_chars else char for char in text)

    def _get_gift_limit(self, gift_title: str) -> int:
        """Get the star limit for a specific gift, using cached config"""
        # Check if we have a specific limit for this gift
        return self.cached_config['GIFT_LIMITS'].get(
            gift_title,
            self.cached_config['DEFAULT_GIFTS_TO_BUY_MAX_PRICE']
        )

    async def _find_cheap_gifts(self, gift_id: int, gift_title: str, client: Client, semaphore: asyncio.Semaphore) -> List:
        """
        Return resale offers for this gift that are
        - under the per‑gift star limit
        - NOT on any of the avoid lists (title or backdrop)
        """
        # 1️⃣  Skip the entire gift type if its *title* matches an avoid keyword
        async with semaphore:
            if (
                self.cached_config['GIFTS_NOT_TO_BUY']
                and any(bad.lower() in gift_title.lower()
                        for bad in self.cached_config['GIFTS_NOT_TO_BUY'])
            ):
                # Nothing to look for – don’t even call search_gifts_for_resale
                return []
            gift_limit = self._get_gift_limit(gift_title)
            
            if gift_limit > self.current_balance_stars:
                return []
            found_gifts = []
            try:
                async for gift in client.search_gifts_for_resale(
                    gift_id=gift_id,
                    order=GiftForResaleOrder.PRICE,
                    limit=randint(1, 5)
                ):
                    # 2️⃣  Price check
                    if not gift.last_resale_star_count or gift.last_resale_star_count > gift_limit:
                        continue
                    found_gifts.append(gift)
            except asyncio.TimeoutError as e:
                self.logger.error("Timeout while searching gifts for %s", gift_id)
                return found_gifts
            except TimeoutError as e:
                self.logger.error("Timeout while searching gifts for %s", gift_id)
                return found_gifts
            except RuntimeError as e:
                self.logger.error("Runtime while searching gifts for %s", gift_id)
                return found_gifts
            except Exception as e:
                self.logger.error(f"Error searching gifts for ID {gift_id}: {e}", exc_info=True)
            return found_gifts

    async def process_gift(self, gift_id: int, gift_title: str, client: Client, semaphore: asyncio.Semaphore) -> None:
        """Process a single gift type with its specific limit"""
        try:
            cheap_gifts = await self._find_cheap_gifts(gift_id, gift_title, client, semaphore)
            if not cheap_gifts:
                return

            buy_tasks = [
                self._try_to_buy_gift(gift)
                for gift in cheap_gifts
                if gift.last_resale_star_count <= self._get_gift_limit(gift.title)
            ]
            results = await asyncio.gather(*buy_tasks, return_exceptions=True)
            if any(results):
                self._save_history()
        except Exception as e:
            self.logger.error(f"Error processing gift {gift_id}: {e}", exc_info=True)
    async def _try_to_buy_gift(self, gift) -> bool:
        """
        Attempt to purchase and send a gift using the buyer client.
        
        Args:
            gift: The gift object containing gift details
            
        Returns:
            bool: True if purchase was successful, False otherwise
        """
        # Early exit checks
        if not self._should_process_gift(gift):
            return False

        gift_identifier = self._extract_gift_identifier(gift.link)
        if not gift_identifier or gift_identifier in self.sent_gifts:
            return False

        self.sent_gifts.add(gift_identifier)

        # Balance verification
        r, currency = await self._verify_balance_for_purchase(gift)
        if not r:
            return False

        # Purchase attempt
        return await self._attempt_gift_purchase(gift, currency)

    def _should_process_gift(self, gift) -> bool:
        """Check if gift meets all criteria for purchase"""
        if not all([gift.link, gift.last_resale_star_count is not None]):
            return False

        if gift.last_resale_star_count > self._get_gift_limit(gift.title):
            return False

        if self._contains_banned_keywords(gift):
            return False

        return True

    def _contains_banned_keywords(self, gift) -> bool:
        """Check for banned keywords in gift title or attributes"""
        # Check gift title
        if (self.cached_config['GIFTS_NOT_TO_BUY'] and gift.title and 
            any(bad.lower() in gift.title.lower() 
                for bad in self.cached_config['GIFTS_NOT_TO_BUY'])):
            return True

        # Check backdrops
        if self.cached_config['BACKDROPS_NOT_TO_BUY']:
            for attr in getattr(gift, 'attributes', []):
                if (attr and attr.type == GiftAttributeType.BACKDROP and
                    any(bad.lower() in getattr(attr, 'name', '').lower()
                        for bad in self.cached_config['BACKDROPS_NOT_TO_BUY'])):
                    return True

        return False

    async def _verify_balance_for_purchase(self, gift) -> tuple[bool, str]:
        """Verify sufficient balance for purchase, prioritize TON over stars"""
        try:
            # Check TON balance first
            if self.current_balance_ton is not None and self.current_balance_ton >= (gift.last_resale_ton_count / 1e9):
                return True, "ton"

            # If TON insufficient, check stars
            if self.current_balance_stars is not None and self.current_balance_stars >= gift.last_resale_star_count:
                return True, "stars"

            # Neither balance is sufficient
            message = (f"⛔️ Skipping gift {gift.link} – "
                    f"Cost: {gift.last_resale_star_count}⭐️ / "
                    f"{gift.last_resale_ton_count / 1e9} TON, "
                    f"Balance: {self.current_balance_stars}⭐️ / "
                    f"{self.current_balance_ton} TON")
            await self._handle_purchase_failure(message, warning=True)
            return False, ""

        except Exception as e:
            self.logger.error(f"Failed to verify balance: {e}", exc_info=True)
            return False, ""

    async def _attempt_gift_purchase(self, gift, currency) -> bool:
        """Execute the gift purchase flow"""
        try:
            await self.buyer_app.send_resold_gift(
                gift.link, 
                self.cached_config['ADMIN_RECIPIENT_USER'],
                use_ton = bool(currency == 'ton'), # checks if the currency is either ton or not.
                cached_peer=self.cached_peer
            )
            
            await self._handle_purchase_success(gift, currency)
            return True

        except (BadRequest, RPCError) as e:
            await self._handle_api_error(e, gift)
            return False
            
        except Exception as e:
            await self._handle_unexpected_error(e, gift)
            return False

    async def _handle_purchase_success(self, gift, currency: str) -> None:
        """Handle successful purchase operations with proper currency deduction"""
        
        if currency == "ton":
            cost_ton = gift.last_resale_ton_count / 1e9
            message = f"✅ Successfully bought and sent gift {gift.link} to Admin for {cost_ton} TON"
            self.current_balance_ton -= cost_ton
            self.bot_state.current_balance_ton = self.current_balance_ton
        elif currency == "stars":
            cost_stars = gift.last_resale_star_count
            message = f"✅ Successfully bought and sent gift {gift.link} to Admin for {cost_stars}⭐️"
            self.current_balance_stars -= cost_stars
            self.bot_state.current_balance_stars = self.current_balance_stars
        else:
            self.logger.warning(f"Unknown currency '{currency}' for gift {gift.link}")
            return

        # Parallelize notifications and logging
        send_notification_to_user(
            "🎁 Gift! Check Your Inbox!",
            message,
            self._username
        )
        await self._notify_admin(message)
        self.bot_state.add_log(message)
        self.bot_state.add_gift(
            self.cached_config['ADMIN_RECIPIENT_USER'],
            gift.link,
            gift.last_resale_star_count if currency == "stars" else 0
        )
        await self.channel_sender._send_gift_to_channel(gift)
        self.logger.info(message)

    async def _handle_api_error(self, error: Exception, gift) -> None:
        """Handle Telegram API specific errors"""
        error_messages = {
            'STARGIFT_RESELL_NOT_ALLOWED': 
                f"❌ {gift.link} was already bought by someone else",
            'STARS_FORM_AMOUNT_MISMATCH': 
                f"❌ Price changed for {gift.link} - try again",
            'BALANCE_TOO_LOW': 
                f"❌ Not enough stars to buy {gift.link}",
            'FLOOD_WAIT': 
                f"❌ Trying too fast - waiting a bit before next try"
        }
        
        message = next(
            (msg for err, msg in error_messages.items() if err in str(error)),
            f"❌ Couldn't buy {gift.link} (try again)"
        )
        
        log_method = self.logger.warning if isinstance(error, BadRequest) else self.logger.error
        log_method(f"API error while buying gift {gift.link}: {error}")
        
        await self._handle_purchase_failure(message)

    async def _handle_unexpected_error(self, error: Exception, gift) -> None:
        """Handle unexpected errors during purchase"""
        message = f"❌ Unexpected error trying to buy gift {gift.link}: {error}"
        self.logger.error(message, exc_info=True)
        await self._handle_purchase_failure(message)

    async def _handle_purchase_failure(self, message: str, warning: bool = False) -> None:
        """Handle failed purchase operations"""
        if warning:
            self.logger.warning(message)
        else:
            self.logger.error(message)
            
        await asyncio.gather(
            self.bot_state.add_log(message),
            self._notify_admin(message)
        )

    async def _notify_admin(self, msg):
        # Notify admin
        try:
            await self.buyer_app.send_message(self.cached_config['ADMIN_RECIPIENT_USER'], msg)
        except Exception as e:
            self.logger.error(f"Failed to notify admin: {e}", exc_info=True)

    async def health_check(self) -> None:
        """Periodically verify client health and handle restarts"""
        while self.bot_state.running:
            try:
                await asyncio.sleep(randint(60, 120))  # Initial delay to space out checks

                if not self.bot_state.running:
                    break
                
                # Quick health check
                if self.app.is_connected:
                    await self.app.get_me()
                if self.buyer_app.is_connected:
                    await self.buyer_app.get_me()
                    # # Refresh cached peer periodically to ensure it's valid
                    # await self._cache_peer_id()

            except TimeoutError:
                self.logger.warning("Timeout in health-check, backing off...")
                await asyncio.sleep(10)   # give API a breather
                continue
            except Exception as e:
                self.logger.warning(
                    "Client session check failed. Attempting restart...",
                    exc_info=True
                )
                await self._handle_client_restart(e)

    async def _safe_stop(self, client):
        try:
            if client.is_connected:          # only if the handshake ever finished
                await client.stop()
        except Unauthorized:
            # auth‑key is already invalid – nothing to clean up
            pass
        except RPCError as e:
            self.logger.debug("Ignoring stop() error: %s", e)

    async def _handle_client_restart(self, reason: str = ""):
        async with self._restart_lock:  # Prevent multiple concurrent restarts
            try:
                self._should_wait = True  # Signal to main loop
                self.logger.warning(f"Beginning client restart: {reason}")
                
                await self._safe_stop(self.app)
                await self._safe_stop(self.buyer_app)
                
                # Quick cooldown before reinitialization
                await asyncio.sleep(10)

                if not await self._initialize_clients():
                    return False

                # Post-restart cooldown
                cooldown = 10
                log = f"Restart successful, cooling down for {cooldown} seconds"
                self.logger.info(log)
                self.bot_state.add_log(log)
                await asyncio.sleep(cooldown)
                self.bot_state.add_log('✅ Client restart completed')
                self._should_wait = False  # Always clear the flag
                return True
            
            except Exception as e:
                self.logger.critical(f"Restart failed: {e}", exc_info=True)
                await self._emergency_shutdown(
                    reason="Client restart failed",
                    error_details=str(e)
                )
                return False

    async def _emergency_shutdown(self, reason: str, error_details: str = "") -> None:
        """Handle graceful shutdown with notifications"""
        msg = f"❌ BOT STOPPED!\n- Reason: {reason}"
        # if error_details:
        #     msg += f"\n- Error: {error_details}"

        self.bot_state.running = False
        self._should_wait = False
        # Parallelize notifications
        send_notification_to_user(
                "🛑 Bot Stopped",
                msg,
                self._username
            )
        await self._notify_admin(msg)
        self.bot_state.add_log(msg)

    async def _initialize_clients(self) -> bool:
        """Initialize and start client sessions"""
        try:
            proxy_config = self._get_proxy_config()
            
            self.app = Client(
                name=os.path.join(
                    BASE_DIR, 
                    "data/sessions", 
                    f"[{self._username}]app_{self.cached_config['APP_PHONE_NUMBER']}"
                ),
                api_id=self.cached_config['APP_API_ID'],
                api_hash=self.cached_config['APP_API_HASH'],
                phone_number=self.cached_config['APP_PHONE_NUMBER'],
                proxy=proxy_config,
                ipv6=bool(proxy_config)
            )
            
            self.buyer_app = Client(
                name=os.path.join(
                    BASE_DIR,
                    "data/sessions",
                    f"[{self._username}]buyer_{self.cached_config['BUYER_PHONE_NUMBER']}"
                ),
                api_id=self.cached_config['BUYER_API_ID'],
                api_hash=self.cached_config['BUYER_API_HASH'],
                phone_number=self.cached_config['BUYER_PHONE_NUMBER'],
                proxy=proxy_config,
                ipv6=bool(proxy_config)
            )
            
            await asyncio.gather(
                self.app.start(),
                self.buyer_app.start()
            )
            # Cache the peer ID during initialization
            await self._cache_peer_id()
            
            return True
        except Exception as e:
            await self._emergency_shutdown(
                reason="Client initialization failed",
                error_details=str(e)
            )
            return False
    async def _cache_peer_id(self) -> None:
        """Cache the peer ID for the admin recipient"""
        try:
            self.cached_peer = await self.buyer_app.resolve_peer(
                self.cached_config['ADMIN_RECIPIENT_USER']
            )
            self.logger.info(f"Cached peer ID for admin: {type(self.cached_peer).__name__}")
        except Exception as e:
            self.logger.error(f"Failed to cache peer ID: {e}", exc_info=True)
            self.cached_peer = None  # Ensure it's None if resolution fails

    def _get_proxy_config(self) -> Optional[Dict]:
        """Prepare proxy configuration if available"""
        if not self.proxy:
            return None
            
        proxy_dict = {
            "scheme": "socks5",
            "hostname": self.proxy['host'],
            "port": self.proxy['port'],
        }
        
        if self.proxy.get('username'):
            proxy_dict.update({
                "username": self.proxy['username'],
                "password": self.proxy.get('password', '')
            })
        
        return proxy_dict

    async def run(self) -> None:
        """Main bot execution loop with proper resource management"""
        health_task = None
        
        try:
            self.proxy = proxy_manager.acquire_proxy(self._username)
            
            if not await self._initialize_clients():
                return
                
            # Initial setup
            self.current_balance_stars = await self.buyer_app.get_stars_balance()
            self.bot_state.current_balance_stars = self.current_balance_stars
            
            self.current_balance_ton = await self.buyer_app.get_ton_balance() / 1e9
            self.bot_state.current_balance_ton = self.current_balance_ton
            
            startup_messages = [
                f"Main app started as {self.app.me.first_name} (ID: {self.app.me.id})",
                f"Buyer app started as {self.buyer_app.me.first_name} (ID: {self.buyer_app.me.id})",
                f"Current Buyer balance: {self.current_balance_stars}⭐️",
                f"Current Buyer balance: {self.current_balance_ton}💎"
            ]
            
            for msg in startup_messages:
                self.logger.info(msg)
                
            self.bot_state.add_log("🤖 Gift Sniper Bot started\n" + "\n".join(startup_messages))
            
            # Start monitoring
            health_task = asyncio.create_task(self.health_check())
            
            # Main processing loop
            cycle_count = 0
            while self.bot_state.running:
                try:
                    # Minimal wait check - non-blocking
                    if self._should_wait:
                        self.logger.info("Brief pause for restart completion")
                        await asyncio.sleep(0.5)  # Tiny sleep to avoid tight loop
                        continue  # Skip this iteration

                    await self._process_gift_cycle(cycle_count)
                    cycle_count += 1
                    self.bot_state.bot_cycle = cycle_count
                    
                except Exception as e:
                    self.logger.error(
                        f"Error in main loop (cycle {cycle_count})",
                        exc_info=True
                    )
                    await asyncio.sleep(30)
                    
        finally:
            await self._shutdown(health_task)

    async def _process_gift_cycle(self, cycle_count: int) -> None:
        """Process one cycle of gift checking with proper concurrency control"""
        
        async def process_with_limits(gift_id, gift_title, client, semaphore):
            return await self.process_gift(int(gift_id), gift_title, client, semaphore)

        gift_items = list(GIFT_MAPPINGS.items())
        
        tasks = []
        # Single client, use all gifts with semaphore
        for gift_id, gift_title in gift_items:
            tasks.append(process_with_limits(gift_id, gift_title, self.app, self.app_semaphore))

        # Run all tasks concurrently but limited by semaphores
        await asyncio.gather(*tasks)

        self.logger.info(
            f"[{cycle_count}] Completed cycle. "
            f"Waiting {self.cached_config['SLEEP_BETWEEN_CYCLES']} seconds..."
        )
        await asyncio.sleep(self.cached_config['SLEEP_BETWEEN_CYCLES'])

    async def _shutdown(self, health_task: Optional[asyncio.Task]) -> None:
        """Handle graceful shutdown"""
        self.bot_state.running = False
        
        if health_task:
            health_task.cancel()
            try:
                await health_task
            except (asyncio.CancelledError, Exception):
                pass
        

class BotState:
    def __init__(self, state_file):
        self._lock = Lock()
        self._state_file = state_file
        self._running = False
        self._current_balance_stars = None
        self._current_balance_ton = None
        self.bot_cycle = None
        self._last_error = None
        self._recent_logs = []
        self._purchased_gifts = []
        self._start_time = None
        self._original_start_time = None
        self.last_error = None
        self.bot_instance = None
        self.loop = None
        self.thread = None
        self._load_state()  # Load initial state

    def _load_state(self):
        if os.path.exists(self._state_file):
            try:
                with open(self._state_file, 'r') as f:
                    data = json.load(f)
                self._running = data.get('running', False)
                self._current_balance_stars = data.get('current_balance_stars')
                self._current_balance_ton = data.get('current_balance_ton')
                self.bot_cycle = data.get('bot_cycle')
                self._recent_logs = data.get('recent_logs', [])
                self._purchased_gifts = data.get('purchased_gifts', [])
                self._original_start_time = data.get('original_start_time')

                # Calculate elapsed time if bot was running
                if self._running and self._original_start_time:
                    elapsed = time.time() - self._original_start_time
                    self._start_time = time.time() - elapsed
            except Exception as e:
                print(f"Failed to load bot state: {e}")

    def save_state(self):
        data = {
            'running': self._running,
            'current_balance_stars': self._current_balance_stars,
            'current_balance_ton': self._current_balance_ton,
            'bot_cycle': self.bot_cycle,
            'recent_logs': self._recent_logs,
            'purchased_gifts': self._purchased_gifts,
            'original_start_time': self._original_start_time
        }
        with open(self._state_file, 'w') as f:
            json.dump(data, f, indent=2)

    @property
    def running(self):
        with self._lock:
            return self._running

    @property
    def start_time(self):
        with self._lock:
            return self._start_time

    @running.setter
    def running(self, value):
        with self._lock:
            if value != self._running:
                self._running = value
                now = time.time()

                if value:                        # bot just started
                    if not self._original_start_time:
                        self._original_start_time = now
                    self._start_time = now       # <-- add this line
                else:                            # bot just stopped
                    self._start_time = None
                    self._original_start_time = None

                self.save_state()

    def add_log(self, message):
        with self._lock:
            # Add timestamp to the log message
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            log_entry = f"[{timestamp}] {message}"

            self._recent_logs.append(log_entry)
            self.save_state()

    def add_gift(self, user_id, gift_link, price):
        """
        Record a gift purchase.

        Parameters
        ----------
        user_id   : int | str     –  who bought it
        gift_link   : str     –  your internal gift/product
        price     : float | int   –  price paid (same units as the rest of your app)
        """
        with self._lock:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            entry = {
                "timestamp": timestamp,
                "user_id": user_id,
                "gift_link": gift_link,
                "price": price
            }
            self._purchased_gifts.append(entry)
            self.save_state()

    @property
    def recent_logs(self):
        with self._lock:
            return self._recent_logs.copy()

    @property
    def current_balance_stars(self):
        with self._lock:
            return self._current_balance_stars

    @current_balance_stars.setter
    def current_balance_stars(self, value):
        with self._lock:
            self._current_balance_stars = value
            self.save_state()  # Optional: auto-save when updated
    @property
    def current_balance_ton(self):
        with self._lock:
            return self._current_balance_ton

    @current_balance_ton.setter
    def current_balance_ton(self, value):
        with self._lock:
            self._current_balance_ton = value
            self.save_state()  # Optional: auto-save when updated

class BotStateManager:
    
    def __init__(self):
        self._states = {}  # Dictionary to hold states by username
        self._lock = Lock()

    def get_state(self, username):
        """Get or create a BotState instance for the given username"""
        with self._lock:
            if username not in self._states:
                state_file = os.path.join(BASE_DIR, 'data/bot_states', f'{username}.json')
                os.makedirs(os.path.dirname(state_file), exist_ok=True)
                self._states[username] = BotState(state_file)
            return self._states[username]

    def cleanup_state(self, username):
        """Clean up state for a username when no longer needed"""
        with self._lock:
            if username in self._states:
                del self._states[username]


# Global state manager
bot_state_manager = BotStateManager()
# Modified GiftBot class to work with web interface


class WebEnabledGiftBot(GiftBot):
    def __init__(self, username):
        super().__init__(username)
        self.username = username
        self.bot_state = bot_state_manager.get_state(username)

    async def run(self):
        # Only update state if not already running
        if not self.bot_state.running:
            self.bot_state.running = True
            self.bot_state.start_time = time.time()

        try:
            await super().run()
        except Exception as e:
            self.bot_state.last_error = str(e)
            get_logger(self.username).exception("Bot crashed")
        finally:
            # Only update state if we're actually stopping
            if hasattr(self, 'proxy') and self.proxy:
                proxy_manager.release_proxy(self.proxy['host'], self.proxy['port'])
            if self.bot_state.running:
                self.bot_state.running = False
                self.bot_state.start_time = None

            try:
                if hasattr(self, 'app') and self.app and self.app.is_connected:
                    await self.app.stop()
                if hasattr(self, 'buyer_app') and self.buyer_app and self.buyer_app.is_connected:
                    await self.buyer_app.stop()
            except Exception as e:
                get_logger(self.username).warning(f"Error stopping clients: {e}")
            finally:
                bot_state_manager.cleanup_state(self.username)

# Start/stop bot functions


def run_bot_in_thread(username):
    asyncio.set_event_loop(bot_state_manager.get_state(username).loop)
    bot = WebEnabledGiftBot(username)
    bot_state_manager.get_state(username).bot_instance = bot
    bot_state_manager.get_state(username).loop.run_until_complete(bot.run())


def validate_environment(username):
    """Validate all critical components before starting the bot"""
    try:
        _config_settings = get_config_settings(username)
        logger = get_logger(username)

        # 1. Check required settings
        required_settings = [
            'APP_API_ID', 'APP_API_HASH', 'APP_PHONE_NUMBER',
            'BUYER_API_ID', 'BUYER_API_HASH', 'BUYER_PHONE_NUMBER',
            'ADMIN_RECIPIENT_USER'
        ]

        for setting in required_settings:
            if not getattr(_config_settings, setting, None):
                logger.error(f"Missing required setting: {setting}")
                return {'valid': False, 'message': f'Missing required setting: {setting.replace("_", " ").title()}'}

        # 2. Check session files exist
        app_session_file = os.path.join(BASE_DIR, "data/sessions",
                                        f"[{username}]app_{_config_settings.APP_PHONE_NUMBER}.session")
        buyer_session_file = os.path.join(BASE_DIR, "data/sessions",
                                          f"[{username}]buyer_{_config_settings.BUYER_PHONE_NUMBER}.session")

        if not os.path.exists(app_session_file):
            logger.error(f"App session file not found at {app_session_file}")
            return {'valid': False, 'message': 'App session missing - please log in again'}

        if not os.path.exists(buyer_session_file):
            logger.error(f"Buyer session file not found at {buyer_session_file}")
            return {'valid': False, 'message': 'Buyer session missing - please log in again'}

        # 3. Validate sessions and peer contact status
        async def validate_peer_contact(client, peer_id):
            """
            Resolve the peer (user / chat / channel) **and** make sure the bot
            can actually talk to it by sending a lightweight test message.
            Returns  (bool ok, str human_message).
            """
            try:
                # ---------- 1. Resolve -------------------------------------------------
                try:
                    # First, try to get it as a user
                    peer = await client.get_users(int(peer_id) if str(peer_id).isdigit() else peer_id)
                except Exception:
                    # If that fails, try to get it as a chat / channel
                    try:
                        peer = await client.get_chat(int(peer_id) if str(peer_id).isdigit() else peer_id)
                    except Exception as e:
                        logger.error(f"Cannot resolve peer: {e}")
                        return False, "Cannot resolve peer. Is the @username / ID correct?"

                resolved_id = peer.id if hasattr(peer, "id") else peer_id  # fall back to what we got

                # ---------- 2. (optional) quick chat lookup ---------------------------
                # If you still want the old “get_chat first, message if needed” logic:
                try:
                    await client.get_chat(resolved_id)          # will succeed if a dialog already exists
                    # fall through – we keep going so we still try to send the message
                except Exception:
                    pass  # no chat yet ➜ we’ll try to create one with send_message()

                # ---------- 3. Try to send a test message -----------------------------
                try:
                    await client.send_message(
                        resolved_id,
                        "🤖 Gift Sniper connection check (please ignore)",
                        disable_notification=True,
                    )
                    return True, "Peer contact verified – message delivered."
                except Exception as e:
                    # Typical errors: BOT_PRIVACY_FORBIDDEN, PEER_ID_INVALID, etc.
                    logger.error(f"Could not message peer: {e}")
                    return (
                        False, 'Please message this user first from your buyer account'
                    )

            except Exception as e:
                logger.error(f"Unexpected peer‑validation error: {e}")
                return False, f"Validation failed: {e}"

        async def validate_all():
            app_client = None
            buyer_client = None
            max_retries = 3
            retry_delay = 2

            for attempt in range(max_retries):
                try:
                    # Initialize and connect clients
                    app_client = Client(
                        os.path.join(BASE_DIR, "data/sessions",
                                     f"[{username}]app_{_config_settings.APP_PHONE_NUMBER}"),
                        _config_settings.APP_API_ID,
                        _config_settings.APP_API_HASH,
                        phone_number=_config_settings.APP_PHONE_NUMBER
                    )
                    buyer_client = Client(
                        os.path.join(BASE_DIR, "data/sessions",
                                     f"[{username}]buyer_{_config_settings.BUYER_PHONE_NUMBER}"),
                        _config_settings.BUYER_API_ID,
                        _config_settings.BUYER_API_HASH,
                        phone_number=_config_settings.BUYER_PHONE_NUMBER
                    )

                    await app_client.connect()
                    await buyer_client.connect()

                    # Verify basic connectivity
                    if not (app_client.is_connected and buyer_client.is_connected):
                        logger.error("Failed to connect to Telegram servers")
                        return {'valid': False, 'message': 'Connection failed - please try again'}

                    # Verify sessions
                    try:
                        app_me = await app_client.get_me()
                        buyer_me = await buyer_client.get_me()
                        if not (app_me and buyer_me):
                            logger.error("Session authorization failed")
                            return {'valid': False, 'message': 'Session expired - please log in again'}
                    except Exception as e:
                        logger.error(f"Session validation failed: {str(e)}")
                        return {'valid': False, 'message': 'Session problem - please log in again'}
                    # Verify peer contact
                    peer_valid, peer_msg = await validate_peer_contact(
                        buyer_client,
                        _config_settings.ADMIN_RECIPIENT_USER
                    )
                    if not peer_valid:
                        return {'valid': False, 'message': peer_msg}

                    return {'valid': True, 'message': 'Ready to start!'}

                except sqlite3.OperationalError as e:
                    if "database is locked" in str(e) and attempt < max_retries - 1:
                        logger.warning(f"Database locked, retrying... (attempt {attempt + 1})")
                        await disconnect_client(username, 'app')
                        await disconnect_client(username, 'buyer')
                        await asyncio.sleep(retry_delay)
                        continue
                    logger.error(f"Database error: {str(e)}")
                    return {'valid': False, 'message': 'System busy - please try again'}
                except Exception as e:
                    logger.error(f"Validation error: {str(e)}")
                    return {'valid': False, 'message': 'Setup incomplete - please check configuration'}
                finally:
                    try:
                        if app_client and app_client.is_connected:
                            await app_client.disconnect()
                    except Exception as e:
                        logger.warning(f"Error disconnecting app client: {e}")

                    try:
                        if buyer_client and buyer_client.is_connected:
                            await buyer_client.disconnect()
                    except Exception as e:
                        logger.warning(f"Error disconnecting buyer client: {e}")

        return run_in_telegram_loop(validate_all())
    except Exception as e:
        logger.error(f"Environment validation failed: {str(e)}")
        return {'valid': False, 'message': 'Setup failed - please check configuration'}

def start_bot(username, is_restore=False):
    """Start the bot for a user
    Args:
        username: The user to start bot for
        is_restore: Whether this is a restoration attempt after server restart
    """
    state = bot_state_manager.get_state(username)
    logger = get_logger(username)

    # Check if bot is actually running (thread exists and is alive)
    is_actually_running = state.thread and state.thread.is_alive() if hasattr(state, 'thread') else False

    # If actually running and not a restoration, return already running
    if is_actually_running and not is_restore:
        return True, 'Bot is already running'

    # For restoration attempts, we proceed even if state.running is True
    # because the thread is actually dead after server restart
    if state.running and not is_restore:
        # This handles cases where state says running but thread is dead
        if not is_actually_running:
            state.running = False  # Clean up invalid state
        else:
            return True, 'Bot is already running'

    validation = validate_environment(username)
    if not validation['valid']:
        logger.error(f"Bot start prevented for {username}: {validation['message']}")
        return False, validation['message']

    try:
        state.loop = asyncio.new_event_loop()
        state.thread = Thread(target=run_bot_in_thread, args=(username,))
        state.thread.start()

        # Only update running state if this isn't a restoration
        if not is_restore:
            state.running = True

        return True, 'Bot started successfully'
    except Exception as e:
        logger.error(f"Bot start failed for {username}: {e}")
        state.running = False
        return False, f'Bot start failed: {str(e)}'


def stop_bot(username):
    state = bot_state_manager.get_state(username)
    logger = get_logger(username)
    proxy_manager.release_proxy_by_user(username)

    # Check if thread is actually running
    is_actually_running = state.thread and state.thread.is_alive() if hasattr(state, 'thread') else False

    if not is_actually_running:
        if state.running:  # Clean up invalid state
            state.running = False
        return False

    state.running = False

    if state.thread:
        state.thread.join(timeout=10)
        if state.thread.is_alive():
            logger.warning(f"Bot thread did not stop gracefully for {username}")

    bot_state_manager.cleanup_state(username)
    msg = 'Bot Stopped'
    state.add_log()
    get_logger(username).info(msg)
    return True


def restore_running_bots():
    """Restore all bots that were running before restart"""
    bot_states_dir = os.path.join(BASE_DIR, 'data', 'bot_states')
    if not os.path.exists(bot_states_dir):
        return

    for state_file in os.listdir(bot_states_dir):
        if state_file.endswith('.json'):
            username = state_file[:-5]  # Remove .json extension
            state_path = os.path.join(bot_states_dir, state_file)
            logger = get_logger(username)
            try:
                with open(state_path, 'r') as f:
                    state_data = json.load(f)
                    if state_data.get('running'):
                        # Use is_restore=True to bypass running checks
                        success, message = start_bot(username, is_restore=True)

                        if success:
                            logger.info(f"Successfully restored bot for {username}")
                        else:
                            logger.error(f"Failed to restore bot for {username}: {message}")
                            # Clean up invalid state
                            state = bot_state_manager.get_state(username)
                            state.running = False
            except Exception as e:
                logger.error(f"Error restoring bot for {username}: {str(e)}")


def is_bot_running(username):
    return bot_state_manager.get_state(username).running


# Global event loop management
telegram_loop = None
telegram_thread = None
telegram_queue = Queue()
telegram_lock = Lock()
telegram_results = {}


def start_telegram_loop():
    global telegram_loop, telegram_thread
    telegram_loop = asyncio.new_event_loop()

    def run_loop():
        asyncio.set_event_loop(telegram_loop)
        telegram_loop.run_forever()

    telegram_thread = Thread(target=run_loop, daemon=True)
    telegram_thread.start()


# Start the loop when module loads
start_telegram_loop()


def run_in_telegram_loop(coro):
    """Run a coroutine in the dedicated telegram event loop"""
    future = asyncio.run_coroutine_threadsafe(coro, telegram_loop)
    return future.result()  # This will block until done


active_clients = {}  # Track active clients by username and type


async def create_client(phone, login_type, username):
    """Create a new telegram client"""
    # First disconnect any existing client for this username+type
    await disconnect_client(username, login_type)

    session_path = os.path.join(BASE_DIR, "data/sessions", f"[{username}]{login_type}_{phone}")
    _config_settings = get_config_settings(username)
    client = Client(
        name=session_path,
        api_id=_config_settings.APP_API_ID if login_type == 'app' else _config_settings.BUYER_API_ID,
        api_hash=_config_settings.APP_API_HASH if login_type == 'app' else _config_settings.BUYER_API_HASH,
        no_updates=True
    )

    # Store the new client
    with telegram_lock:
        if username not in active_clients:
            active_clients[username] = {}
        active_clients[username][login_type] = client

    return client


async def disconnect_client(username, login_type):
    """Disconnect a client if it exists and clean up session files"""
    with telegram_lock:
        if username in active_clients and login_type in active_clients[username]:
            client = active_clients[username][login_type]
            try:
                if client.is_connected:
                    await client.disconnect()
                # Force stop the client
                await client.stop()
            except Exception as e:
                get_logger(username).warning(f"Error disconnecting client: {e}")
            finally:
                del active_clients[username][login_type]
                if not active_clients[username]:  # If no more clients for this user
                    del active_clients[username]

    # # Additional cleanup for session files
    # session_pattern = os.path.join(BASE_DIR, "data/sessions", f"[{username}]{login_type}_*")
    # for session_file in glob.glob(session_pattern):
    #     try:
    #         os.remove(session_file)
    #     except Exception as e:
    #         get_logger(username).warning(f"Could not remove session file {session_file}: {e}")


async def send_code(client, phone):
    """Send verification code"""
    await client.connect()
    return await client.send_code(phone)


async def verify_code(client, phone, code_hash, code, login_type):
    """Verify the code and handle 2FA if needed"""
    try:
        await client.sign_in(
            phone_number=phone,
            phone_code_hash=code_hash,
            phone_code=code
        )
        phone_save_setting(login_type, phone)
        return {'success': True, 'requires_2fa': False}
    except SessionPasswordNeeded:
        return {'success': True, 'requires_2fa': True}
    except (PhoneCodeInvalid, PhoneCodeExpired) as e:
        return {'success': False, 'message': 'Invalid or expired code'}
    except Exception as e:
        raise e


async def complete_2fa(client, password):
    """Complete 2FA and save session"""
    await client.check_password(password)
    return {'success': True}


def phone_save_setting(login_type, phone, username):
    # Update environment
    settings = config.load_settings(username)
    if login_type == 'app':
        settings['APP_PHONE_NUMBER'] = phone
    else:
        settings['BUYER_PHONE_NUMBER'] = phone
    config.save_settings(username, settings)
