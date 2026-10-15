import os
import time
import json
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://discord.com/api/webhooks/1560392929284071454/ZyF07_fB4eSqGNU61A_8MgJOduwpSBxf0Lx8ub0Q3q6mOBHvyCkUmF51XHNCnctPuS8d")
ROLE_ID = os.getenv("ROLE_ID", "1560317338291675147")
PORT = int(os.getenv("PORT", 8000))

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
        print(f"Save error: {e}", flush=True)

def ping_version_update(place_name, place_id, old_ver, new_ver, player_name):
    payload = {
        "username": "TD Version Watchdog",
        "content": (
            f"<@&{ROLE_ID}> **Обнаружено обновление игры при заходе!**\n"
            f"**Режим:** `{place_name}` (`{place_id}`)\n"
            f"**Версия:** `{old_ver}` ➔ `{new_ver}`\n"
            f"**Зафиксировал аккаунт:** `{player_name}`"
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
    accounts = state.get("accounts", {})
    if not accounts:
        return

    fields = []
    for acc_name, info in accounts.items():
        ts = info.get("timestamp", int(time.time()))
        place = info.get("place", "Lobby")
        ver = info.get("version", "?")
        currencies = info.get("currencies", {})
        start_currencies = info.get("start_currencies", {})

        curr_lines = []
        for c_name, c_val in currencies.items():
            start_val = start_currencies.get(c_name, c_val)
            diff = c_val - start_val
            diff_str = f" (+{diff})" if diff > 0 else (f" ({diff})" if diff < 0 else "")
            curr_lines.append(f"• **{c_name}:** `{c_val}`{diff_str}")

        curr_text = "\n".join(curr_lines) if curr_lines else "• Валюта не найдена"

        field_val = (
            f"📍 **Статус:** `{place}` (v: `{ver}`)\n"
            f"{curr_text}\n"
            f"🕒 **Updated:** <t:{ts}:R>"
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
            "text": "Статус обновляется при каждом заходе аккаунта в Лобби / Матч"
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
            if resp.status_code == 200:
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
    return jsonify({"status": "running"})

@app.route("/report", methods=["POST"])
def report():
    data = request.get_json(silent=True) or {}
    player = str(data.get("player", "Unknown"))
    place_id = str(data.get("place_id", ""))
    place_name = str(data.get("place_name", "Lobby"))
    version = str(data.get("version", ""))
    currencies = data.get("currencies", {})

    if not place_id:
        return jsonify({"error": "missing place_id"}), 400

    state = load_state()
    now_ts = int(time.time())

    if version:
        old_ver = state["versions"].get(place_id)
        if old_ver is None:
            state["versions"][place_id] = version
        elif old_ver != version:
            state["versions"][place_id] = version
            ping_version_update(place_name, place_id, old_ver, version, player)

    acc_entry = state["accounts"].get(player, {})
    start_curr = acc_entry.get("start_currencies", currencies)

    state["accounts"][player] = {
        "place": place_name,
        "version": version,
        "currencies": currencies,
        "start_currencies": start_curr,
        "timestamp": now_ts
    }

    save_state(state)
    update_discord_dashboard(state)

    return jsonify({"status": "ok", "timestamp": now_ts})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
