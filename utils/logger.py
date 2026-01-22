# utils/logger.py
import logging
import sys
from pathlib import Path
from functools import lru_cache
import config   # your own module that has get_log_file(username)


@lru_cache(maxsize=None)        # one instance per username
def get_logger(username: str) -> logging.Logger:
    """
    Return a logger that writes to <logs>/<username>.log and stdout.
    Cached, so the same object is reused for each username.
    """
    logger = logging.getLogger(f"bot.{username}")

    # If first time we see this user, attach handlers/formatters
    if not logger.handlers:
        logger.setLevel(logging.INFO)

        fmt = logging.Formatter("%(asctime)s [%(levelname)s] ["+username+"] %(message)s")

        # Make sure the directory exists
        Path(config.get_log_file(username)).parent.mkdir(parents=True, exist_ok=True)

        fh = logging.FileHandler(config.get_log_file(username), encoding="utf-8")
        fh.setFormatter(fmt)

        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)

        logger.addHandler(fh)
        logger.addHandler(sh)
        logger.propagate = False          # don’t duplicate to root
    return logger
