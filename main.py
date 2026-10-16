import os
import re
import time
import json
import secrets
import threading
import requests
import discord
from discord.ext import commands
from discord import app_commands
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
ROLE_ID = os.getenv("ROLE_ID", "1560317338291675147")
PORT = int(os.getenv("PORT", 3000))

STATE_FILE = "bot_state.json"
state_lock = threading.Lock()

app = Flask(__name__)

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                data.setdefault("versions", {})
                data.setdefault("accounts", {})
                data.setdefault("users", {})
                data.setdefault("codes", {})
                return data
        except Exception as e:
            print(f"Error reading state file: {e}", flush=True)
    return {
        "versions": {},
        "accounts": {},
        "users": {},
        "codes": {}
    }

def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving state file: {e}", flush=True)

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

def format_number(num):
    if num is None:
        return "0"
    return f"{num:,}"

def format_currency_display(curr_val, start_val):
    if not is_valid_currency(curr_val):
        return "`Waiting for Lobby...`"
    c_num = parse_int(curr_val)
    s_num = parse_int(start_val)
    if c_num is not None and s_num is not None:
        diff = c_num - s_num
        if diff > 0:
            return f"`{format_number(c_num)}` *(+{format_number(diff)})*"
        elif diff < 0:
            return f"`{format_number(c_num)}` *({format_number(diff)})*"
        return f"`{format_number(c_num)}`"
    return f"`{curr_val}`"

def format_place_Emoji(place_str):
    if not place_str:
        return "❓ `Unknown`"
    low = place_str.lower()
    if "match" in low:
        return f"🎮 `{place_str}`"
    if "lobby" in low:
        return f"🏠 `{place_str}`"
    return f"📍 `{place_str}`"

def get_or_create_link_code(discord_id_str, force_new=False):
    with state_lock:
        state = load_state()
        user_data = state["users"].setdefault(discord_id_str, {"code": None, "accounts": []})
        old_code = user_data.get("code")

        if old_code and not force_new:
            return old_code

        if old_code and old_code in state["codes"]:
            del state["codes"][old_code]

        new_code = "BZ-" + secrets.token_hex(3).upper()
        while new_code in state["codes"]:
            new_code = "BZ-" + secrets.token_hex(3).upper()

        user_data["code"] = new_code
        state["codes"][new_code] = discord_id_str
        save_state(state)
        return new_code

def ping_version_update(place_name, place_id, old_ver, new_ver, player_name):
    if not WEBHOOK_URL:
        return
    payload = {
        "username": "TD Version Watchdog",
        "content": (
            f"<@&{ROLE_ID}> 🚨 **Game Version Update Detected!**\n"
            f"🗺️ **Place:** `{place_name}` (`{place_id}`)\n"
            f"🔄 **Version:** `{old_ver}` ➔ `{new_ver}`\n"
            f"👤 **First detected by:** `{player_name}`"
        ),
        "allowed_mentions": {
            "roles": [ROLE_ID]
        }
    }
    try:
        requests.post(WEBHOOK_URL, json=payload, timeout=10)
    except Exception as e:
        print(f"Webhook ping error: {e}", flush=True)

def build_user_dashboard_embed(discord_user):
    discord_id_str = str(discord_user.id)
    with state_lock:
        state = load_state()
        user_info = state["users"].get(discord_id_str)
        linked_names = user_info.get("accounts", []) if user_info else []
        user_code = user_info.get("code", "Not generated") if user_info else "Not generated"
        all_accounts = state.get("accounts", {})

    if not linked_names:
        embed = discord.Embed(
            title="❌ No Linked Accounts Found",
            description=(
                "You don't have any Roblox accounts linked to your Discord profile yet.\n\n"
                "**How to link:**\n"
                "1️⃣ Click **🔗 Get Link Code** below.\n"
                "2️⃣ Paste your code into the **femboy script ;3** UI in Roblox and click **Link**.\n"
                "3️⃣ All accounts running in the same workspace will link automatically!"
            ),
            color=0xE74C3C
        )
        return embed

    now_ts = int(time.time())
    embed = discord.Embed(
        title=f"📊 {discord_user.display_name}'s Account Tracker",
        description=f"🔑 **Active Link Key:** ||`{user_code}`|| • **Total Accounts:** `{len(linked_names)}`",
        color=0x2B2D31
    )

    total_wins = 0
    total_losses = 0

    for acc_name in linked_names:
        info = all_accounts.get(acc_name)
        if not info:
            continue

        ts = info.get("timestamp", now_ts)
        age = now_ts - ts
        if age < 180:
            health_badge = "🟢 **Online**"
        elif age < 600:
            health_badge = "🟡 **Idle**"
        else:
            health_badge = "🔴 **Offline / Disconnected**"

        cur_place = info.get("place", "Lobby")
        prev_place = info.get("prev_place")
        ver = info.get("version", "v?")

        if prev_place and prev_place != cur_place:
            transition_str = f"{format_place_Emoji(prev_place)} ➔ {format_place_Emoji(cur_place)}"
        else:
            transition_str = f"{format_place_Emoji(cur_place)}"

        coins_str = format_currency_display(info.get("coins"), info.get("start_coins"))
        pumpkins_str = format_currency_display(info.get("pumpkins"), info.get("start_pumpkins"))

        wins = info.get("wins", 0)
        losses = info.get("losses", 0)
        total_wins += wins
        total_losses += losses

        last_event = info.get("last_event", "Joined")
        gold_in_match = info.get("match_gold")
        wave_in_match = info.get("match_wave")

        match_extra = ""
        if "match" in cur_place.lower() and (gold_in_match is not None or wave_in_match is not None):
            match_extra = f"⚔️ **Wave:** `{wave_in_match or 0}` | 💵 **Cash:** `{gold_in_match or 0}$`\n"

        field_value = (
            f"📡 **State:** {health_badge} (`{ver}`)\n"
            f"🔄 **Status:** {transition_str}\n"
            f"{match_extra}"
            f"🪙 **Coins:** {coins_str}\n"
            f"🎃 **Pumpkins:** {pumpkins_str}\n"
            f"🏆 **W/L:** `{wins}W` / `{losses}L` *(Last: {last_event})*\n"
            f"🕒 **Updated:** <t:{ts}:R>"
        )

        embed.add_field(
            name=f"👤 {acc_name}",
            value=field_value,
            inline=True
        )

    embed.set_footer(text=f"Session Totals: {total_wins} Wins | {total_losses} Losses • Click Refresh to update")
    return embed

class DashboardRefreshView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Refresh Status", style=discord.ButtonStyle.primary, emoji="🔄", custom_id="td_dash_refresh")
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = build_user_dashboard_embed(interaction.user)
        await interaction.response.edit_message(embed=embed, view=self)

class ControlPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="My Accounts", style=discord.ButtonStyle.success, emoji="📊", custom_id="td_panel_my_accounts")
    async def my_accounts_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = build_user_dashboard_embed(interaction.user)
        await interaction.response.send_message(embed=embed, view=DashboardRefreshView(), ephemeral=True)

    @discord.ui.button(label="Get Link Code", style=discord.ButtonStyle.secondary, emoji="🔗", custom_id="td_panel_get_code")
    async def get_code_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        code = get_or_create_link_code(str(interaction.user.id), force_new=False)
        embed = discord.Embed(
            title="🔗 Account Linking Instructions",
            description=(
                f"Your personal link code is:\n"
                f"## `{code}`\n\n"
                "**Steps to link your Roblox accounts:**\n"
                "1. Execute **femboy script ;3** in Roblox.\n"
                "2. Paste `{code}` into the **Link Code** box in the UI and press **Link**.\n"
                "3. Your account (and all alts sharing the same workspace) will immediately appear in **📊 My Accounts**!"
            ),
            color=0x5865F2
        )
        embed.set_footer(text="Do not share this code with anyone!")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Reset Code", style=discord.ButtonStyle.danger, emoji="🔄", custom_id="td_panel_reset_code")
    async def reset_code_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        new_code = get_or_create_link_code(str(interaction.user.id), force_new=True)
        embed = discord.Embed(
            title="🔄 Link Code Regenerated",
            description=(
                f"Your old code has been invalidated. Your new link code is:\n"
                f"## `{new_code}`\n\n"
                "Update this code in your Roblox script UI to continue syncing new accounts."
            ),
            color=0xF1C40F
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

@app.route("/", methods=["GET"])
def index():
    return jsonify({"status": "online", "service": "TD Bot & Monitor API"})

@app.route("/report", methods=["POST"])
def report():
    data = request.get_json(silent=True) or {}
    player = str(data.get("player", "Unknown")).strip()
    place_id = str(data.get("place_id", "")).strip()
    place_name = str(data.get("place_name", "Lobby")).strip()
    version = str(data.get("version", "")).strip()
    raw_coins = data.get("coins")
    raw_pumpkins = data.get("pumpkins")
    link_code = str(data.get("link_code", "")).strip().upper()
    event_type = str(data.get("event", "Sync")).strip()
    match_gold = data.get("match_gold")
    match_wave = data.get("match_wave")

    if not place_id or not player:
        return jsonify({"error": "missing fields"}), 400

    now_ts = int(time.time())
    version_changed = None

    with state_lock:
        state = load_state()

        if version:
            old_ver = state["versions"].get(place_id)
            if old_ver is None:
                state["versions"][place_id] = version
            elif old_ver != version:
                state["versions"][place_id] = version
                version_changed = (old_ver, version)

        acc_info = state["accounts"].get(player, {})

        old_place = acc_info.get("place")
        if old_place and old_place != place_name:
            acc_info["prev_place"] = old_place
        elif "prev_place" not in acc_info:
            acc_info["prev_place"] = None

        acc_info["place"] = place_name
        acc_info["version"] = version
        acc_info["timestamp"] = now_ts
        acc_info["last_event"] = event_type

        if match_gold is not None:
            acc_info["match_gold"] = match_gold
        if match_wave is not None:
            acc_info["match_wave"] = match_wave

        if event_type.upper() == "VICTORY":
            acc_info["wins"] = acc_info.get("wins", 0) + 1
        elif event_type.upper() == "GAME OVER":
            acc_info["losses"] = acc_info.get("losses", 0) + 1
        else:
            acc_info.setdefault("wins", 0)
            acc_info.setdefault("losses", 0)

        if is_valid_currency(raw_coins):
            acc_info["coins"] = str(raw_coins).strip()
            if not is_valid_currency(acc_info.get("start_coins")):
                acc_info["start_coins"] = str(raw_coins).strip()

        if is_valid_currency(raw_pumpkins):
            acc_info["pumpkins"] = str(raw_pumpkins).strip()
            if not is_valid_currency(acc_info.get("start_pumpkins")):
                acc_info["start_pumpkins"] = str(raw_pumpkins).strip()

        linked_discord_id = None
        if link_code and link_code in state["codes"]:
            linked_discord_id = state["codes"][link_code]
            acc_info["owner_id"] = linked_discord_id
            user_entry = state["users"].setdefault(linked_discord_id, {"code": link_code, "accounts": []})
            if player not in user_entry["accounts"]:
                user_entry["accounts"].append(player)

        state["accounts"][player] = acc_info
        save_state(state)

    if version_changed:
        ping_version_update(place_name, place_id, version_changed[0], version_changed[1], player)

    return jsonify({
        "status": "ok",
        "linked": bool(acc_info.get("owner_id")),
        "timestamp": now_ts
    })

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

def create_master_panel_embed():
    embed = discord.Embed(
        title="🌸 femboy script ;3 — Account Control Panel",
        description=(
            "Welcome to the live **Multi-Account Farm Tracker**!\n"
            "Link your Roblox accounts to monitor your farm progress in real time directly from Discord.\n\n"
            "✨ **Features:**\n"
            "• 🔄 **Live State Transitions:** `In Match ➔ Lobby`\n"
            "• 🪙 **Currency Tracker:** Live `Coins` & `Pumpkins` with session profit (`+Δ`)\n"
            "• ⚔️ **Match Telemetry:** Current Wave, Cash & Win/Loss counter\n"
            "• 🟢 **Disconnect Watchdog:** Instant online/offline status & `<t:ts:R>` timer\n\n"
            "👇 **Use the buttons below to manage and view your accounts:**"
        ),
        color=0xFF85B3
    )
    embed.set_footer(text="femboy script ;3 • Real-Time Telemetry System")
    return embed

@bot.event
async def on_ready():
    bot.add_view(ControlPanelView())
    bot.add_view(DashboardRefreshView())
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands.", flush=True)
    except Exception as e:
        print(f"Slash sync error: {e}", flush=True)
    print(f"Discord Bot logged in as {bot.user}", flush=True)

@bot.command(name="panel")
async def send_panel_cmd(ctx):
    embed = create_master_panel_embed()
    await ctx.send(embed=embed, view=ControlPanelView())

@bot.tree.command(name="panel", description="Send the TD Account Control Panel")
async def slash_panel(interaction: discord.Interaction):
    embed = create_master_panel_embed()
    await interaction.response.send_message(embed=embed, view=ControlPanelView())

def run_flask():
    print(f"Starting Flask API Server on port {PORT}...", flush=True)
    app.run(host="0.0.0.0", port=PORT, use_reloader=False)

if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    if BOT_TOKEN:
        bot.run(BOT_TOKEN)
    else:
        print("WARNING: BOT_TOKEN is not set in .env! Running Flask API only...", flush=True)
        while True:
            time.sleep(3600)
