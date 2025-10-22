  # -*- coding: utf-8 -*-
"""
ADVANCED Telegram Broadcast Bot v2.0 (සිංහල Comments)
- python-telegram-bot v20+ සඳහා සම්පූර්ණයෙන්ම යාවත්කාලීන කර ඇත
- සියලුම කේතය එකම ගොනුවක.

--- NEW FEATURES v2.0 (අලුත් විශේෂාංග) ---
1.  Button Confirmation (බොත්තම් මගින් තහවුරු කිරීම):
    - Admin දැන් 'YES'/'NO' ලෙස ටයිප් කිරීම වෙනුවට, බොත්තම් (Buttons) click කළ යුතුය.
2.  Cancel Schedules (`/remshed`):
    - Schedule කර ඇති සියලුම (pending) broadcasts අවලංගු කිරීමට අලුත් command එකක්.

--- ADVANCED FEATURES (පැරණි දියුණු විශේෂාංග) ---
1.  Multi-Line Buttons (බහු-පේළි බොත්තම්)
2.  Smart Send (ස්වයංක්‍රීය Forward/Copy)
3.  Scheduled Broadcasts (/schedule)
4.  Broadcast Throttling (විකාශන වේගය පාලනය)
5.  Updated /vip Menu & Startup Notification
"""

import logging
import firebase_admin
import asyncio
import re
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    CallbackQueryHandler # බොත්තම් සඳහා අලුතෙන් import කරන ලදී
)

# --- START OF CONFIGURATION (සැකසුම්) ---
TELEGRAM_BOT_TOKEN = "8419617505:AAFwnP-m7fbhbcUYFKm85xQmz0FLsyupZbE"
ADMIN_USER_ID = 6687619682
TARGET_GROUP_ID = -1003074965096
# --- END OF CONFIGURATION ---

# --- ADVANCED CONFIG (උසස් සැකසුම්) ---
BROADCAST_RATE_LIMIT = 25 # තත්පරයකට යවන පණිවිඩ ගණන

# ලොග් සැකසීම (Logging)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Firebase ආරම්භ කිරීම (Initialize Firebase)
try:
    cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    logger.info("Firebase සාර්ථකව සම්බන්ධ විය!")
except Exception as e:
    logger.error(f"Firebase සම්බන්ධ වීමේ දෝෂයක්: {e}")
    exit()

# --- HELPER FUNCTIONS (උපකාරක ශ්‍රිත) ---

async def check_group_membership(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> dict:
    """පරිශීලකයා group එකේ සාමාජිකයෙක්දැයි පරීක්ෂා කරයි."""
    try:
        member = await context.bot.get_chat_member(chat_id=TARGET_GROUP_ID, user_id=user_id)
        if member.status in ['member', 'administrator', 'creator', 'restricted']:
            return {"is_member": True, "status": member.status}
        else:
            return {"is_member": False, "status": member.status}
    except (BadRequest, Forbidden) as e:
        logger.error(f"සාමාජිකත්වය පරීක්ෂා කිරීමේ දෝෂයක් (ID: {user_id}): {e}")
        return {"is_member": False, "status": "error", "error_message": str(e)}
    except Exception as e:
        logger.error(f"සාමාන්‍ය දෝෂයක් (සාමාජිකත්වය පරීක්ෂා කිරීම): {e}")
        return {"is_member": False, "status": "error", "error_message": str(e)}

async def notify_admin_on_startup(app: Application) -> None:
    """Bot එක ඔන් වූ විට Admin ට DM එකක් යවයි."""
    try:
        await app.bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=f"🤖 *Bot is now ONLINE! (Advanced v2.0)*\n\n"
                 f"Throttling: *{BROADCAST_RATE_LIMIT} msg/sec*\n"
                 f"Features: Button Confirm, /remshed, Multi-Button\n"
                 f"Use /vip to see your admin commands.",
            parse_mode=ParseMode.MARKDOWN
        )
        logger.info("Admin හට startup පණිවිඩය යවන ලදී.")
    except Exception as e:
        logger.error(f"Admin හට startup පණිවිඩය යැවීමට නොහැකි විය: {e}")

def parse_buttons(message_text: str) -> (InlineKeyboardMarkup | None):
    """බහු-පේළි බොත්තම් (multi-line buttons) සකසන ශ්‍රිතය."""
    lines = message_text.split('\n')[1:] # පළමු පේළිය (command එක) මඟ හැරීම
    buttons = []
    if not lines:
        return None # බොත්තම් නැත

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            button_text, button_url = line.split('|', 1)
            button_text = button_text.strip()
            button_url = button_url.strip()
            if not (button_url.startswith("http://") or button_url.startswith("https://")):
                logger.warning(f"වලංගු නොවන URL එකක් මඟ හරින ලදී: {button_url}")
                continue
            buttons.append([InlineKeyboardButton(text=button_text, url=button_url)])
        except ValueError:
            logger.warning(f"වලංගු නොවන බොත්තම් ආකෘතියක් මඟ හරින ලදී: {line}")
            continue
    
    if buttons:
        return InlineKeyboardMarkup(buttons)
    return None

def parse_time(time_str: str) -> (int | None):
    """Schedule command එකේ කාලය තත්පර වලට හරවයි (10m, 2h, 1d)."""
    if not time_str:
        return None
    match = re.match(r"^(\d+)([mhd])$", time_str.lower())
    if not match:
        return None
    value = int(match.group(1))
    unit = match.group(2)
    if unit == 'm':
        return value * 60 # මිනිත්තු
    elif unit == 'h':
        return value * 3600 # පැය
    elif unit == 'd':
        return value * 86400 # දවස්
    return None

def get_subscriber_ids() -> list:
    """Database එකෙන් සියලුම subscriber IDs ලබාගැනීම."""
    try:
        users_ref = db.collection('subscribers').stream()
        return [user.id for user in users_ref]
    except Exception as e:
        logger.error(f"Firestore වෙතින් subscriber IDs ලබාගත නොහැකි විය: {e}")
        return []


async def do_broadcast(context: ContextTypes.DEFAULT_TYPE, job_data: dict) -> None:
    """Broadcast එක සිදුකරන ප්‍රධාන ශ්‍රිතය (Throttling සමග)."""
    
    admin_id = job_data["admin_id"]
    from_chat_id = job_data["from_chat_id"]
    message_id = job_data["message_id"]
    buttons = job_data["buttons"] # InlineKeyboardMarkup object එක හෝ None
    operation = "copy" if buttons else "forward" # Smart Send
    
    subscriber_ids = get_subscriber_ids()
    if not subscriber_ids:
        await context.bot.send_message(admin_id, "Database එක හිස්ය. Broadcast එක අවලංගු කරන ලදී.")
        return

    total_users = len(subscriber_ids)
    success_count = 0
    failure_count = 0
    
    # Admin ට broadcast එක පටන් ගත් බව දැනුම් දීම
    await context.bot.send_message(
        admin_id,
        f"🚀 *Broadcast එක ඇරඹුණා...*\n\n"
        f"ක්‍රියාව: *{operation.upper()}*\n"
        f"පරිශීලකයින් *{total_users}* දෙනෙකුට යවමින් සිටී (වේගය: {BROADCAST_RATE_LIMIT} msg/sec).\n\n"
        f"මෙය අවසන් වූ පසු ඔබට අවසන් වාර්තාවක් ලැබෙනු ඇත.",
        parse_mode=ParseMode.MARKDOWN
    )
    
    # Throttled Loop - වේගය පාලනය කරමින් යැවීම
    for user_id_str in subscriber_ids:
        try:
            user_id_int = int(user_id_str)
            if operation == "copy":
                await context.bot.copy_message(chat_id=user_id_int, from_chat_id=from_chat_id, message_id=message_id, reply_markup=buttons)
            else: # operation == "forward"
                await context.bot.forward_message(chat_id=user_id_int, from_chat_id=from_chat_id, message_id=message_id)
            success_count += 1
        except (Forbidden, BadRequest) as e:
            failure_count += 1
            if "bot was blocked by the user" in str(e).lower() or "user is deactivated" in str(e).lower():
                logger.info(f"User {user_id_str} විසින් bot ව block කර ඇත. Database එකෙන් ඉවත් කරමින්...")
                try:
                    db.collection('subscribers').document(user_id_str).delete()
                except Exception as del_e:
                    logger.error(f"User {user_id_str} ව ඉවත් කිරීමට නොහැකි විය: {del_e}")
        except Exception as e:
            failure_count += 1
            logger.error(f"{user_id_str} වෙත යැවීමේදී නොදන්නා දෝෂයක්: {e}")

        # Throttling - වේගය පාලනය කිරීම
        await asyncio.sleep(1 / BROADCAST_RATE_LIMIT)

    # Admin ට අවසන් වාර්තාව යැවීම
    await context.bot.send_message(
        admin_id,
        f"✅ *Broadcast එක අවසන්!*\n\n"
        f"සාර්ථකව යැවූ ගණන: *{success_count}*\n"
        f"අසාර්ථක වූ ගණන: *{failure_count}*\n"
        f"(Block කළ/Deactivated වූ පරිශීලකයින් ස්වයංක්‍රීයව ඉවත් කරන ලදී)",
        parse_mode=ParseMode.MARKDOWN
    )

# --- BOT HANDLER FUNCTIONS (පරිශීලක විධාන) ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start විධානය සහ group සාමාජිකත්වය තහවුරු කිරීම."""
    user = update.effective_user
    chat = update.effective_chat
    
    if chat.type != 'private':
        if str(chat.id) == str(TARGET_GROUP_ID):
            try:
                await update.message.reply_text(f"👋 @{user.username or user.first_name}, කරුණාකර මට /start යන්න පුද්ගලිකව (DM) එවන්න!", reply_to_message_id=update.message.message_id)
            except Exception: pass
        return

    logger.info(f"User {user.id} වෙතින් /start ලැබුණි (DM)")
    membership = await check_group_membership(context, user.id)

    if not membership["is_member"]:
        logger.info(f"User {user.id} group එකේ නැත (Status: {membership['status']}). ලියාපදිංචිය ප්‍රතික්ෂේප විය.")
        reply_text = (
            "⛔ *ලියාපදිංචිය අසාර්ථකයි*\n\n"
            "Broadcast සේවාව ලබාගැනීමට, ඔබ අපගේ ප්‍රධාන group එකේ සාමාජිකයෙකු විය යුතුය.\n\n"
            "කරුණාකර group එකට join වී, නැවත මෙහි /start ලෙස ටයිප් කරන්න."
        )
        if membership["status"] == "error":
            reply_text = "⚠️ ඔබගේ සාමාජිකත්වය තහවුරු කිරීමේදී දෝෂයක් සිදුවිය. කරුණාකර පසුව නැවත උත්සාහ කරන්න."
            await context.bot.send_message(
                chat_id=ADMIN_USER_ID,
                text=f"🆘 *CRITICAL BOT ERROR*\n\nUser `{user.id}` ගේ සාමාජිකත්වය (group: `{TARGET_GROUP_ID}`) පරීක්ෂා කළ නොහැක.\n\n*දෝෂය:* `{membership.get('error_message')}`\n\n👉 **ක්‍රියාමාර්ගය: Bot ව අනිවාර්යයෙන්ම group එකේ ADMINISTRATOR කෙනෙක් කරන්න!**",
                parse_mode=ParseMode.MARKDOWN
            )
        await update.message.reply_text(reply_text, parse_mode=ParseMode.MARKDOWN)
        return

    try:
        logger.info(f"User {user.id} group එකේ සිටී. (Status: {membership['status']}).")
        user_doc_ref = db.collection('subscribers').document(str(user.id))
        user_doc = user_doc_ref.get()
        if not user_doc.exists:
            user_data = {'user_id': user.id, 'first_name': user.first_name, 'last_name': user.last_name or '', 'username': user.username or '', 'subscribed_at': firestore.SERVER_TIMESTAMP}
            user_doc_ref.set(user_data)
            logger.info(f"නව පරිශීලකයෙක් ({user.id}) Firestore වෙත ඇතුලත් කරන ලදී.")
            await context.bot.send_message(chat_id=user.id, text="✅ *සාර්ථකව ලියාපදිංචි විය!*\n\nඔබව අපගේ broadcast ලැයිස්තුවට සාර්ථකව ඇතුලත් කරගන්නා ලදී.", parse_mode=ParseMode.MARKDOWN)
        else:
            logger.info(f"User {user.id} දැනටමත් ලියාපදිංචි වී ඇත.")
            await context.bot.send_message(chat_id=user.id, text="ℹ️ ඔබ දැනටමත් අපගේ broadcast ලැයිස්තුවේ ලියාපදිංචි වී ඇත.")
    except Exception as e:
        logger.error(f"/start විධානයේ දෝෂයක් (User {user.id}): {e}")
        await update.message.reply_text("⚠️ පද්ධතියේ දෝෂයක් සිදුවිය. කරුණාකර පසුව නැවත උත්සාහ කරන්න.")

# --- ADMIN COMMANDS (Admin ගේ විධාන) ---

async def vip_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """v2.0 - යාවත්කාලීන කරන ලද /vip මෙනුව පෙන්වයි."""
    menu_text = (
        "👑 *Admin VIP Menu (Advanced v2.0)*\n\n"
        
        "*/vip*\n"
        "› මෙම මෙනුව පෙන්වයි.\n\n"
        
        "*/send*\n"
        "› පණිවිඩයකට reply කර මෙය යොදන්න. Bot විසින් බොත්තම් මගින් තහවුරු කිරීමට අසනු ඇත.\n"
        "› **බොත්තම් නැතුව:** පණිවිඩය FORWARD කරයි.\n"
        "› **බොත්තම් සමග:** පණිවිඩය COPY කරයි.\n\n"

        "*/schedule* `[කාලය]`\n"
        "› `/send` මෙනි, නමුත් නියමිත වේලාවකට schedule කරයි.\n"
        "› `[කාලය]` = 10m, 2h, 1d.\n\n"

        "*බොත්තම් යොදන ආකාරය (/send & /schedule සඳහා):*\n"
        "විධානයට පසුව, *නව පේළි වලින්* බොත්තම් යොදන්න.\n"
      
        "*/stats*\n"
        "› මුළු subscribers ලා ගණන පෙන්වයි.\n\n"
        
        "*/remshed*\n"
        "› (NEW!) Schedule කර ඇති *සියලුම* broadcasts අවලංගු කරයි.\n\n"
        
        "*/getuser* `[USER_ID]`\n"
        "› subscriber කෙනෙකුගේ විස්තර පෙන්වයි.\n\n"
        
        "*/deluser* `[USER_ID]`\n"
        "› subscriber කෙනෙක්ව database එකෙන් ඉවත් කරයි."
    )
    await update.message.reply_text(menu_text, parse_mode=ParseMode.MARKDOWN)

async def send_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/send විධානය. v2.0 - තහවුරු කිරීමට බොත්තම් (Buttons) ඉල්ලයි."""
    
    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ *භාවිතා කරන ආකාරය:*\nඔබට යැවීමට අවශ්‍ය පණිවිඩයට Reply කර `/send` ලෙස ටයිප් කරන්න.")
        return
        
    context.chat_data.clear() # පැරණි තහවුරු කිරීම් ඉවත් කිරීම
    message_to_send = update.message.reply_to_message
    buttons = parse_buttons(update.message.text)
    subscriber_count = len(get_subscriber_ids())
    operation = "COPY with buttons" if buttons else "FORWARD"

    # දත්ත තාවකාලිකව මතකයේ තබාගැනීම
    context.chat_data['pending_broadcast'] = {
        "admin_id": update.effective_user.id,
        "from_chat_id": message_to_send.chat_id,
        "message_id": message_to_send.message_id,
        "buttons": buttons,
        "count": subscriber_count,
        "operation": operation
    }

    # Admin ගෙන් තහවුරු කිරීම ඉල්ලීම (බොත්තම් සමග)
    keyboard = [
        [InlineKeyboardButton("✅ YES (තහවුරු කරන්න)", callback_data="confirm_broadcast_yes")],
        [InlineKeyboardButton("❌ NO (අවලංගු කරන්න)", callback_data="confirm_broadcast_no")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"⚠️ *Broadcast එක තහවුරු කරන්න*\n\n"
        f"ඔබ මෙම පණිවිඩය *{operation.upper()}* කිරීමට සූදානම්.\n"
        f"මුළු පරිශීලකයින් ගණන: *{subscriber_count}*\n\n"
        f"කරුණාකර පහත බොත්තමක් මගින් තහවුරු කරන්න:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/schedule විධානය. v2.0 - තහවුරු කිරීමට බොත්තම් (Buttons) ඉල්ලයි."""

    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ *භාවිතා කරන ආකාරය:*\nපණිවිඩයකට Reply කර `/schedule [කාලය]` ලෙස යොදන්න (උදා: `/schedule 2h`).")
        return
    if not context.args:
        await update.message.reply_text("⚠️ *කාලය අවශ්‍යයි.*\nභාවිතය: `/schedule 10m` හෝ `/schedule 2h` හෝ `/schedule 1d`")
        return

    context.chat_data.clear() # පැරණි තහවුරු කිරීම් ඉවත් කිරීම
    time_str = context.args[0]
    time_in_seconds = parse_time(time_str)
    
    if time_in_seconds is None:
        await update.message.reply_text("⚠️ *කාල ආකෘතිය වැරදියි.*\n`m` (මිනිත්තු), `h` (පැය), හෝ `d` (දවස්) භාවිතා කරන්න.\nඋදාහරණ: `/schedule 2h`")
        return

    message_to_send = update.message.reply_to_message
    buttons = parse_buttons(update.message.text)
    subscriber_count = len(get_subscriber_ids())
    operation = "COPY with buttons" if buttons else "FORWARD"

    # දත්ත තාවකාලිකව මතකයේ තබාගැනීම
    context.chat_data['pending_schedule'] = {
        "admin_id": update.effective_user.id,
        "from_chat_id": message_to_send.chat_id,
        "message_id": message_to_send.message_id,
        "buttons": buttons,
        "count": subscriber_count,
        "operation": operation,
        "time_str": time_str,
        "time_sec": time_in_seconds
    }

    # Admin ගෙන් තහවුරු කිරීම ඉල්ලීම (බොත්තම් සමග)
    keyboard = [
        [InlineKeyboardButton("✅ YES (Schedule කරන්න)", callback_data="confirm_schedule_yes")],
        [InlineKeyboardButton("❌ NO (අවලංගු කරන්න)", callback_data="confirm_schedule_no")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"⏳ *Schedule එක තහවුරු කරන්න*\n\n"
        f"ඔබ මෙම පණිවිඩය *{operation.upper()}* කිරීමට සූදානම්.\n"
        f"මුළු පරිශීලකයින් ගණන: *{subscriber_count}*\n"
        f"යවන කාලය: තව *{time_str}* කින්.\n\n"
        f"කරුණාකර පහත බොත්තමක් මගින් තහවුරු කරන්න:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def button_confirmation_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """NEW v2.0 - 'YES'/'NO' බොත්තම් click කිරීම් හසුරුවයි."""
    
    query = update.callback_query
    await query.answer() # බොත්තම click කළ බව Telegram වෙත දැනුම් දීම
    
    data = query.data # "confirm_broadcast_yes" වැනි දත්ත
    
    # --- Broadcast තහවුරු කිරීම ---
    if data == "confirm_broadcast_yes":
        job_data = context.chat_data.pop('pending_broadcast', None)
        if job_data is None:
            await query.edit_message_text("⚠️ මෙම ක්‍රියාව කල් ඉකුත් වී ඇත (Action Expired) හෝ දැනටමත් තහවුරු කර ඇත.", reply_markup=None)
            return
        
        await query.edit_message_text("✅ තහවුරු කරන ලදී. Broadcast එක අරඹමින්...", reply_markup=None)
        context.application.create_task(do_broadcast(context, job_data))
        
    elif data == "confirm_broadcast_no":
        context.chat_data.pop('pending_broadcast', None)
        await query.edit_message_text("❌ Broadcast එක අවලංගු කරන ලදී.", reply_markup=None)

    # --- Schedule තහවුරු කිරීම ---
    elif data == "confirm_schedule_yes":
        job_data = context.chat_data.pop('pending_schedule', None)
        if job_data is None:
            await query.edit_message_text("⚠️ මෙම ක්‍රියාව කල් ඉකුත් වී ඇත (Action Expired) හෝ දැනටමත් තහවුරු කර ඇත.", reply_markup=None)
            return

        time_sec = job_data.pop('time_sec')
        time_str = job_data.pop('time_str')
        
        # Job එක schedule කිරීම (නමක් සහිතව)
        job_name = f"broadcast_{job_data['message_id']}_{datetime.now().timestamp()}"
        context.job_queue.run_once(scheduled_broadcast_job, time_sec, data=job_data, name=job_name)
        
        await query.edit_message_text(
            f"✅ *සාර්ථකව Schedule කරන ලදී!*\n\nBroadcast එක තව *{time_str}* කින් යවනු ලැබේ.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=None
        )
        
    elif data == "confirm_schedule_no":
        context.chat_data.pop('pending_schedule', None)
        await query.edit_message_text("❌ Schedule එක අවලංගු කරන ලදී.", reply_markup=None)


async def scheduled_broadcast_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """නියමිත වේලාවට schedule වූ job එක run කිරීම."""
    logger.info(f"Schedule වූ job එකක් අරඹමින්: {context.job.name}")
    job_data = context.job.data
    await do_broadcast(context, job_data)


# --- Other Admin Commands (අනෙකුත් Admin විධාන) ---

async def stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/stats - ගණනය කිරීම්."""
    try:
        count = len(get_subscriber_ids())
        await update.message.reply_text(f"📊 *Bot Statistics*\nමුළු Subscribers ලා ගණන: *{count}*", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"Stats ලබාගැනීමේ දෝෂයක්: {e}")

async def cancel_schedule_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """NEW v2.0 - /remshed - සියලුම schedule වූ job අවලංගු කිරීම."""
    
    jobs = context.job_queue.jobs()
    if not jobs:
        await update.message.reply_text("ℹ️ අවලංගු කිරීමට කිසිදු schedule job එකක් නොමැත.")
        return

    count = 0
    for job in jobs:
        # අපගේ broadcast job පමණක් තෝරා ඉවත් කිරීම
        if job.name.startswith("broadcast_"):
            job.schedule_removal()
            count += 1
            
    logger.info(f"Admin cancelled {count} scheduled jobs.")
    await update.message.reply_text(f"✅ සාර්ථකයි! Schedule කර තිබූ broadcast jobs *{count}* ක් අවලංගු කරන ලදී.")


async def delete_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/deluser - User කෙනෙක්ව ඉවත් කිරීම."""
    if not context.args:
        await update.message.reply_text("භාවිතය: `/deluser [USER_ID]`")
        return
    user_id_to_delete = context.args[0]
    if not user_id_to_delete.isdigit():
        await update.message.reply_text("වලංගු නොවන User ID එකකි. ඉලක්කම් පමණක් යොදන්න.")
        return
    try:
        doc_ref = db.collection('subscribers').document(user_id_to_delete)
        if doc_ref.get().exists:
            doc_ref.delete()
            await update.message.reply_text(f"✅ User {user_id_to_delete} ව database එකෙන් සාර්ථකව ඉවත් කරන ලදී.")
        else:
            await update.message.reply_text(f"⚠️ User {user_id_to_delete} ව database එකේ සොයාගත නොහැක.")
    except Exception as e:
        await update.message.reply_text(f"User ව ඉවත් කිරීමේ දෝෂයක්: {e}")

async def get_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/getuser - User කෙනෙකුගේ විස්තර බැලීම."""
    if not context.args:
        await update.message.reply_text("භාවිතය: `/getuser [USER_ID]`")
        return
    user_id_to_get = context.args[0]
    if not user_id_to_get.isdigit():
        await update.message.reply_text("වලංගු නොවන User ID එකකි. ඉලක්කම් පමණක් යොදන්න.")
        return
    try:
        doc = db.collection('subscribers').document(user_id_to_get).get()
        if doc.exists:
            data = doc.to_dict()
            sub_time = "N/A"
            if 'subscribed_at' in data and isinstance(data['subscribed_at'], datetime):
                sub_time = data['subscribed_at'].strftime("%Y-%m-%d %H:%M:%S")
            username = f"@{data.get('username')}" if data.get('username') else "N/A"
            reply_text = (
                f"👤 *පරිශීලක විස්තර: `{data.get('user_id')}`*\n\n"
                f"First Name: *{data.get('first_name')}*\n"
                f"Last Name: *{data.get('last_name') or 'N/A'}*\n"
                f"Username: *{username}*\n"
                f"Subscribed On: `{sub_time}`"
            )
            await update.message.reply_text(reply_text, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(f"⚠️ User {user_id_to_get} ව database එකේ සොයාගත නොහැක.")
    except Exception as e:
        await update.message.reply_text(f"User ගේ විස්තර ලබාගැනීමේ දෝෂයක්: {e}")


def main() -> None:
    """Bot එක පණගැන්වීම."""
    
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN එක සකසා නැත! කරුණාකර configuration එක පරීක්ෂා කරන්න.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.post_init = notify_admin_on_startup
    admin_filter = filters.User(user_id=ADMIN_USER_ID)

    # --- Handlers v2.0 (විධාන භාරගැනීම) ---
    application.add_handler(CommandHandler("start", start_command, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("vip", vip_menu_handler, filters=admin_filter))
    application.add_handler(CommandHandler("send", send_command, filters=admin_filter))
    application.add_handler(CommandHandler("schedule", schedule_command, filters=admin_filter))
    application.add_handler(CommandHandler("stats", stats_handler, filters=admin_filter))
    application.add_handler(CommandHandler("remshed", cancel_schedule_handler, filters=admin_filter)) # අලුත් command එක
    application.add_handler(CommandHandler("deluser", delete_user_handler, filters=admin_filter))
    application.add_handler(CommandHandler("getuser", get_user_handler, filters=admin_filter))
    
    # NEW v2.0 - 'YES'/'NO' බොත්තම් සඳහා CallbackQueryHandler
    # `handle_confirmation` (MessageHandler) එක ඉවත් කර, මෙය යොදන ලදී
    application.add_handler(CallbackQueryHandler(button_confirmation_handler, pattern="^confirm_"))

    logger.info("Bot (Advanced v2.0) සාර්ථකව ආරම්භ විය... polling කරමින්...")
    application.run_polling()

if __name__ == '__main__':
    main()

