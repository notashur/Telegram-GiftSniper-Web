# routes.py
import json
from flask import Flask, render_template, request, jsonify, redirect, send_from_directory, url_for, flash, session, g
from flask_session import Session
# from pyotp import TOTP
import config
import models
from bot_manager import (
    bot_state_manager, is_bot_running, start_bot, stop_bot,
    run_in_telegram_loop, create_client, send_code,
    verify_code, complete_2fa, phone_save_setting, 
    telegram_lock, disconnect_client
)
import bot_manager
from data.gifts import GIFT_MAPPINGS, BACKDROP_CENTER_COLORS
from utils.logger import get_logger
import time
from datetime import datetime, timedelta
from flask_minify import Minify  # type: ignore
# from flask_wtf import CSRFProtect
# from flask_talisman import Talisman
import models
from dotenv import load_dotenv
import os

load_dotenv()
app = Flask(__name__)

app.secret_key = b'c\xce%\xdb\xac\xcc\x96\xa5]\xad\xfa\x89\xb6\x91\xd8-\x04\xea6\xc5\xae\xda\xa9]T\xa9mD?\xf2\xebp'
IS_DOMAIN = os.getenv('IS_DOMAIN')
app.config.update(
    SESSION_COOKIE_SECURE=IS_DOMAIN,        # Keep this for HTTPS
    SESSION_COOKIE_HTTPONLY=True,      # Keep this for security
    SESSION_COOKIE_SAMESITE='Lax',     # Good for security
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),  # Extend session lifetime
    SESSION_REFRESH_EACH_REQUEST=True,  # Refresh session on each request
    SESSION_COOKIE_NAME='giftsniper_session',  # Custom cookie name
    SESSION_TYPE='filesystem',          # Use filesystem for persistent sessions
)
Session(app)
# Talisman(app, content_security_policy=None)
# CSRFProtect(app)
Minify(app=app, html=True, js=True, cssless=True)


def bot_state():
    return bot_state_manager.get_state(g.username)
sessions = {}

@app.route('/')
def index():
    settings = config.load_settings(g.username)
    user_manager = models.UserManager()
    expiry_date_str = user_manager.get_user(g.username).expire_date
    if expiry_date_str:
        expiry_date = datetime.strptime(expiry_date_str, '%Y-%m-%d')
        today = datetime.now()
        is_expired = today > expiry_date
        days_left = (expiry_date.date() - today.date()).days
        expiry_timestamp = int(expiry_date.timestamp()) * 1000  # milliseconds for JS
    else:
        is_expired = None
        days_left = None
        expiry_timestamp = None

    return render_template(
        'index.html.j2',
        settings=settings,
        bot_status=is_bot_running(g.username),
        current_balance_stars=bot_state().current_balance_stars if bot_state().current_balance_stars is not None else "N/A",
        current_balance_ton=bot_state().current_balance_ton if bot_state().current_balance_ton is not None else "N/A",
        recent_logs=bot_state().recent_logs,
        account_expired=is_expired,
        days_left=days_left,
        expiry_date=expiry_date_str,
        expiry_timestamp=expiry_timestamp,
        bot_cycles=bot_state().bot_cycle if bot_state().bot_cycle is not None else "N/A",
        GIFT_MAPPINGS=GIFT_MAPPINGS,
        BACKDROP_CENTER_COLORS=BACKDROP_CENTER_COLORS,
        is_admin = user_manager.is_admin(g.username)
    )


@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        new_settings = request.form.to_dict()
        new_settings['SLEEP_BETWEEN_CYCLES'] = int(new_settings['SLEEP_BETWEEN_CYCLES'])
        new_settings['GIFTS_NOT_TO_BUY'] = request.form.getlist('GIFTS_NOT_TO_BUY')
        new_settings['BACKDROPS_NOT_TO_BUY'] = request.form.getlist('BACKDROPS_NOT_TO_BUY')
        print(new_settings)
        config.save_settings(g.username, new_settings)
        # Stop the bot if it's running to apply new settings
        stop_bot(g.username)
        flash('Settings saved successfully!', 'success')

        return redirect(url_for('settings'))

    settings = config.load_settings(g.username)
    sorted_gifts = dict(sorted(GIFT_MAPPINGS.items(), key=lambda item: item[1]))
    return render_template('settings.html',
                           settings=settings,
                           GIFT_MAPPINGS=sorted_gifts,
                           BACKDROP_CENTER_COLORS=BACKDROP_CENTER_COLORS.items())


@app.route('/settings/gift-limits', methods=['GET', 'POST'])
def gift_limits():
    settings = config.load_settings(g.username)
    if request.method == 'POST':
        # Get all form data
        form_data = request.form.to_dict()

        # Extract gift limits (fields starting with GIFT_LIMIT_)
        gift_limits = {}
        for key, value in form_data.items():
            if key.startswith('GIFT_LIMIT_'):
                gift_name = key.replace('GIFT_LIMIT_', '')
                if value:  # Only add if a value was provided
                    try:
                        gift_limits[gift_name] = int(value)
                    except ValueError:
                        pass  # Skip invalid entries

        # Save the new limits
        config.save_settings(g.username, {'GIFT_LIMITS': gift_limits})
        stop_bot(g.username)
        flash('Gift limits updated successfully!', 'success')
        return redirect(url_for('gift_limits'))

    # For GET requests, show the form
    return render_template('gift_limits.html.j2',
                           settings=settings,
                           GIFT_MAPPINGS=GIFT_MAPPINGS)

# <!-- Logs Endpoint -->


@app.route('/quick-logs')
def quick_logs():
    page = request.args.get('page', default=1, type=int)
    per_page = request.args.get('per_page', default=10, type=int)

    # Get the logs in reverse order (newest first)
    all_logs = bot_state().recent_logs[::-1]

    # Calculate pagination
    total_logs = len(all_logs)
    total_pages = max(1, (total_logs + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))  # Clamp page between 1 and total_pages

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_logs = all_logs[start_idx:end_idx]

    return jsonify({
        'logs': paginated_logs,
        'pagination': {
            'current_page': page,
            'per_page': per_page,
            'total_pages': total_pages,
            'total_logs': total_logs
        },
        'status': bot_state().running,
        'balance': bot_state().current_balance_stars,
        'balance_ton': bot_state().current_balance_ton
    })

  # https://gift.ashur.gay/static/gifts/id
  # return static/gifts/id .png


@app.route('/static/gifts/<path:filename>')
def serve_gift_image(filename):
    return send_from_directory('static/gifts', filename)


@app.template_filter('find_key')
def find_key(d, value):
    return next((k for k, v in d.items() if v == value), None)

@app.route('/api/bot/start', methods=['POST'])
def api_start_bot():
    if bot_state().running:
        return jsonify({'status': 'error', 'message': 'Bot is already running'})
    started, message = start_bot(g.username)
    return jsonify({'status': 'success' if started else 'error', 'message': message})


@app.route('/api/bot/stop', methods=['POST'])
def api_stop_bot():
    success = stop_bot(g.username)
    return jsonify({'status': 'success' if success else 'error', 'message': 'Bot stopped' if success else 'Bot is not running'})


@app.route('/api/bot/status', methods=['GET'])
def api_bot_status():
    return jsonify({
        'running': bot_state().running,
        'balance_stars': bot_state().current_balance_stars if bot_state().current_balance_stars is not None else "N/A",
        'balance_ton': bot_state().current_balance_ton if bot_state().current_balance_ton is not None else "N/A",
        'last_error': bot_state().last_error,
        'thread_alive': bot_state().thread.is_alive() if bot_state().thread else False,
        'bot_cycles': bot_state().bot_cycle if bot_state().bot_cycle is not None else "N/A",
    })


@app.route('/api/bot/runtime', methods=['GET'])
def api_bot_runtime():
    if not bot_state().running or not bot_state().start_time:
        return jsonify({'runtime': 0})
    return jsonify({'runtime': int(time.time() - bot_state().start_time)})


# <!-- Telegram Login and Verification Endpoints -->
@app.route('/api/telegram/login', methods=['POST'])
def handle_login():
    data = request.json
    phone = data.get('phone')
    login_type = data.get('type')
    username = g.username
    
    if not phone or login_type not in ['app', 'buyer']:
        return jsonify({'success': False, 'message': 'Invalid parameters'})

    # Validate required settings
    missing = []
    user_settings = config.load_settings(username)
    if login_type == 'app':
        if not user_settings['APP_API_ID']:
            missing.append('App ID')
        if not user_settings['APP_API_HASH']:
            missing.append('App API Hash')
    elif login_type == 'buyer':
        if not user_settings['BUYER_API_ID']:
            missing.append('Buyer App ID')
        if not user_settings['BUYER_API_HASH']:
            missing.append('Buyer App API Hash')
    if missing:
        return jsonify({'success': False, 'message': f"Missing: {', '.join(missing)}"})

    try:
        # Disconnect any existing session first
        run_in_telegram_loop(disconnect_client(username, login_type))
        
        # Create new client
        client = run_in_telegram_loop(create_client(phone, login_type, username))
        sent_code = run_in_telegram_loop(send_code(client, phone))
        
        with telegram_lock:
            sessions[phone] = (client, sent_code.phone_code_hash, login_type)
            
        return jsonify({'success': True})
    except Exception as e:
        get_logger(username).error(f"Login error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/telegram/verify', methods=['POST'])
def handle_verify():
    data = request.json
    phone = data.get('phone')
    code = data.get('code')
    login_type = data.get('type')
    username = g.username
    
    with telegram_lock:
        session_data = sessions.get(phone)
        if not session_data or session_data[2] != login_type:
            return jsonify({'success': False, 'message': 'Invalid session'})
    
    client, code_hash, _ = session_data
    try:
        result = run_in_telegram_loop(verify_code(client, phone, code_hash, code, login_type))
        
        # Clean up session reference after successful verification
        if result.get('success') and not result.get('requires_2fa'):
            with telegram_lock:
                if phone in sessions:
                    del sessions[phone]
                    
        return jsonify(result)
    except Exception as e:
        get_logger(username).error(f"Verify error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)})
    finally:
        # Ensure client is properly stored in bot_manager.active_clients
        with telegram_lock:
            if username not in bot_manager.active_clients:
                bot_manager.active_clients[username] = {}
            bot_manager.active_clients[username][login_type] = client

@app.route('/api/telegram/2fa', methods=['POST'])
def handle_2fa():
    data = request.json
    phone = data.get('phone')
    password = data.get('password')
    login_type = data.get('type')
    username = g.username
    
    with telegram_lock:
        session_data = sessions.get(phone)
        if not session_data or session_data[2] != login_type:
            return jsonify({'success': False, 'message': 'Invalid session'})
    
    client, _, _ = session_data
    try:
        result = run_in_telegram_loop(complete_2fa(client, password))
        
        # Update settings and clean up
        if result.get('success'):
            phone_save_setting(login_type, phone, username)
            with telegram_lock:
                if phone in sessions:
                    del sessions[phone]
                    
        return jsonify(result)
    except Exception as e:
        get_logger(username).error(f"2FA error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)})
    finally:
        # Ensure client is properly stored
        with telegram_lock:
            if username not in bot_manager.active_clients:
                bot_manager.active_clients[username] = {}
            bot_manager.active_clients[username][login_type] = client


# <!-- Global Login Check Middleware -->
@app.before_request
def check_login_and_expiry():
    # Skip for these endpoints
    if request.endpoint in ['login', 'login_page', 'static']:
        return
        
    # Existing user check
    if 'username' not in session:
        flash('You must log in first.', 'error')
        return redirect(url_for('login'))
    
    user_manager = models.UserManager()
    user = user_manager.get_user(session['username'])
    # Check if user is an admin
    if user_manager.is_admin(session['username']):
        g.username = session['username']
        g.admin = True
        return
    # Check if user is active
    if not user.active:
        session.clear()
        flash('Your account has been disabled', 'error')
        return redirect(url_for('login'))
    
    g.username = session['username']
    
    # Check expiration (skip for admin)
    if user_manager.is_expired(session['username']):
        expiration_date = user_manager.get_user(session['username']).expire_date
        session.clear()
        return render_template('expired.html', expiry_date=expiration_date)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user_manager = models.UserManager()
        username = request.form['username']
        password = request.form['password']
        
        # Regular user login
        user = user_manager.authenticate(username, password)
        if user:
            session['username'] = username
            g.username = username
            if user_manager.is_expired(username):
                expiration_date = user_manager.get_user(username).expire_date
                return render_template('expired.html', expiry_date=expiration_date)
            return redirect(url_for('index'))
            
        flash('Invalid credentials')
    return render_template('login.html.j2')

@app.route('/logout', methods=['POST'])
def logout():
    session.pop('username', None)  # Remove logged-in status
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))  # Redirect to the login page


@app.route('/save-subscription', methods=['POST'])
def save_subscription():
    try:
        new_sub = request.get_json()  # More explicit than request.json
        if not new_sub or 'endpoint' not in new_sub:
            return jsonify({"error": "Invalid subscription data"}), 400

        subs = config.load_subscriptions()
        new_sub['username'] = g.username  # Add username from Flask's g context

        # Check for existing subscription (by endpoint and username)
        exists = any(
            sub['endpoint'] == new_sub['endpoint'] and 
            sub.get('username') == g.username
            for sub in subs
        )

        if not exists:
            subs.append(new_sub)
            try:
                with open(config.SUBSCRIPTIONS_FILE, 'w') as f:
                    json.dump(subs, f, indent=2)  # Indent for better readability
                return jsonify({"status": "added"})
            except IOError as e:
                return jsonify({"error": "Failed to save subscription"}), 500
        return jsonify({"status": "already_exists"})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def initialize_app():
    # This will be called when the app starts
    with app.app_context():
        bot_manager.restore_running_bots()

# Manually call initialize_app when the module loads
initialize_app()
