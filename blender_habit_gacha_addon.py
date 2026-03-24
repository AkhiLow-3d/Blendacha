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
import random
import time
from pathlib import Path
from datetime import datetime, timedelta
from bpy.props import BoolProperty, IntProperty, StringProperty

# =========================================================
# Constants
# =========================================================

ADDON_ID = "habit_gacha"
PANEL_CATEGORY = "Habit Gacha"
DATA_VERSION = 1
GACHA_COST = 300
SESSION_REWARD_SECONDS = 15 * 60
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
    {"id": "badge_beginner", "name": "Beginner Badge", "rarity": "N", "type": "badge"},
    {"id": "sticker_blue_star", "name": "Blue Star Sticker", "rarity": "N", "type": "sticker"},
    {"id": "badge_daily_worker", "name": "Daily Worker", "rarity": "R", "type": "badge"},
    {"id": "sticker_soft_cloud", "name": "Soft Cloud Sticker", "rarity": "R", "type": "sticker"},
    {"id": "badge_persistent", "name": "Persistent Badge", "rarity": "SR", "type": "badge"},
    {"id": "sticker_gold_frame", "name": "Gold Frame Sticker", "rarity": "SR", "type": "sticker"},
    {"id": "badge_legend", "name": "Legend Badge", "rarity": "SSR", "type": "badge"},
]

# =========================================================
# Global runtime state
# =========================================================

_RUNTIME = {
    "session_start": 0.0,
    "timer_registered": False,
    "notifications": [],
    "data": None,
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

        if elapsed >= SESSION_REWARD_SECONDS and not has_claimed_today("session_15m"):
            grant_reward("session_15m")

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

        layout.template_list(
            "HG_UL_inventory_list",
            "",
            scene,
            "hg_inventory_items",
            scene,
            "hg_inventory_index",
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
        box.label(text=f"Debug mode: {'ON' if settings.get('debug_mode') else 'OFF'}")

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



def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    register_props()

    _RUNTIME["data"] = load_data()
    _RUNTIME["session_start"] = time.time()
    _RUNTIME["notifications"] = []

    register_timer()

    if bpy.context.scene:
        ensure_scene_props_defaults(bpy.context.scene)
        refresh_ui_collections(bpy.context.scene)

    print(f"[{ADDON_ID}] registered")



def unregister():
    unregister_timer()
    unregister_props()

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    print(f"[{ADDON_ID}] unregistered")


if __name__ == "__main__":
    register()
