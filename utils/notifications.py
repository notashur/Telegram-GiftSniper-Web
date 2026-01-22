from pywebpush import webpush, WebPushException
import json
import config
from utils.logger import get_logger
VAPID_PRIVATE_KEY = "WvbWZfe5mdZxMMIr_7JLnkGNV0A3g5Wg3M8M9YbVsbk"

# def send_notification_to_all(title, body):
#     subs = config.load_subscriptions()
#     for sub in subs:
#         try:
#             webpush(
#                 subscription_info=sub,
#                 data=json.dumps({"title": title, "body": body}),
#                 vapid_private_key=VAPID_PRIVATE_KEY,
#                 vapid_claims={"sub": "mailto:admin@ashur.gay"}
#             )
#             # logger.info(f"Sent to {sub['endpoint']}")
#         except Exception as e:
#             # logger.error(f"Failed to send to {sub['endpoint']}: {e}")
#             # Optional: Remove dead subscriptions
#             subs.remove(sub)
#             with open(config.SUBSCRIPTIONS_FILE, 'w') as f:
#                 json.dump(subs, f)


def send_notification_to_user(title, body, username):
    """Send push notification to a specific user"""
    try:
        subs = config.load_subscriptions()
        logger = get_logger(username)
        user_subs = [sub for sub in subs if sub.get('username') == username]
        
        if not user_subs:
            return False

        success_count = 0
        updated_subs = subs.copy()  # Work on a copy to avoid modifying during iteration

        for sub in user_subs:
            try:
                webpush(
                    subscription_info=sub,
                    data=json.dumps({"title": title, "body": body}),
                    vapid_private_key=VAPID_PRIVATE_KEY,
                    vapid_claims={"sub": "mailto:admin@ashur.gay"}
                )
                success_count += 1
            except WebPushException as e:
                if e.response.status_code == 410:  # Gone - subscription expired
                    updated_subs.remove(sub)
                # Log other errors but continue with other subscriptions
                logger.error(f"Push notification failed for {username}: {str(e)}")

        # Only update file if subscriptions were removed
        if len(updated_subs) != len(subs):
            try:
                with open(config.SUBSCRIPTIONS_FILE, 'w') as f:
                    json.dump(updated_subs, f, indent=2)
            except IOError as e:
                logger.error(f"Failed to update subscriptions: {str(e)}")

        return success_count > 0
    
    except Exception as e:
        logger.error(f"Notification system error: {str(e)}")
        return False