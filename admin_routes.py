# admin_routes.py
from flask import render_template, request, jsonify, redirect, url_for, session, g
from datetime import datetime, timedelta
import models
from routes import app
from bot_manager import bot_state_manager, stop_bot
from utils.proxy import ProxyManager
user_manager = models.UserManager()
proxy_manager = ProxyManager()


@app.route('/admin/dashboard')
def admin_dashboard():
    if not g.admin:
        return redirect(url_for('login'))

    users = []
    for username, user in user_manager.users.items():
        expiry_date = datetime.strptime(user.expire_date, "%Y-%m-%d")
        days_left = (expiry_date.date() - datetime.now().date()).days

        # Get bot status
        bot_status = user_manager.get_user_bot_status(username)
        bot_state = bot_state_manager.get_state(username)
        users.append({
            "username": username,
            "expire_date": user.expire_date,
            "days_left": days_left,
            "is_admin": user.is_admin,
            "is_owner": user.is_owner,
            "active": user.active,
            "bot_running": bot_status['is_running'],
            "can_disable_bot": bot_status['can_disable'],
            "current_balance_stars": bot_state.current_balance_stars if bot_state.current_balance_stars is not None else "N/A"
        })

    users.sort(key=lambda x: x["days_left"])
    return render_template('admin_dashboard.html.j2',
                           users=users,
                           is_owner=user_manager.is_owner(g.username),
                           user_manager=user_manager
                           )


@app.route('/admin/create_user', methods=['POST'])
def admin_create_user():
    if not g.admin:
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    data = request.json
    username = data.get('username')
    password = data.get('password')
    expire_days = data.get('expire_days', 30)
    is_admin = data.get('is_admin', False) and user_manager.is_owner(g.username)

    if not username or not password:
        return jsonify({"status": "error", "message": "Username and password required"}), 400

    if username in user_manager.users:
        return jsonify({"status": "error", "message": "Username already exists"}), 400

    try:
        # Convert to integer if it's a string
        expire_days = int(expire_days)
        expire_date = (datetime.now() + timedelta(days=expire_days)).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "Invalid expiration days value"}), 400

    user_manager.add_user(username, password, expire_date, is_admin=is_admin)

    return jsonify({
        "status": "success",
        "message": "User created successfully",
        "user": {
            "username": username,
            "expire_date": expire_date
        }
    })


@app.route('/admin/update_user', methods=['POST'])
def admin_update_user():
    if not g.admin:
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    data = request.json
    username = data.get('username')
    current_user = user_manager.get_user(g.username)
    target_user = user_manager.get_user(username)

    # Validate permissions
    if not user_manager.can_edit_user(g.username, username):
        return jsonify({"status": "error", "message": "You don't have permission to edit this user"}), 403

    # Handle expiry date update
    if 'new_expiry' in data:
        # Only allow expiry date changes for non-admins or if owner
        if target_user.is_admin and not current_user.is_owner:
            return jsonify({"status": "error", "message": "Only owner can modify admin expiry dates"}), 403

        if not user_manager.update_user_expiry(username, data['new_expiry']):
            return jsonify({"status": "error", "message": "Failed to update expiry date"}), 400

    # Handle password update
    if 'new_password' in data:
        if not user_manager.update_user_password(username, data['new_password']):
            return jsonify({"status": "error", "message": "Failed to update password"}), 400

    return jsonify({
        "status": "success",
        "message": "User updated successfully"
    })


@app.route('/admin/delete_user', methods=['POST'])
def admin_delete_user():
    if not g.admin:
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    username = request.json.get('username')

    # Prevent self-deletion
    if g.username == username:
        return jsonify({"status": "error", "message": "You cannot delete yourself"}), 400

    # Check edit permissions
    if not user_manager.can_edit_user(g.username, username):
        return jsonify({"status": "error", "message": "You don't have permission to delete this user"}), 403

    if not user_manager.delete_user(username):
        return jsonify({"status": "error", "message": "User not found"}), 404

    return jsonify({
        "status": "success",
        "message": "User deleted successfully"
    })


@app.route('/admin/toggle_user', methods=['POST'])
def admin_toggle_user():
    if not g.admin:
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    username = request.json.get('username')
    active = request.json.get('active')  # Optional: force specific state

    if isinstance(active, str):
        active = active.lower() == 'true'

    if not username:
        return jsonify({"status": "error", "message": "Username required"}), 400

    if not user_manager.is_owner(username) and user_manager.is_admin(username):
        return jsonify({"status": "error", "message": "Cannot modify admin user"}), 400

    if not user_manager.toggle_user_active(username, active):
        return jsonify({"status": "error", "message": "User not found"}), 404

    stop_bot(username)

    return jsonify({
        "status": "success",
        "message": "User status updated",
        "active": user_manager.users[username].active
    })


@app.route('/admin/update_password', methods=['POST'])
def admin_update_password():
    if not g.admin:
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    data = request.json
    username = data.get('username')
    current_user = user_manager.get_user(g.username)
    target_user = user_manager.get_user(username)
    new_password = data.get('new_password')

    if not current_user.is_owner:
        # Admin trying to change another admin's password
        if target_user.is_admin and current_user.username != target_user.username:
            return jsonify({"status": "error", "message": "You can only change your own password"}), 403

    if not username or not new_password:
        return jsonify({"status": "error", "message": "Username and password required"}), 400

    if not user_manager.update_user_password(username, new_password):
        return jsonify({"status": "error", "message": "Failed to update password"}), 500

    return jsonify({
        "status": "success",
        "message": "Password updated successfully"
    })


@app.route('/admin/stop_bot', methods=['POST'])
def admin_stop_bot():
    if not g.admin:
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    username = request.json.get('username')

    if not username:
        return jsonify({"status": "error", "message": "Username required"}), 400

    # if user_manager.is_admin(username):
    #     return jsonify({"status": "error", "message": "Cannot modify admin bot"}), 400

    success = stop_bot(username)

    return jsonify({
        "status": "success" if success else "error",
        "message": "Bot stopped successfully" if success else "Failed to stop bot"
    })


@app.route('/admin/promote_admin', methods=['POST'])
def admin_promote_admin():
    if not g.admin or not user_manager.is_owner(g.username):
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    username = request.json.get('username')

    if not username:
        return jsonify({"status": "error", "message": "Username required"}), 400

    if not user_manager.promote_to_admin(username):
        return jsonify({"status": "error", "message": "Failed to promote user"}), 400

    return jsonify({
        "status": "success",
        "message": "User promoted to admin"
    })


@app.route('/admin/demote_admin', methods=['POST'])
def admin_demote_admin():
    if not g.admin or not user_manager.is_owner(g.username):
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    username = request.json.get('username')

    if not username:
        return jsonify({"status": "error", "message": "Username required"}), 400

    if not user_manager.demote_admin(username):
        return jsonify({"status": "error", "message": "Failed to demote admin"}), 400

    return jsonify({
        "status": "success",
        "message": "Admin privileges removed"
    })


# Add these new routes to admin_routes.py

@app.route('/admin/proxies', methods=['GET', 'POST'])
def manage_proxies():
    if not g.admin:
        return redirect(url_for('login'))

    if request.method == 'POST':
        try:
            data = request.json
            action = data.get('action')

            if action == 'add':
                proxy_manager.add_proxy(data['host'], 
                                  int(data['port']), 
                                  data.get('username', ''), 
                                  data.get('password', ''))
                return jsonify({'status': 'success', 'message': 'Proxy added'})

            elif action == 'remove':
                proxy_manager.remove_proxy(data['host'], int(data['port']))
                return jsonify({'status': 'success', 'message': 'Proxy removed'})

            elif action == 'test':
                # Implement proxy testing if needed
                return jsonify({'status': 'success', 'message': 'Proxy test not implemented yet'})

        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 400

    # GET request - return proxy list
    return jsonify({'status': 'success', 'proxies': proxy_manager.get_proxy_list()})


@app.route('/admin/proxy_stats', methods=['GET'])
def proxy_stats():
    if not g.admin:
        return redirect(url_for('login'))

    proxies = proxy_manager.get_proxy_list()
    stats = {
        'total': len(proxies),
        'available': len([p for p in proxies if not p['in_use']]),
        'in_use': len([p for p in proxies if p['in_use']])
    }

    return jsonify({'status': 'success', 'stats': stats})
