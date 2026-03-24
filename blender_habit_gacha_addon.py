bl_info = {
    "name": "Habit Gacha",
    "author": "OpenAI",
    "version": (0, 1, 0),
    "blender": (4, 5, 3),
    "location": "View3D > Sidebar > Habit Gacha",
    "description": "Gamifies Blender usage with daily rewards, stones, and a simple gacha.",
    "category": "3D View",
}

import bpy
import json
import bpy.utils.previews
import random
import time
from pathlib import Path
import tempfile
from datetime import datetime, timedelta
from bpy.props import BoolProperty, IntProperty, StringProperty, FloatProperty

# =========================================================
# Constants
# =========================================================

ADDON_ID = "habit_gacha"
PANEL_CATEGORY = "Habit Gacha"
DATA_VERSION = 1
GACHA_COST = 300
SESSION_REWARD_SECONDS = 15 * 60
DEBUG_SESSION_REWARD_SECONDS = 10
TIMER_INTERVAL = 5.0
MAX_HISTORY = 50

RARITY_WEIGHTS = {
    "N": 70,
    "R": 25,
    "SR": 4,
    "SSR": 1,
}

DUPLICATE_STONE_REFUND = {
    "N": 20,
    "R": 50,
    "SR": 100,
    "SSR": 200,
}

REWARD_TABLE = {
    "daily_login": {
        "stones": 100,
        "once_per_day": True,
        "label": "ログイン報酬",
    },
    "session_15m": {
        "stones": 50,
        "once_per_day": True,
        "label": "15分継続報酬",
    },
    "work_start": {
        "stones": 20,
        "once_per_day": True,
        "label": "作業開始報酬",
    },
}

GACHA_TABLE = [
    {"id": "badge_beginner", "name": "Beginner Badge", "rarity": "N", "type": "badge", "image": "", "color": (0.35, 0.55, 1.0, 0.9)},
    {"id": "sticker_blue_star", "name": "Blue Star Sticker", "rarity": "N", "type": "sticker", "image": "", "color": (0.35, 0.75, 1.0, 0.9)},
    {"id": "badge_daily_worker", "name": "Daily Worker", "rarity": "R", "type": "badge", "image": "", "color": (0.75, 0.35, 1.0, 0.95)},
    {"id": "sticker_soft_cloud", "name": "Soft Cloud Sticker", "rarity": "R", "type": "sticker", "image": "", "color": (0.95, 0.55, 1.0, 0.95)},
    {"id": "badge_persistent", "name": "Persistent Badge", "rarity": "SR", "type": "badge", "image": "", "color": (1.0, 0.75, 0.25, 0.98)},
    {"id": "sticker_gold_frame", "name": "Gold Frame Sticker", "rarity": "SR", "type": "sticker", "image": "", "color": (1.0, 0.85, 0.3, 0.98)},
    {"id": "badge_legend", "name": "Legend Badge", "rarity": "SSR", "type": "badge", "image": "", "color": (1.0, 0.35, 0.35, 1.0)},
]

# =========================================================
# Global runtime state
# =========================================================

_RUNTIME = {
    "session_start": 0.0,
    "timer_registered": False,
    "notifications": [],
    "data": None,
    "popup_state": {
        "active": False,
        "title": "",
        "subtitle": "",
        "rarity": "",
        "expire_at": 0.0,
        "color": (0.3, 0.7, 1.0, 0.9),
        "image_path": "",
        "image_name": "",
    },
    "draw_handler": None,
    "preview_collection": None,
}

# =========================================================
# Data helpers
# =========================================================


def get_data_path() -> Path:
    scripts_dir = Path(bpy.utils.user_resource("SCRIPTS"))
    addon_dir = scripts_dir / "addons" / ADDON_ID
    addon_dir.mkdir(parents=True, exist_ok=True)
    return addon_dir / "habit_gacha_data.json"



def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")



def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")



def default_data() -> dict:
    return {
        "version": DATA_VERSION,
        "player": {
            "stones": 0,
            "total_earned": 0,
            "total_spent": 0,
            "login_streak": 0,
            "last_login_date": "",
        },
        "daily": {
            "date": today_str(),
            "claimed_rewards": [],
            "missions_completed": [],
            "all_completed": False,
        },
        "inventory": {
            "badges": [],
            "stickers": [],
        },
        "gacha": {
            "count_total": 0,
            "count_since_sr_or_higher": 0,
            "count_since_ssr": 0,
        },
        "history": [],
        "settings": {
            "debug_mode": False,
            "daily_bonus_claimed": False,
            "image_folder_path": ""
        },
    }



def load_data() -> dict:
    path = get_data_path()
    if not path.exists():
        data = default_data()
        save_data(data)
        return data

    try:
        with path.open("r", encoding="utf-8") as f:
            loaded = json.load(f)
    except Exception:
        loaded = default_data()
        save_data(loaded)
        return loaded

    data = default_data()
    deep_update(data, loaded)
    ensure_daily_reset(data)
    return data



def save_data(data: dict) -> None:
    path = get_data_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)



def deep_update(base: dict, incoming: dict) -> None:
    for key, value in incoming.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            deep_update(base[key], value)
        else:
            base[key] = value



def get_data() -> dict:
    if _RUNTIME["data"] is None:
        _RUNTIME["data"] = load_data()
    return _RUNTIME["data"]



def set_data(data: dict) -> None:
    _RUNTIME["data"] = data
    save_data(data)
    sync_scene_props_to_data()



def ensure_daily_reset(data: dict) -> None:
    today = today_str()
    if data["daily"]["date"] != today:
        data["daily"] = {
            "date": today,
            "claimed_rewards": [],
            "missions_completed": [],
            "all_completed": False,
        }
        data["settings"]["daily_bonus_claimed"] = False
        save_data(data)



def append_history(entry_type: str, entry_id: str, text: str) -> None:
    data = get_data()
    data["history"].insert(0, {
        "timestamp": now_iso(),
        "type": entry_type,
        "id": entry_id,
        "text": text,
    })
    data["history"] = data["history"][:MAX_HISTORY]
    save_data(data)



def add_notification(text: str) -> None:
    _RUNTIME["notifications"].insert(0, text)
    _RUNTIME["notifications"] = _RUNTIME["notifications"][:10]
    sync_scene_props_to_data()


def show_popup(message_lines: list[str], title: str = "通知", icon: str = 'INFO') -> None:
    def draw(self, context):
        for line in message_lines:
            self.layout.label(text=line)

    wm = getattr(bpy.context, "window_manager", None)
    if wm is not None:
        try:
            wm.popup_menu(draw, title=title, icon=icon)
        except Exception:
            pass


def get_item_definition(item_id: str) -> dict | None:
    for item in GACHA_TABLE:
        if item["id"] == item_id:
            return item
    return None


def get_preview_icon_id(image_path: str, key: str) -> int:
    if not image_path:
        return 0
    pcoll = _RUNTIME.get("preview_collection")
    if pcoll is None:
        return 0
    try:
        if key in pcoll:
            preview = pcoll[key]
            if getattr(preview, "icon_id", 0):
                return preview.icon_id
        preview = pcoll.load(key, image_path, 'IMAGE')
        return preview.icon_id
    except Exception:
        return 0


def _ensure_demo_image(item: dict) -> str:
    # 0) user-configured image folder path
    data = get_data()
    image_folder_setting = data.get("settings", {}).get("image_folder_path", "") or ""
    if image_folder_setting:
        configured_dir = Path(image_folder_setting)
        configured_path = configured_dir / f"{item['id']}.png"
        if configured_path.exists():
            return str(configured_path)

    # 1) explicit image path on item
    image_path = item.get("image", "") or ""
    if image_path:
        explicit = Path(image_path)
        if not explicit.is_absolute():
            explicit = Path(__file__).resolve().parent / explicit
        if explicit.exists():
            return str(explicit)

    # 2) auto lookup by item id next to addon file
    addon_dir = Path(__file__).resolve().parent
    auto_path = addon_dir / "images" / f"{item['id']}.png"
    if auto_path.exists():
        return str(auto_path)

    # 3) fallback demo image generation
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return ""

    cache_dir = Path(tempfile.gettempdir()) / ADDON_ID
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path = cache_dir / f"{item['id']}.png"
    if out_path.exists():
        return str(out_path)

    size = 256
    rgba = item.get("color", (0.5, 0.5, 0.5, 1.0))
    color = tuple(int(max(0.0, min(1.0, c)) * 255) for c in rgba[:3])
    img = Image.new("RGBA", (size, size), color + (255,))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((12, 12, size - 12, size - 12), radius=24, outline=(255, 255, 255, 220), width=4)
    draw.text((24, 24), item.get("rarity", "?"), fill=(255, 255, 255, 255))
    draw.text((24, 72), item.get("name", "ITEM")[:18], fill=(255, 255, 255, 255))
    img.save(out_path)
    return str(out_path)

    size = 256
    rgba = item.get("color", (0.5, 0.5, 0.5, 1.0))
    color = tuple(int(max(0.0, min(1.0, c)) * 255) for c in rgba[:3])
    img = Image.new("RGBA", (size, size), color + (255,))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((12, 12, size - 12, size - 12), radius=24, outline=(255, 255, 255, 220), width=4)
    draw.text((24, 24), item.get("rarity", "?"), fill=(255, 255, 255, 255))
    draw.text((24, 72), item.get("name", "ITEM")[:18], fill=(255, 255, 255, 255))
    img.save(out_path)
    return str(out_path)

    size = 256
    rgba = item.get("color", (0.5, 0.5, 0.5, 1.0))
    color = tuple(int(max(0.0, min(1.0, c)) * 255) for c in rgba[:3])
    img = Image.new("RGBA", (size, size), color + (255,))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((12, 12, size - 12, size - 12), radius=24, outline=(255, 255, 255, 220), width=4)
    draw.text((24, 24), item.get("rarity", "?"), fill=(255, 255, 255, 255))
    draw.text((24, 72), item.get("name", "ITEM")[:18], fill=(255, 255, 255, 255))
    img.save(out_path)
    return str(out_path)


def show_image_popup(item: dict, is_new: bool, refund: int = 0) -> None:
    image_path = _ensure_demo_image(item)
    popup = _RUNTIME["popup_state"]
    popup["active"] = True
    popup["title"] = item.get("name", "")
    popup["subtitle"] = "NEW" if is_new else (f"重複 返還 +{refund}石" if refund > 0 else "重複")
    popup["rarity"] = item.get("rarity", "")
    popup["expire_at"] = time.time() + 2.5
    popup["color"] = item.get("color", (0.3, 0.7, 1.0, 0.9))
    popup["image_path"] = image_path
    popup["image_name"] = f"{ADDON_ID}_{item['id']}"

    if image_path:
        try:
            img_name = popup["image_name"]
            if img_name in bpy.data.images:
                img = bpy.data.images[img_name]
                img.reload()
            else:
                img = bpy.data.images.load(image_path)
                img.name = img_name
        except Exception:
            popup["image_path"] = ""

    sync_scene_props_to_data()



def has_claimed_today(event_id: str) -> bool:
    data = get_data()
    ensure_daily_reset(data)
    return event_id in data["daily"]["claimed_rewards"]



def mark_claimed_today(event_id: str) -> None:
    data = get_data()
    if event_id not in data["daily"]["claimed_rewards"]:
        data["daily"]["claimed_rewards"].append(event_id)
        save_data(data)



def add_stones(amount: int) -> None:
    data = get_data()
    data["player"]["stones"] += amount
    data["player"]["total_earned"] += max(0, amount)
    save_data(data)
    sync_scene_props_to_data()



def spend_stones(amount: int) -> bool:
    data = get_data()
    if data["player"]["stones"] < amount:
        return False
    data["player"]["stones"] -= amount
    data["player"]["total_spent"] += amount
    save_data(data)
    sync_scene_props_to_data()
    return True



def get_login_streak_bonus(streak: int) -> int:
    if streak <= 1:
        return 0
    if streak == 2:
        return 10
    if streak == 3:
        return 20
    if streak == 4:
        return 30
    if streak == 5:
        return 40
    if streak == 6:
        return 50
    if streak >= 7:
        return 100
    return 0



def update_login_streak() -> int:
    data = get_data()
    player = data["player"]
    today = today_str()
    last_login = player["last_login_date"]

    if not last_login:
        player["login_streak"] = 1
    else:
        try:
            last_dt = datetime.strptime(last_login, "%Y-%m-%d")
            today_dt = datetime.strptime(today, "%Y-%m-%d")
            delta_days = (today_dt - last_dt).days
        except ValueError:
            delta_days = 999

        if delta_days == 0:
            pass
        elif delta_days == 1:
            player["login_streak"] += 1
        else:
            player["login_streak"] = 1

    player["last_login_date"] = today
    save_data(data)
    sync_scene_props_to_data()
    return player["login_streak"]



def grant_reward(event_id: str) -> tuple[bool, str]:
    data = get_data()
    ensure_daily_reset(data)

    if event_id not in REWARD_TABLE:
        return False, f"未定義イベント: {event_id}"

    event = REWARD_TABLE[event_id]
    if event.get("once_per_day", False) and has_claimed_today(event_id):
        return False, f"{event['label']}は本日受取済みです"

    amount = int(event["stones"])

    if event_id == "daily_login":
        streak = update_login_streak()
        bonus = get_login_streak_bonus(streak)
        amount += bonus
        msg = f"{event['label']} +{amount}石（連続{streak}日）"
    else:
        msg = f"{event['label']} +{amount}石"

    add_stones(amount)
    mark_claimed_today(event_id)
    append_history("reward", event_id, msg)
    add_notification(msg)
    sync_scene_props_to_data()
    check_daily_complete_bonus()
    return True, msg



def roll_rarity() -> str:
    rarities = list(RARITY_WEIGHTS.keys())
    weights = list(RARITY_WEIGHTS.values())
    return random.choices(rarities, weights=weights, k=1)[0]



def pick_item_by_rarity(rarity: str) -> dict:
    pool = [item for item in GACHA_TABLE if item["rarity"] == rarity]
    if not pool:
        pool = GACHA_TABLE
    return random.choice(pool)



def inventory_contains(item: dict) -> bool:
    data = get_data()
    key = "badges" if item["type"] == "badge" else "stickers"
    return item["id"] in data["inventory"][key]



def add_item_to_inventory(item: dict) -> None:
    data = get_data()
    key = "badges" if item["type"] == "badge" else "stickers"
    if item["id"] not in data["inventory"][key]:
        data["inventory"][key].append(item["id"])
        save_data(data)
    sync_scene_props_to_data()



def update_gacha_counters(rarity: str) -> None:
    data = get_data()
    gacha = data["gacha"]
    gacha["count_total"] += 1

    if rarity in {"SR", "SSR"}:
        gacha["count_since_sr_or_higher"] = 0
    else:
        gacha["count_since_sr_or_higher"] += 1

    if rarity == "SSR":
        gacha["count_since_ssr"] = 0
    else:
        gacha["count_since_ssr"] += 1

    save_data(data)
    sync_scene_props_to_data()



def draw_gacha_once() -> tuple[bool, str, dict | None]:
    if not spend_stones(GACHA_COST):
        return False, f"石が足りません（必要: {GACHA_COST}）", None

    rarity = roll_rarity()
    item = pick_item_by_rarity(rarity)
    update_gacha_counters(rarity)

    if inventory_contains(item):
        refund = DUPLICATE_STONE_REFUND.get(rarity, 0)
        if refund > 0:
            add_stones(refund)
        msg = f"{rarity} {item['name']}（重複） 返還 +{refund}石"
        append_history("gacha", item["id"], msg)
        add_notification(msg)
        show_popup([
            f"{rarity} 獲得",
            item['name'],
            "重複",
            f"返還 +{refund}石",
        ], title="ガチャ結果", icon='INFO')
        show_image_popup(item, is_new=False, refund=refund)
        sync_scene_props_to_data()
        return True, msg, item

    add_item_to_inventory(item)
    msg = f"{rarity} {item['name']} を獲得！"
    append_history("gacha", item["id"], msg)
    add_notification(msg)
    show_popup([
        f"{rarity} 獲得！",
        item['name'],
        "新規獲得",
    ], title="ガチャ結果", icon='CHECKMARK')
    show_image_popup(item, is_new=True)
    sync_scene_props_to_data()
    return True, msg, item

    add_item_to_inventory(item)
    msg = f"{rarity} {item['name']} を獲得！"
    append_history("gacha", item["id"], msg)
    add_notification(msg)
    show_popup([
        f"{rarity} 獲得！",
        item['name'],
        "新規獲得",
    ], title="ガチャ結果", icon='CHECKMARK')
    sync_scene_props_to_data()
    return True, msg, item

    add_item_to_inventory(item)
    msg = f"{rarity} {item['name']} を獲得！"
    append_history("gacha", item["id"], msg)
    add_notification(msg)
    sync_scene_props_to_data()
    return True, msg, item



def get_session_elapsed_seconds() -> int:
    if _RUNTIME["session_start"] <= 0:
        return 0
    return int(time.time() - _RUNTIME["session_start"])



def format_seconds_to_mmss(seconds: int) -> str:
    minutes = seconds // 60
    remain = seconds % 60
    return f"{minutes:02d}:{remain:02d}"


def get_required_session_seconds() -> int:
    data = get_data()
    return DEBUG_SESSION_REWARD_SECONDS if data["settings"].get("debug_mode", False) else SESSION_REWARD_SECONDS


def check_daily_complete_bonus() -> None:
    data = get_data()
    ensure_daily_reset(data)
    required = {"daily_login", "work_start", "session_15m"}
    claimed = set(data["daily"].get("claimed_rewards", []))
    if required.issubset(claimed) and not data["settings"].get("daily_bonus_claimed", False):
        bonus = 50
        add_stones(bonus)
        data["daily"]["all_completed"] = True
        data["settings"]["daily_bonus_claimed"] = True
        save_data(data)
        msg = f"デイリー全達成ボーナス +{bonus}石"
        append_history("reward", "daily_all_complete", msg)
        add_notification(msg)
        show_popup([
            "デイリー全達成！",
            f"ボーナス +{bonus}石",
        ], title="デイリーボーナス", icon='CHECKMARK')
        sync_scene_props_to_data()

# =========================================================
# Scene properties sync
# =========================================================


def ensure_scene_props_defaults(scene: bpy.types.Scene) -> None:
    # NOTE: Do NOT write to Scene properties from draw() context.
    # This function is kept for compatibility but does not mutate data.
    return



def sync_scene_props_to_data() -> None:
    scene = getattr(bpy.context, "scene", None)
    if scene is None:
        return
    data = get_data()
    scene.hg_stones = data["player"]["stones"]
    scene.hg_login_streak = data["player"]["login_streak"]
    scene.hg_last_message = _RUNTIME["notifications"][0] if _RUNTIME["notifications"] else ""
    scene.hg_elapsed_label = format_seconds_to_mmss(get_session_elapsed_seconds())
    scene.hg_image_folder_input = data.get("settings", {}).get("image_folder_path", "") or ""

# =========================================================
# Timer
# =========================================================


def timer_tick():
    if not _RUNTIME["timer_registered"]:
        return None

    try:
        data = get_data()
        ensure_daily_reset(data)

        elapsed = get_session_elapsed_seconds()
        sync_scene_props_to_data()

        required_seconds = get_required_session_seconds()
        if elapsed >= required_seconds and not has_claimed_today("session_15m"):
            grant_reward("session_15m")

        popup = _RUNTIME["popup_state"]
        if popup["active"] and time.time() >= popup["expire_at"]:
            popup["active"] = False
            popup["image_path"] = ""

    except Exception as exc:
        print(f"[{ADDON_ID}] Timer error: {exc}")

    return TIMER_INTERVAL



def register_timer() -> None:
    if _RUNTIME["timer_registered"]:
        return
    _RUNTIME["session_start"] = time.time()
    _RUNTIME["timer_registered"] = True
    if not bpy.app.timers.is_registered(timer_tick):
        bpy.app.timers.register(timer_tick, first_interval=TIMER_INTERVAL)



def unregister_timer() -> None:
    _RUNTIME["timer_registered"] = False
    if bpy.app.timers.is_registered(timer_tick):
        bpy.app.timers.unregister(timer_tick)

# =========================================================
# UI Lists
# =========================================================


class HG_UL_HistoryList(bpy.types.UIList):
    bl_idname = "HG_UL_history_list"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.label(text=item.timestamp, icon='TIME')
            row.label(text=item.text)
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(text="")


class HG_UL_InventoryList(bpy.types.UIList):
    bl_idname = "HG_UL_inventory_list"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.label(text=item.rarity)
            row.label(text=item.item_type)
            row.label(text=item.name)
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(text="")

# =========================================================
# Property groups
# =========================================================


class HG_HistoryItem(bpy.types.PropertyGroup):
    timestamp: StringProperty(name="Timestamp")
    text: StringProperty(name="Text")


class HG_InventoryItem(bpy.types.PropertyGroup):
    item_id: StringProperty(name="Item ID")
    name: StringProperty(name="Name")
    rarity: StringProperty(name="Rarity")
    item_type: StringProperty(name="Type")
    image_path: StringProperty(name="Image Path")

# =========================================================
# Collection refresh
# =========================================================


def refresh_ui_collections(scene: bpy.types.Scene | None = None) -> None:
    if scene is None:
        scene = getattr(bpy.context, "scene", None)
    if scene is None:
        return

    data = get_data()

    scene.hg_history_items.clear()
    for entry in data["history"][:20]:
        item = scene.hg_history_items.add()
        item.timestamp = entry.get("timestamp", "")
        item.text = entry.get("text", "")

    scene.hg_inventory_items.clear()
    owned_ids = set(data["inventory"]["badges"] + data["inventory"]["stickers"])
    for definition in GACHA_TABLE:
        if definition["id"] in owned_ids:
            item = scene.hg_inventory_items.add()
            item.item_id = definition["id"]
            item.name = definition["name"]
            item.rarity = definition["rarity"]
            item.item_type = definition["type"]
            item.image_path = _ensure_demo_image(definition)

    sync_scene_props_to_data()

# =========================================================
# Operators
# =========================================================


class HG_OT_ClaimLoginReward(bpy.types.Operator):
    bl_idname = "habit.claim_login_reward"
    bl_label = "ログイン報酬受取"
    bl_description = "本日のログイン報酬を受け取ります"

    def execute(self, context):
        ok, msg = grant_reward("daily_login")
        refresh_ui_collections(context.scene)
        self.report({'INFO'} if ok else {'WARNING'}, msg)
        return {'FINISHED'}


class HG_OT_StartWork(bpy.types.Operator):
    bl_idname = "habit.start_work"
    bl_label = "作業開始"
    bl_description = "作業開始報酬を受け取り、今日の作業を始めます"

    def execute(self, context):
        ok, msg = grant_reward("work_start")
        refresh_ui_collections(context.scene)
        self.report({'INFO'} if ok else {'WARNING'}, msg)
        return {'FINISHED'}


class HG_OT_DrawGacha(bpy.types.Operator):
    bl_idname = "habit.draw_gacha"
    bl_label = "ガチャ1回"
    bl_description = f"{GACHA_COST}石でガチャを1回引きます"

    def execute(self, context):
        ok, msg, item = draw_gacha_once()
        refresh_ui_collections(context.scene)
        self.report({'INFO'} if ok else {'WARNING'}, msg)
        return {'FINISHED'}


class HG_OT_DebugAddStones(bpy.types.Operator):
    bl_idname = "habit.debug_add_stones"
    bl_label = "デバッグ: 石追加"
    bl_description = "デバッグ用に石を追加します"

    amount: IntProperty(name="Amount", default=500, min=1, max=999999)

    def execute(self, context):
        add_stones(int(self.amount))
        msg = f"デバッグで +{self.amount}石"
        append_history("system", "debug_add_stones", msg)
        add_notification(msg)
        refresh_ui_collections(context.scene)
        self.report({'INFO'}, msg)
        return {'FINISHED'}


class HG_OT_ToggleDebugMode(bpy.types.Operator):
    bl_idname = "habit.toggle_debug_mode"
    bl_label = "デバッグ時短切替"
    bl_description = "15分継続報酬を短時間テスト用に切り替えます"

    def execute(self, context):
        data = get_data()
        current = data["settings"].get("debug_mode", False)
        data["settings"]["debug_mode"] = not current
        save_data(data)
        state = "ON" if data["settings"]["debug_mode"] else "OFF"
        msg = f"デバッグ時短: {state}"
        append_history("system", "toggle_debug_mode", msg)
        add_notification(msg)
        refresh_ui_collections(context.scene)
        self.report({'INFO'}, msg)
        return {'FINISHED'}


class HG_OT_SetImageFolderPath(bpy.types.Operator):
    bl_idname = "habit.set_image_folder_path"
    bl_label = "画像フォルダ設定"
    bl_description = "画像フォルダの絶対パスを保存します"

    def execute(self, context):
        folder_path = (context.scene.hg_image_folder_input or "").strip()
        data = get_data()
        data["settings"]["image_folder_path"] = folder_path
        save_data(data)
        refresh_ui_collections(context.scene)
        msg = f"画像フォルダを設定しました: {folder_path if folder_path else '未設定'}"
        append_history("system", "set_image_folder_path", msg)
        add_notification(msg)
        self.report({'INFO'}, msg)
        return {'FINISHED'}


class HG_OT_BrowseImageFolderPath(bpy.types.Operator):
    bl_idname = "habit.browse_image_folder_path"
    bl_label = "画像フォルダ参照"
    bl_description = "画像フォルダを選択して入力欄に反映します"

    directory: StringProperty(name="Directory", default="", subtype='DIR_PATH')

    def invoke(self, context, event):
        self.directory = context.scene.hg_image_folder_input or ""
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        context.scene.hg_image_folder_input = self.directory
        self.report({'INFO'}, f"選択中: {self.directory}")
        return {'FINISHED'}


class HG_OT_ClearImageFolderPath(bpy.types.Operator):
    bl_idname = "habit.clear_image_folder_path"
    bl_label = "画像フォルダ解除"
    bl_description = "設定済みの画像フォルダパスを解除します"

    def execute(self, context):
        data = get_data()
        data["settings"]["image_folder_path"] = ""
        save_data(data)
        refresh_ui_collections(context.scene)
        msg = "画像フォルダ設定を解除しました"
        append_history("system", "clear_image_folder_path", msg)
        add_notification(msg)
        self.report({'INFO'}, msg)
        return {'FINISHED'}


class HG_OT_ReloadData(bpy.types.Operator):
    bl_idname = "habit.reload_data"
    bl_label = "データ再読込"
    bl_description = "JSONデータを再読み込みします"

    def execute(self, context):
        _RUNTIME["data"] = load_data()
        refresh_ui_collections(context.scene)
        self.report({'INFO'}, "データを再読み込みしました")
        return {'FINISHED'}


class HG_OT_ResetSave(bpy.types.Operator):
    bl_idname = "habit.reset_save"
    bl_label = "セーブ初期化"
    bl_description = "保存データを初期化します"

    confirm: BoolProperty(name="Confirm", default=False)

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        _RUNTIME["data"] = default_data()
        save_data(_RUNTIME["data"])
        _RUNTIME["notifications"].clear()
        _RUNTIME["session_start"] = time.time()
        refresh_ui_collections(context.scene)
        self.report({'INFO'}, "保存データを初期化しました")
        return {'FINISHED'}

# =========================================================
# Panels
# =========================================================


class HG_PT_MainPanel(bpy.types.Panel):
    bl_label = "Habit Gacha"
    bl_idname = "HG_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = PANEL_CATEGORY

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        data = get_data()
        # ensure_scene_props_defaults(scene)  # disabled (write in draw not allowed)

        box = layout.box()
        box.label(text="ステータス", icon='FUND')
        col = box.column(align=True)
        col.label(text=f"所持石: {scene.hg_stones}")
        col.label(text=f"連続ログイン: {scene.hg_login_streak}日")
        col.label(text=f"起動経過: {scene.hg_elapsed_label}")

        box = layout.box()
        box.label(text="今日の報酬", icon='CHECKMARK')
        col = box.column(align=True)
        col.label(text=f"ログイン報酬: {'受取済み' if has_claimed_today('daily_login') else '未受取'}")
        col.label(text=f"作業開始報酬: {'受取済み' if has_claimed_today('work_start') else '未受取'}")
        col.label(text=f"15分継続報酬: {'受取済み' if has_claimed_today('session_15m') else '未受取'}")
        daily_complete = data["daily"].get("all_completed", False)
        col.label(text=f"全達成ボーナス: {'受取済み' if daily_complete else '未達成'}")

        row = layout.row(align=True)
        row.operator("habit.claim_login_reward", icon='IMPORT')
        row.operator("habit.start_work", icon='PLAY')

        layout.separator()

        box = layout.box()
        box.label(text="ガチャ", icon='EVENT_A')
        col = box.column(align=True)
        col.label(text=f"1回 {GACHA_COST}石")
        col.operator("habit.draw_gacha", icon='FILE_REFRESH')

        layout.separator()

        box = layout.box()
        box.label(text="最新通知", icon='INFO')
        if scene.hg_last_message:
            box.label(text=scene.hg_last_message)
        else:
            box.label(text="まだ通知はありません")


class HG_PT_CollectionPanel(bpy.types.Panel):
    bl_label = "Collection"
    bl_idname = "HG_PT_collection_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = PANEL_CATEGORY
    bl_parent_id = "HG_PT_main_panel"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        data = get_data()

        badges = data["inventory"]["badges"]
        stickers = data["inventory"]["stickers"]

        row = layout.row()
        row.label(text=f"バッジ: {len(badges)}")
        row.label(text=f"ステッカー: {len(stickers)}")

        if 0 <= scene.hg_inventory_index < len(scene.hg_inventory_items):
            selected = scene.hg_inventory_items[scene.hg_inventory_index]
            box = layout.box()
            box.label(text=f"{selected.rarity} / {selected.item_type}")
            box.label(text=selected.name)
            if selected.image_path:
                icon_id = get_preview_icon_id(selected.image_path, selected.item_id)
                if icon_id:
                    box.template_icon(icon_value=icon_id, scale=8.0)
                    box.label(text=selected.image_path)
                else:
                    box.label(text="画像プレビュー読み込み失敗")
                    box.label(text=selected.image_path)

        layout.template_list(
            "HG_UL_inventory_list",
            "",
            scene,
            "hg_inventory_items",
            scene,
            "hg_inventory_index",
        "hg_image_folder_input",
            rows=8,
        )


class HG_PT_LogPanel(bpy.types.Panel):
    bl_label = "Log"
    bl_idname = "HG_PT_log_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = PANEL_CATEGORY
    bl_parent_id = "HG_PT_main_panel"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.template_list(
            "HG_UL_history_list",
            "",
            scene,
            "hg_history_items",
            scene,
            "hg_history_index",
            rows=10,
        )


class HG_PT_SettingsPanel(bpy.types.Panel):
    bl_label = "Settings"
    bl_idname = "HG_PT_settings_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = PANEL_CATEGORY
    bl_parent_id = "HG_PT_main_panel"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        data = get_data()
        settings = data["settings"]

        box = layout.box()
        box.label(text="デバッグ", icon='TOOL_SETTINGS')
        row = box.row(align=True)
        op = row.operator("habit.debug_add_stones", icon='ADD')
        op.amount = 500
        row = box.row(align=True)
        row.operator("habit.toggle_debug_mode", icon='RECOVER_LAST')
        box.label(text=f"Debug mode: {'ON' if settings.get('debug_mode') else 'OFF'}")
        seconds = DEBUG_SESSION_REWARD_SECONDS if settings.get('debug_mode') else SESSION_REWARD_SECONDS
        box.label(text=f"15分報酬条件: {seconds}秒")

        box = layout.box()
        box.label(text="画像フォルダ", icon='FILE_FOLDER')
        image_folder = settings.get('image_folder_path', '')
        box.label(text=f"保存済み: {image_folder if image_folder else '未設定'}")
        box.prop(context.scene, "hg_image_folder_input", text="入力")
        row = box.row(align=True)
        row.operator("habit.browse_image_folder_path", icon='FILE_FOLDER', text='参照')
        row.operator("habit.set_image_folder_path", icon='CHECKMARK', text='保存')
        row.operator("habit.clear_image_folder_path", icon='X', text='解除')

        box = layout.box()
        box.label(text="保存データ", icon='FILE_TICK')
        box.operator("habit.reload_data", icon='FILE_REFRESH')
        box.operator("habit.reset_save", icon='TRASH')

# =========================================================
# Register / unregister
# =========================================================


classes = (
    HG_HistoryItem,
    HG_InventoryItem,
    HG_UL_HistoryList,
    HG_UL_InventoryList,
    HG_OT_ClaimLoginReward,
    HG_OT_StartWork,
    HG_OT_DrawGacha,
    HG_OT_DebugAddStones,
    HG_OT_ToggleDebugMode,
    HG_OT_SetImageFolderPath,
    HG_OT_BrowseImageFolderPath,
    HG_OT_ClearImageFolderPath,
    HG_OT_ReloadData,
    HG_OT_ResetSave,
    HG_PT_MainPanel,
    HG_PT_CollectionPanel,
    HG_PT_LogPanel,
    HG_PT_SettingsPanel,
)



def register_props():
    bpy.types.Scene.hg_stones = IntProperty(name="Stones", default=0)
    bpy.types.Scene.hg_login_streak = IntProperty(name="Login Streak", default=0)
    bpy.types.Scene.hg_last_message = StringProperty(name="Last Message", default="")
    bpy.types.Scene.hg_elapsed_label = StringProperty(name="Elapsed", default="00:00")
    bpy.types.Scene.hg_history_items = bpy.props.CollectionProperty(type=HG_HistoryItem)
    bpy.types.Scene.hg_history_index = IntProperty(default=0)
    bpy.types.Scene.hg_inventory_items = bpy.props.CollectionProperty(type=HG_InventoryItem)
    bpy.types.Scene.hg_inventory_index = IntProperty(default=0)
    bpy.types.Scene.hg_image_folder_input = StringProperty(name="Image Folder Input", default="", subtype='DIR_PATH')



def unregister_props():
    props = [
        "hg_stones",
        "hg_login_streak",
        "hg_last_message",
        "hg_elapsed_label",
        "hg_history_items",
        "hg_history_index",
        "hg_inventory_items",
        "hg_inventory_index",
    ]
    for prop in props:
        if hasattr(bpy.types.Scene, prop):
            delattr(bpy.types.Scene, prop)



def register_popup_draw_handler() -> None:
    if _RUNTIME["draw_handler"] is not None:
        return

    def _draw_popup_overlay():
        popup = _RUNTIME["popup_state"]
        if not popup.get("active"):
            return

        try:
            import blf
            from gpu_extras.batch import batch_for_shader
            import gpu
        except Exception:
            return

        region = getattr(bpy.context, "region", None)
        if region is None:
            return

        width = region.width
        height = region.height
        x = width - 300
        y = height - 170
        w = 260
        h = 120
        color = popup.get("color", (0.3, 0.7, 1.0, 0.9))

        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        vertices = ((x, y), (x + w, y), (x + w, y + h), (x, y + h))
        batch = batch_for_shader(shader, 'TRI_FAN', {"pos": vertices})
        gpu.state.blend_set('ALPHA')
        shader.bind()
        shader.uniform_float("color", (0.05, 0.05, 0.08, 0.82))
        batch.draw(shader)

        border = batch_for_shader(shader, 'LINE_LOOP', {"pos": vertices})
        shader.uniform_float("color", color)
        border.draw(shader)

        font_id = 0
        blf.position(font_id, x + 16, y + h - 28, 0)
        blf.size(font_id, 18.0)
        blf.color(font_id, color[0], color[1], color[2], 1.0)
        blf.draw(font_id, popup.get("rarity", ""))

        blf.position(font_id, x + 16, y + h - 54, 0)
        blf.size(font_id, 16.0)
        blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
        blf.draw(font_id, popup.get("title", ""))

        blf.position(font_id, x + 16, y + h - 80, 0)
        blf.size(font_id, 13.0)
        blf.color(font_id, 0.9, 0.9, 0.9, 1.0)
        blf.draw(font_id, popup.get("subtitle", ""))

    _RUNTIME["draw_handler"] = bpy.types.SpaceView3D.draw_handler_add(
        _draw_popup_overlay, (), 'WINDOW', 'POST_PIXEL'
    )


def unregister_popup_draw_handler() -> None:
    if _RUNTIME["draw_handler"] is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_RUNTIME["draw_handler"], 'WINDOW')
        except Exception:
            pass
        _RUNTIME["draw_handler"] = None


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    register_props()

    _RUNTIME["preview_collection"] = bpy.utils.previews.new()
    _RUNTIME["data"] = load_data()
    _RUNTIME["session_start"] = time.time()
    _RUNTIME["notifications"] = []

    register_timer()
    register_popup_draw_handler()

    if bpy.context.scene:
        refresh_ui_collections(bpy.context.scene)

    print(f"[{ADDON_ID}] registered")



def unregister():
    unregister_timer()
    unregister_popup_draw_handler()
    if _RUNTIME.get("preview_collection") is not None:
        try:
            bpy.utils.previews.remove(_RUNTIME["preview_collection"])
        except Exception:
            pass
        _RUNTIME["preview_collection"] = None
    unregister_props()

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    print(f"[{ADDON_ID}] unregistered")


if __name__ == "__main__":
    register()
