import os
import re
import time
import json
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

WEBHOOK_URL = os.getenv("WEBHOOK_URL")
ROLE_ID = os.getenv("ROLE_ID", "1560317338291675147")
PORT = int(os.getenv("PORT", 3000))

STATE_FILE = "bot_state.json"

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "versions": {},
        "accounts": {},
        "dashboard_msg_id": None
    }

def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving state: {e}", flush=True)

def is_valid_currency(val):
    if val is None:
        return False
    s = str(val).strip()
    if not s or "?" in s:
        return False
    return bool(re.search(r"\d", s))

def parse_int(val):
    if not is_valid_currency(val):
        return None
    digits = re.sub(r"\D", "", str(val))
    return int(digits) if digits else None

def format_currency_line(curr_val, start_val):
    if not is_valid_currency(curr_val):
        return "`Unknown (Waiting for Lobby)`"
    c_num = parse_int(curr_val)
    s_num = parse_int(start_val)
    if c_num is not None and s_num is not None:
        diff = c_num - s_num
        if diff > 0:
            return f"`{curr_val}` (+{diff})"
        elif diff < 0:
            return f"`{curr_val}` ({diff})"
    return f"`{curr_val}`"

def ping_version_update(place_name, place_id, old_ver, new_ver, player_name):
    if not WEBHOOK_URL:
        print("Error: WEBHOOK_URL is not set!", flush=True)
        return

    payload = {
        "username": "TD Version Watchdog",
        "content": (
            f"<@&{ROLE_ID}> **Game Version Update Detected!**\n"
            f"**Place:** `{place_name}` (`{place_id}`)\n"
            f"**Version:** `{old_ver}` -> `{new_ver}`\n"
            f"**Detected by:** `{player_name}`"
        ),
        "allowed_mentions": {
            "roles": [ROLE_ID]
        }
    }
    try:
        requests.post(WEBHOOK_URL, json=payload, timeout=10)
    except Exception as e:
        print(f"Webhook ping error: {e}", flush=True)

def update_discord_dashboard(state):
    if not WEBHOOK_URL:
        print("Error: WEBHOOK_URL is not set!", flush=True)
        return

    accounts = state.get("accounts", {})
    if not accounts:
        return

    fields = []
    for acc_name, info in accounts.items():
        ts = info.get("timestamp", int(time.time()))
        place = info.get("place", "Lobby")
        ver = info.get("version", "?")

        coins_str = format_currency_line(info.get("coins"), info.get("start_coins"))
        pumpkins_str = format_currency_line(info.get("pumpkins"), info.get("start_pumpkins"))

        field_val = (
            f"📍 **Location:** `{place}` (`{ver}`)\n"
            f"🪙 **Coins:** {coins_str}\n"
            f"🎃 **Pumpkins:** {pumpkins_str}\n"
            f"🕒 **Last updated:** <t:{ts}:R>"
        )
        fields.append({
            "name": f"👤 {acc_name}",
            "value": field_val,
            "inline": True
        })

    embed = {
        "title": "📊 TD Multi-Account Farm Monitor",
        "color": 3447003,
        "fields": fields,
        "footer": {
            "text": "Updates automatically when an account joins Lobby or Match"
        }
    }

    payload = {
        "username": "TD Farm Monitor",
        "embeds": [embed]
    }

    msg_id = state.get("dashboard_msg_id")
    try:
        if msg_id:
            edit_url = f"{WEBHOOK_URL}/messages/{msg_id}"
            resp = requests.patch(edit_url, json=payload, timeout=10)
            if resp.status_code in (200, 204):
                return

        post_url = f"{WEBHOOK_URL}?wait=true"
        resp = requests.post(post_url, json=payload, timeout=10)
        if resp.status_code in (200, 201):
            data = resp.json()
            state["dashboard_msg_id"] = data.get("id")
            save_state(state)
    except Exception as e:
        print(f"Dashboard update error: {e}", flush=True)

@app.route("/", methods=["GET"])
def index():
    return jsonify({"status": "running", "service": "TD Farm Monitor"})

@app.route("/report", methods=["POST"])
def report():
    data = request.get_json(silent=True) or {}
    player = str(data.get("player", "Unknown"))
    place_id = str(data.get("place_id", ""))
    place_name = str(data.get("place_name", "Lobby"))
    version = str(data.get("version", ""))
    raw_coins = data.get("coins")
    raw_pumpkins = data.get("pumpkins")

    if not place_id:
        return jsonify({"error": "missing place_id"}), 400

    state = load_state()
    now_ts = int(time.time())

    if version:
        old_ver = state["versions"].get(place_id)
        if old_ver is None:
            state["versions"][place_id] = version
            print(f"Initialized version for {place_name} ({place_id}): {version}", flush=True)
        elif old_ver != version:
            state["versions"][place_id] = version
            print(f"Version updated for {place_name}: {old_ver} -> {version}", flush=True)
            ping_version_update(place_name, place_id, old_ver, version, player)

    acc_info = state["accounts"].get(player, {})

    if is_valid_currency(raw_coins):
        acc_info["coins"] = str(raw_coins).strip()
        if not is_valid_currency(acc_info.get("start_coins")):
            acc_info["start_coins"] = str(raw_coins).strip()

    if is_valid_currency(raw_pumpkins):
        acc_info["pumpkins"] = str(raw_pumpkins).strip()
        if not is_valid_currency(acc_info.get("start_pumpkins")):
            acc_info["start_pumpkins"] = str(raw_pumpkins).strip()

    acc_info["place"] = place_name
    acc_info["version"] = version
    acc_info["timestamp"] = now_ts

    state["accounts"][player] = acc_info

    save_state(state)
    update_discord_dashboard(state)

    return jsonify({"status": "ok", "timestamp": now_ts})

if __name__ == "__main__":
    print(f"Starting TD Monitor Server on port {PORT}...", flush=True)
    app.run(host="0.0.0.0", port=PORT)
