"""
ADVANCED Telegram Broadcast Bot (Sinhala Welcome / English Admin)
- Fully updated for python-telegram-bot v20+
- All code in a single file.
- Scheduling features are REMOVED.

--- FIX v5.0 (මෙම අනුවාදයේ වෙනස) ---
-   CRITICAL FIX: Fixed "InlineKeyboardMarkup has no attribute 'from_dict'" error.
-   The bot now passes the 'InlineKeyboardMarkup' object directly between confirmation and
    broadcasting, instead of converting it to/from a dict.
    (බොත්තම් ටික dict එකක් බවට පත්කිරීමේ දෝෂය නිරාකරණය කර ඇත).

--- FEATURES (විශේෂාංග) ---
1.  Group Welcome: Welcomes new users in SINHALA.
2.  Group /start: Checks DB, replies in SINHALA.
3.  Language Mix: Admin panel in English, User messages in Sinhala.
4.  Multi-Line Buttons
5.  Smart Send (Auto Forward/Copy)
6.  Button Confirmation (YES/NO)
7.  Broadcast Throttling
"""

import logging
import firebase_admin
import asyncio
import re
import traceback # Error එකේ විස්තර ලබාගැනීමට
from firebase_admin import credentials, firestore
from datetime import datetime
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup, User
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    CallbackQueryHandler
)

# --- START OF CONFIGURATION (සැකසුම්) ---
TELEGRAM_BOT_TOKEN = "8419617505:AAFwnP-m7fbhbcUYFKm85xQmz0FLsyupZbE"
ADMIN_USER_ID = 6687619682
TARGET_GROUP_ID = -1003084456496
BOT_USERNAME = "Paid_updates_bot" # (ඔබගේ bot ගේ username එක @ ලකුණ නොමැතිව)
# --- END OF CONFIGURATION ---

# --- ADVANCED CONFIG ---
BROADCAST_RATE_LIMIT = 25 # Messages per second (safe limit)

# Setup logging (English)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize Firebase
try:
    cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    logger.info("Successfully connected to Firebase!")
except Exception as e:
    logger.error(f"Error connecting to Firebase: {e}")
    exit()

# --- HELPER FUNCTIONS ---

async def check_group_membership(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> dict:
    """Checks if a user is a member of the target group."""
    try:
        member = await context.bot.get_chat_member(chat_id=TARGET_GROUP_ID, user_id=user_id)
        if member.status in ['member', 'administrator', 'creator', 'restricted']:
            return {"is_member": True, "status": member.status}
        else:
            return {"is_member": False, "status": member.status}
    except (BadRequest, Forbidden) as e:
        logger.error(f"Error checking membership for {user_id}: {e}")
        return {"is_member": False, "status": "error", "error_message": str(e)}
    except Exception as e:
        logger.error(f"Generic error in check_group_membership: {e}")
        return {"is_member": False, "status": "error", "error_message": str(e)}

async def notify_admin_on_startup(app: Application) -> None:
    """Sends a DM to the Admin (in English) when the bot starts."""
    try:
        await app.bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=f"🤖 *Bot is now ONLINE! (v5.0 Button Fix)*\n\n"
                 f"Throttling: *{BROADCAST_RATE_LIMIT} msg/sec*\n"
                 f"Features: Group Welcome, Button Confirmations.\n"
                 f"Use /vip to see your admin commands.",
            parse_mode=ParseMode.MARKDOWN
        )
        logger.info("Admin startup notification sent.")
    except Exception as e:
        logger.error(f"Failed to send startup notification to Admin: {e}")

def parse_buttons(message_text: str) -> (InlineKeyboardMarkup | None):
    """Parses the multi-line button format (English logic)."""
    lines = message_text.split('\n')[1:] 
    buttons = []
    if not lines:
        return None

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            button_text, button_url = line.split('|', 1)
            button_text = button_text.strip()
            button_url = button_url.strip()
            if not (button_url.startswith("http://") or button_url.startswith("https://")):
                logger.warning(f"Skipping invalid URL: {button_url}")
                continue
            buttons.append([InlineKeyboardButton(text=button_text, url=button_url)])
        except ValueError:
            logger.warning(f"Skipping invalid button format: {line}")
            continue
    
    if buttons:
        return InlineKeyboardMarkup(buttons)
    return None

def get_subscriber_ids() -> list:
    """Gets all subscriber IDs from the database (English logic)."""
    try:
        users_ref = db.collection('subscribers').stream()
        return [user.id for user in users_ref]
    except Exception as e:
        logger.error(f"Could not get subscriber IDs from Firestore: {e}")
        return []

# --- CRITICAL FIX in this function ---
async def do_broadcast(context: ContextTypes.DEFAULT_TYPE, job_data: dict) -> None:
    """
    The main broadcast function (with throttling).
    Wrapped in a try/except to report errors.
    """
    admin_id = job_data.get("admin_id", ADMIN_USER_ID)

    try:
        # --- Broadcast එක සකස් කිරීම ---
        from_chat_id = job_data["from_chat_id"]
        message_id = job_data["message_id"]
        
        # --- FIX v5.0 ---
        # බොත්තම් 'dict' එකක් ලෙස නොව, 'object' එකක් ලෙසම ලබාගැනීම
        # buttons_dict = job_data.get("buttons") # <-- පරණ ක්‍රමය (වැරදියි)
        # buttons_markup = InlineKeyboardMarkup.from_dict(buttons_dict) if buttons_dict else None # <-- පරණ ක්‍රමය (වැරදියි)
        
        buttons_markup = job_data.get("buttons") # <-- අලුත් ක්‍රමය (නිවැරදියි)
        
        operation = "copy" if buttons_markup else "forward"
        
        subscriber_ids = get_subscriber_ids()
        if not subscriber_ids:
            await context.bot.send_message(admin_id, "Broadcast cancelled. The subscriber database is empty.")
            return

        total_users = len(subscriber_ids)
        success_count = 0
        failure_count = 0
        
        # --- Admin ට "Broadcast Started" පණිවිඩය යැවීම ---
        await context.bot.send_message(
            admin_id,
            f"🚀 *Broadcast Started...*\n\n"
            f"Operation: *{operation.upper()}*\n"
            f"Sending to *{total_users}* users (Rate: {BROADCAST_RATE_LIMIT} msg/sec).\n\n"
            f"You will get a final report when this is complete.",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # --- Throttled Loop (පණිවිඩ යැවීමේ loop එක) ---
        for user_id_str in subscriber_ids:
            try:
                user_id_int = int(user_id_str)
                if operation == "copy":
                    await context.bot.copy_message(chat_id=user_id_int, from_chat_id=from_chat_id, message_id=message_id, reply_markup=buttons_markup)
                else:
                    await context.bot.forward_message(chat_id=user_id_int, from_chat_id=from_chat_id, message_id=message_id)
                success_count += 1
            except (Forbidden, BadRequest) as e:
                failure_count += 1
                if "bot was blocked by the user" in str(e).lower() or "user is deactivated" in str(e).lower():
                    logger.info(f"User {user_id_str} blocked the bot. Removing from database...")
                    try:
                        db.collection('subscribers').document(user_id_str).delete()
                    except Exception as del_e:
                        logger.error(f"Failed to delete user {user_id_str}: {del_e}")
                else:
                    logger.error(f"Failed to send to {user_id_str}: {e}")
            except Exception as e:
                failure_count += 1
                logger.error(f"Unknown error sending to {user_id_str}: {e}")
            
            await asyncio.sleep(1 / BROADCAST_RATE_LIMIT)

        # --- අවසන් වාර්තාව Admin ට යැවීම ---
        await context.bot.send_message(
            admin_id,
            f"✅ *Broadcast Complete!*\n\n"
            f"Successfully Sent: *{success_count}*\n"
            f"Failed to Send: *{failure_count}*\n"
            f"(Blocked/Deactivated users have been auto-removed)",
            parse_mode=ParseMode.MARKDOWN
        )
    
    except Exception as e:
        logger.error(f"CRITICAL ERROR in do_broadcast: {e}", exc_info=True)
        try:
            await context.bot.send_message(
                admin_id,
                f"🆘 *Broadcast FAILED!*\n\n"
                f"An unexpected error occurred and the broadcast could not be started.\n\n"
                f"*Error Message:* `{e}`\n\n"
                f"*(For dev: Check server logs for full traceback)*",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as report_e:
            logger.error(f"Failed to even report the broadcast error to admin: {report_e}")


# --- BOT HANDLER FUNCTIONS (Public - SINHALA REPLIES) ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /start in DMs (Replies in SINHALA)."""
    user = update.effective_user
    chat = update.effective_chat
    
    if chat.type != 'private':
        return

    logger.info(f"Received /start from User {user.id} (DM)")
    membership = await check_group_membership(context, user.id)

    if not membership["is_member"]:
        logger.info(f"User {user.id} is not in the group (Status: {membership['status']}). Subscription rejected.")
        reply_text = (
            "⛔ *ලියාදිංචිය අසාර්ථකයි*\n\n"
            "Broadcast සේවාව ලබාගැනීමට, ඔබ අපගේ ප්‍රධාන group එකේ සාමාජිකයෙකු විය යුතුය.\n\n"
            "කරුණාකර group එකට join වී, නැවත මෙහි /start ලෙස ටයිප් කරන්න."
        )
        if membership["status"] == "error":
            reply_text = "⚠️ ඔබගේ සාමාජිකත්වය තහවුරු කිරීමේදී දෝෂයක් සිදුවිය. කරුණාකර පසුව නැවත උත්සාහ කරන්න."
            await context.bot.send_message(
                chat_id=ADMIN_USER_ID,
                text=f"🆘 *CRITICAL BOT ERROR*\n\nCannot check membership for User `{user.id}` (Group: `{TARGET_GROUP_ID}`).\n\n*Error:* `{membership.get('error_message')}`\n\n👉 **ACTION REQUIRED: You MUST make the bot an ADMINISTRATOR in your group!**",
                parse_mode=ParseMode.MARKDOWN
            )
        await update.message.reply_text(reply_text, parse_mode=ParseMode.MARKDOWN)
        return

    try:
        logger.info(f"User {user.id} is in the group (Status: {membership['status']}).")
        user_doc_ref = db.collection('subscribers').document(str(user.id))
        user_doc = user_doc_ref.get()

        if not user_doc.exists:
            user_data = {'user_id': user.id, 'first_name': user.first_name, 'last_name': user.last_name or '', 'username': user.username or '', 'subscribed_at': firestore.SERVER_TIMESTAMP}
            user_doc_ref.set(user_data)
            logger.info(f"New subscriber {user.id} added to Firestore.")
            await context.bot.send_message(chat_id=user.id, text="✅ *සාර්ථකව ලියාපදිංචි විය!*\n\nඔබව අපගේ broadcast ලැයිස්තුවට සාර්ථකව ඇතුලත් කරගන්නා ලදී.", parse_mode=ParseMode.MARKDOWN)
        else:
            logger.info(f"User {user.id} is already subscribed.")
            await context.bot.send_message(chat_id=user.id, text="ℹ️ ඔබ දැනටමත් අපගේ broadcast ලැයිස්තුවේ ලියාපදිංචි වී ඇත.")
    except Exception as e:
        logger.error(f"Error in /start handler for User {user.id}: {e}")
        await update.message.reply_text("⚠️ පද්ධතියේ දෝෂයක් සිදුවිය. කරුණාකර පසුව නැවත උත්සාහ කරන්න.")

# --- NEW HANDLERS (Group - SINHALA REPLIES) ---

def get_welcome_message(member: User) -> (str, InlineKeyboardMarkup):
    """Generates the Sinhala welcome message and button."""
    
    user_mention = member.mention_html()
    
    message_text = (
        f"👋 ආයුබෝවන් {user_mention}!\n"
        f"අපගේ group එකට ඔබව සාදරයෙන් පිළිගනිමු.\n\n"
        f"Group එකේ සියලුම වැදගත් යාවත්කාලීන කිරීම් (updates) සහ පණිවිඩ (broadcasts) "
        f"ඔබගේ Inbox එකටම ලබාගැනීම සඳහා, කරුණාකර පහත 'Start Bot' බොත්තම ඔබා Bot ව Start කරන්න."
    )
    
    keyboard = [
        [InlineKeyboardButton("🤖 Start Bot", url=f"https://t.me/{BOT_USERNAME}?start=group_join")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    return message_text, reply_markup

async def group_start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /start in the GROUP (Replies in SINHALA)."""
    user = update.effective_user
    chat = update.effective_chat
    
    if str(chat.id) != str(TARGET_GROUP_ID):
        return
        
    logger.info(f"Received /start in group from User {user.id}")
    
    doc_ref = db.collection('subscribers').document(str(user.id))
    doc = doc_ref.get()
    
    if doc.exists:
        logger.info(f"User {user.id} is already in DB. Ignoring group /start.")
        return
    else:
        logger.info(f"User {user.id} is NOT in DB. Sending welcome prompt in group.")
        message_text, reply_markup = get_welcome_message(user)
        try:
            await update.message.reply_text(
                text=message_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
                reply_to_message_id=update.message.message_id
            )
        except Exception as e:
            logger.error(f"Failed to send group /start reply: {e}")

async def new_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Welcomes new members who JOIN or are ADDED (Replies in SINHALA)."""
    chat = update.effective_chat
    
    if str(chat.id) != str(TARGET_GROUP_ID):
        return
        
    new_members = update.message.new_chat_members
    logger.info(f"{len(new_members)} new member(s) joined group {chat.id}")
    
    for member in new_members:
        if member.is_bot:
            continue
            
        message_text, reply_markup = get_welcome_message(member)
        
        try:
            await context.bot.send_message(
                chat_id=chat.id,
                text=message_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Failed to send welcome message for user {member.id}: {e}")

# --- ADMIN COMMANDS (English) ---

async def vip_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays the Admin VIP Menu (English)."""
    menu_text = (
        "👑 *Admin VIP Menu (v5.0 Button Fix)*\n\n"
        
        "*/vip*\n"
        "› Shows this help menu.\n\n"
        
        "*/send*\n"
        "› Reply to a message and use this command. The bot will ask for confirmation.\n"
        "› **Without Buttons:** FORWARDS the message.\n"
        "› **With Buttons:** COPIES the message.\n\n"

        "*How to Add Buttons (for /send):*\n"
        "Type the command, then add buttons on *new lines*.\n"
                
        "*/stats*\n"
        "› Shows the total number of subscribers.\n\n"
        
        "*/getuser* `[USER_ID]`\n"
        "› Shows details for a specific subscriber.\n\n"
        
        "*/deluser* `[USER_ID]`\n"
        "› Deletes a subscriber from the database."
    )
    await update.message.reply_text(menu_text, parse_mode=ParseMode.MARKDOWN)

# --- CRITICAL FIX in this function ---
async def send_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /send command (English logic)."""
    
    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ *Usage Error:*\nReply to the message you want to send and type `/send`.")
        return
        
    context.chat_data.clear()
    message_to_send = update.message.reply_to_message
    buttons = parse_buttons(update.message.text)
    subscriber_count = len(get_subscriber_ids())
    operation = "COPY with buttons" if buttons else "FORWARD"

    # දත්ත තාවකාලිකව මතකයේ තබාගැනීම
    context.chat_data['pending_broadcast'] = {
        "admin_id": update.effective_user.id,
        "from_chat_id": message_to_send.chat_id,
        "message_id": message_to_send.message_id,
        # --- FIX v5.0 ---
        # 'dict' එකක් වෙනුවට 'object' එකම තබාගැනීම
        # "buttons": buttons.to_dict() if buttons else None, # <-- පරණ ක්‍රමය (වැරදියි)
        "buttons": buttons, # <-- අලුත් ක්‍රමය (නිවැරදියි)
        "count": subscriber_count,
        "operation": operation
    }

    keyboard = [
        [InlineKeyboardButton("✅ YES (Confirm)", callback_data="confirm_broadcast_yes")],
        [InlineKeyboardButton("❌ NO (Cancel)", callback_data="confirm_broadcast_no")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"⚠️ *Confirm Broadcast*\n\n"
        f"You are about to *{operation.upper()}* this message.\n"
        f"Total Subscribers: *{subscriber_count}*\n\n"
        f"Please confirm or cancel using the buttons below:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def button_confirmation_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the 'YES'/'NO' button clicks (English logic)."""
    
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "confirm_broadcast_yes":
        job_data = context.chat_data.pop('pending_broadcast', None)
        if job_data is None:
            await query.edit_message_text("⚠️ This action has expired or was already confirmed.", reply_markup=None)
            return
        
        await query.edit_message_text("✅ Confirmed. Starting broadcast...\n\n(You will get a 'Started' message next, followed by a 'Complete' report.)", reply_markup=None)
        
        context.application.create_task(do_broadcast(context, job_data))
        
    elif data == "confirm_broadcast_no":
        context.chat_data.pop('pending_broadcast', None)
        await query.edit_message_text("❌ Broadcast Canceled.", reply_markup=None)

async def stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/stats - Shows subscriber count (English)."""
    try:
        count = len(get_subscriber_ids())
        await update.message.reply_text(f"📊 *Bot Statistics*\nTotal Subscribers: *{count}*", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"Error getting stats: {e}")

async def delete_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/deluser - Removes a user (English)."""
    if not context.args:
        await update.message.reply_text("Usage: `/deluser [USER_ID]`")
        return
    user_id_to_delete = context.args[0]
    if not user_id_to_delete.isdigit():
        await update.message.reply_text("Invalid User ID. Please provide numbers only.")
        return
    try:
        doc_ref = db.collection('subscribers').document(user_id_to_delete)
        if doc_ref.get().exists:
            doc_ref.delete()
            await update.message.reply_text(f"✅ User {user_id_to_delete} has been successfully deleted from the database.")
        else:
            await update.message.reply_text(f"⚠️ User {user_id_to_delete} was not found in the database.")
    except Exception as e:
        await update.message.reply_text(f"Error deleting user: {e}")

async def get_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/getuser - Shows user details (English)."""
    if not context.args:
        await update.message.reply_text("Usage: `/getuser [USER_ID]`")
        return
    user_id_to_get = context.args[0]
    if not user_id_to_get.isdigit():
        await update.message.reply_text("Invalid User ID. Please provide numbers only.")
        return
    try:
        doc = db.collection('subscribers').document(user_id_to_get).get()
        if doc.exists:
            data = doc.to_dict()
            sub_time_utc = data.get('subscribed_at')
            sub_time_str = "N/A"
            if sub_time_utc and isinstance(sub_time_utc, datetime):
                sub_time_str = sub_time_utc.strftime("%Y-%m-%d %H:%M:%S (UTC)")
            username = f"@{data.get('username')}" if data.get('username') else "N/A"
            reply_text = (
                f"👤 *User Details: `{data.get('user_id')}`*\n\n"
                f"First Name: *{data.get('first_name')}*\n"
                f"Last Name: *{data.get('last_name') or 'N/A'}*\n"
                f"Username: *{username}*\n"
                f"Subscribed On: `{sub_time_str}`"
            )
            await update.message.reply_text(reply_text, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(f"⚠️ User {user_id_to_get} was not found in the database.")
    except Exception as e:
        logger.error(f"Error in /getuser: {e}")
        await update.message.reply_text(f"Error getting user details: {e}")

def main() -> None:
    """Starts the bot."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set! Please check your configuration.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.post_init = notify_admin_on_startup
    admin_filter = filters.User(user_id=ADMIN_USER_ID)
    group_filter = filters.Chat(chat_id=TARGET_GROUP_ID)

    # --- Handlers ---
    application.add_handler(CommandHandler("start", start_command, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("start", group_start_handler, filters=group_filter & filters.ChatType.GROUPS))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS & group_filter, new_member_handler))

    application.add_handler(CommandHandler("vip", vip_menu_handler, filters=admin_filter))
    application.add_handler(CommandHandler("send", send_command, filters=admin_filter))
    application.add_handler(CommandHandler("stats", stats_handler, filters=admin_filter))
    application.add_handler(CommandHandler("deluser", delete_user_handler, filters=admin_filter))
    application.add_handler(CommandHandler("getuser", get_user_handler, filters=admin_filter))
    
    application.add_handler(CallbackQueryHandler(button_confirmation_handler, pattern="^confirm_"))

    logger.info("Bot (v5.0 Button Fix Edition) started successfully... polling...")
    application.run_polling()

if __name__ == '__main__':
    main()


