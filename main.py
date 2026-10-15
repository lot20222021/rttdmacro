import time
import json
import os
import requests

WEBHOOK_URL = os.getenv("WEBHOOK_URL")
ROLE_ID = "1560317338291675147"

PLACES = {
    "Lobby": 117995703220717,
    "Match": 118060896686640
}

STATE_FILE = "roblox_versions.json"
CHECK_INTERVAL = 45

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"Ошибка сохранения файла: {e}")

def get_universe_id(place_id):
    url = f"https://apis.roblox.com/universes/v1/places/{place_id}/universe"
    resp = requests.get(url, timeout=10)
    if resp.status_code == 200:
        return resp.json().get("universeId")
    return None

def get_game_updated_timestamp(universe_id):
    url = f"https://games.roblox.com/v1/games?universeIds={universe_id}"
    resp = requests.get(url, timeout=10)
    if resp.status_code == 200:
        data = resp.json().get("data", [])
        if data:
            return data[0].get("updated")
    return None

def send_discord_ping(label, place_id, old_ts, new_ts):
    if not WEBHOOK_URL:
        print("Ошибка: переменная WEBHOOK_URL не задана в панели!")
        return

    payload = {
        "username": "TD Version Watchdog",
        "content": (
            f"<@&{ROLE_ID}> **Игра обновилась в Roblox!**\n"
            f"**Плейс:** `{label}` (`{place_id}`)\n"
            f"**Прошлое обновление:** `{old_ts}`\n"
            f"**Новое обновление:** `{new_ts}`"
        ),
        "allowed_mentions": {
            "roles": [ROLE_ID]
        }
    }
    try:
        requests.post(WEBHOOK_URL, json=payload, timeout=10)
    except Exception as e:
        print(f"Ошибка отправки вебхука: {e}")

def main():
    print("Запуск мониторинга версий Roblox...", flush=True)
    state = load_state()
    universe_cache = {}

    while True:
        for label, place_id in PLACES.items():
            try:
                if place_id not in universe_cache:
                    uid = get_universe_id(place_id)
                    if uid:
                        universe_cache[place_id] = uid

                uid = universe_cache.get(place_id)
                if not uid:
                    continue

                updated_ts = get_game_updated_timestamp(uid)
                if not updated_ts:
                    continue

                key = str(place_id)
                old_ts = state.get(key)

                if old_ts is None:
                    state[key] = updated_ts
                    save_state(state)
                    print(f"[{label}] Зафиксирована текущая версия: {updated_ts}", flush=True)
                elif old_ts != updated_ts:
                    state[key] = updated_ts
                    save_state(state)
                    print(f"[{label}] ОБНОВЛЕНИЕ: {old_ts} -> {updated_ts}", flush=True)
                    send_discord_ping(label, place_id, old_ts, new_ts=updated_ts)

            except Exception as e:
                print(f"Ошибка при проверке {label}: {e}", flush=True)

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
