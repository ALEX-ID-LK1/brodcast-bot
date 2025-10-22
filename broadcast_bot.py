# -*- coding: utf-8 -*-
"""
ADVANCED Telegram Broadcast Bot (English Version)
- FULLY UPDATED for python-telegram-bot v20+
- ALL CODE IN A SINGLE FILE.

--- ADVANCED FEATURES ---
1.  Multi-Line Buttons:
    - Define multiple buttons on new lines after the command.
    - Example:
      /send
      Button 1 | https://link1.com
      Button 2 | https://link2.com

2.  Smart Send (Auto Forward/Copy):
    - /send (no buttons) -> FORWARDS the message.
    - /send (with buttons) -> COPIES the message with buttons.

3.  Scheduled Broadcasts (/schedule):
    - Schedule posts for later.
    - Usage: /schedule [time]
    - [time] can be: 10m (10 minutes), 2h (2 hours), 1d (1 day).
    - Example:
      /schedule 2h
      Button 1 | https://link1.com

4.  Broadcast Confirmation (Safety Feature):
    - Admin must type 'YES' to confirm any broadcast or schedule,
      preventing accidental sends.

5.  Broadcast Throttling (Rate Limiting):
    - Sends messages in batches (approx 25 messages/sec) to avoid
      hitting Telegram's flood limits. CRITICAL for large user bases.

6.  Updated /vip Menu & Startup Notification.
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
    filters
)

# --- START OF CONFIGURATION ---
TELEGRAM_BOT_TOKEN = "8419617505:AAFwnP-m7fbhbcUYFKm85xQmz0FLsyupZbE"
ADMIN_USER_ID = 6687619682
TARGET_GROUP_ID = -1003074965096
# --- END OF CONFIGURATION ---

# --- ADVANCED CONFIG ---
# Messages per second. 25 is a safe limit (Telegram limit is ~30/sec)
BROADCAST_RATE_LIMIT = 25 

# Setup logging (ලොග් සැකසීම)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize Firebase (Firebase ආරම්භ කිරීම)
try:
    cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    logger.info("Firebase initialized successfully!")
except Exception as e:
    logger.error(f"Failed to initialize Firebase: {e}")
    # Bot එක ක්‍රියා විරහිත කිරීම, Firebase නැතුව වැඩක් නැති නිසා
    exit()

# --- HELPER FUNCTIONS (උපකාරක ශ්‍රිත) ---

async def check_group_membership(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> dict:
    """Checks if a user is in the target group. Returns a dictionary."""
    # පරිශීලකයා group එකේ සාමාජිකයෙක්දැයි පරීක්ෂා කරයි
    try:
        member = await context.bot.get_chat_member(chat_id=TARGET_GROUP_ID, user_id=user_id)
        if member.status in ['member', 'administrator', 'creator', 'restricted']:
            return {"is_member": True, "status": member.status}
        else:
            # 'left' or 'kicked'
            return {"is_member": False, "status": member.status}
    except (BadRequest, Forbidden) as e:
        logger.error(f"Error checking chat member status for {user_id}: {e}")
        # Bot ට admin නැත්නම් මෙතනට එනවා
        return {"is_member": False, "status": "error", "error_message": str(e)}
    except Exception as e:
        logger.error(f"General error checking membership for {user_id}: {e}")
        return {"is_member": False, "status": "error", "error_message": str(e)}

async def notify_admin_on_startup(app: Application) -> None:
    """Send a notification to the admin when the bot starts."""
    # Bot එක ඔන් වූ විට Admin ට DM එකක් යවයි
    try:
        await app.bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=f"🤖 *Bot is now ONLINE! (Advanced v1.0)*\n\n"
                 f"Throttling: *{BROADCAST_RATE_LIMIT} msg/sec*\n"
                 f"Features: Multi-Button, Schedule, Confirm\n"
                 f"Use /vip to see your admin commands.",
            parse_mode=ParseMode.MARKDOWN
        )
        logger.info("Admin startup notification sent.")
    except Exception as e:
        logger.error(f"Failed to send startup notification to admin: {e}")

def parse_buttons(message_text: str) -> (InlineKeyboardMarkup | None):
    """
    Parses multi-line button definitions from the command text.
    Format:
    Button Text | https://link.com
    Button Text 2 | https://link2.com
    """
    # Command එකෙන් multi-line buttons වෙන් කරගැනීම
    lines = message_text.split('\n')[1:] # Ignore the first line (the command itself)
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
                logger.warning(f"Invalid URL skipped: {button_url}")
                continue
                
            buttons.append([InlineKeyboardButton(text=button_text, url=button_url)])
        
        except ValueError:
            logger.warning(f"Invalid button format skipped: {line}")
            continue
    
    if buttons:
        return InlineKeyboardMarkup(buttons)
    return None

def parse_time(time_str: str) -> (int | None):
    """Parses time string (10m, 2h, 1d) into seconds."""
    # Schedule command එකේ කාලය තත්පර වලට හරවයි
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
    """Fetches all subscriber IDs from Firestore."""
    # Database එකෙන් සියලුම subscriber IDs ලබාගැනීම
    try:
        users_ref = db.collection('subscribers').stream()
        return [user.id for user in users_ref]
    except Exception as e:
        logger.error(f"Could not get subscriber IDs from Firestore: {e}")
        return []


async def do_broadcast(context: ContextTypes.DEFAULT_TYPE, job_data: dict) -> None:
    """
    The core broadcast function with throttling.
    This function is called by 'handle_confirmation' or 'scheduled_broadcast_job'.
    """
    # Broadcast එක සිදුකරන ප්‍රධාන ශ්‍රිතය (Throttling සමග)
    
    # Extract data from the job
    admin_id = job_data["admin_id"]
    from_chat_id = job_data["from_chat_id"]
    message_id = job_data["message_id"]
    buttons = job_data["buttons"] # This is the InlineKeyboardMarkup object or None
    operation = "copy" if buttons else "forward"
    
    subscriber_ids = get_subscriber_ids()
    if not subscriber_ids:
        await context.bot.send_message(admin_id, "Database is empty. Broadcast cancelled.")
        return

    total_users = len(subscriber_ids)
    success_count = 0
    failure_count = 0
    
    # Admin ට broadcast එක පටන් ගත් බව දැනුම් දීම
    await context.bot.send_message(
        admin_id,
        f"🚀 *Broadcast started...*\n\n"
        f"Operation: *{operation.upper()}*\n"
        f"Sending to *{total_users}* users at {BROADCAST_RATE_LIMIT} msg/sec.\n\n"
        f"You will get a final report when this is complete.",
        parse_mode=ParseMode.MARKDOWN
    )
    
    # Throttled Loop - වේගය පාලනය කරමින් යැවීම
    for user_id_str in subscriber_ids:
        try:
            user_id_int = int(user_id_str)
            
            if operation == "copy":
                await context.bot.copy_message(
                    chat_id=user_id_int,
                    from_chat_id=from_chat_id,
                    message_id=message_id,
                    reply_markup=buttons # None or buttons
                )
            else: # operation == "forward"
                await context.bot.forward_message(
                    chat_id=user_id_int,
                    from_chat_id=from_chat_id,
                    message_id=message_id
                )
            success_count += 1
            
        except (Forbidden, BadRequest) as e:
            failure_count += 1
            logger.error(f"Failed to send to {user_id_str}: {e}")
            if "bot was blocked by the user" in str(e).lower() or "user is deactivated" in str(e).lower():
                logger.info(f"User {user_id_str} blocked/deactivated. Removing from database.")
                try:
                    # Bot ව block කළ අයව DB එකෙන් ඉවත් කිරීම
                    db.collection('subscribers').document(user_id_str).delete()
                except Exception as del_e:
                    logger.error(f"Failed to delete user {user_id_str}: {del_e}")
        except Exception as e:
            failure_count += 1
            logger.error(f"Unknown error sending to {user_id_str}: {e}")

        # Throttling - වේගය පාලනය කිරීම
        # Telegram rate limit (30/sec) එකට අසුනොවීමට මෙසේ කරයි
        await asyncio.sleep(1 / BROADCAST_RATE_LIMIT)

    # Admin ට අවසන් වාර්තාව යැවීම
    await context.bot.send_message(
        admin_id,
        f"✅ *Broadcast Complete!*\n\n"
        f"Sent to: *{success_count}* users\n"
        f"Failed for: *{failure_count}* users\n"
        f"(Blocked/deactivated users were automatically removed)",
        parse_mode=ParseMode.MARKDOWN
    )

# --- BOT HANDLER FUNCTIONS (පරිශීලක විධාන) ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /start command in DMs and verifies group membership."""
    # /start විධානය
    user = update.effective_user
    chat = update.effective_chat
    
    # Group chat එකක /start ගැහුවොත්
    if chat.type != 'private':
        if str(chat.id) == str(TARGET_GROUP_ID):
            try:
                await update.message.reply_text(
                    f"👋 @{user.username or user.first_name}, please send me /start in a private chat (DM) to subscribe!",
                    reply_to_message_id=update.message.message_id
                )
            except Exception: pass
        return

    logger.info(f"Received /start in DM from user {user.id}")
    
    # Group එකේ සාමාජිකයෙක්දැයි පරීක්ෂා කිරීම
    membership = await check_group_membership(context, user.id)

    if not membership["is_member"]:
        logger.info(f"User {user.id} is NOT in the group (status: {membership['status']}). Subscription denied.")
        reply_text = (
            "⛔ *Subscription Failed*\n\n"
            "You must be an active member of our main group to subscribe to broadcasts.\n\n"
            "Please join the group and then type /start here again."
        )
        
        if membership["status"] == "error":
            # Bot ට admin නැත්නම්, Admin ට දැනුම් දීම
            reply_text = "⚠️ An error occurred while verifying your membership. Please try again later."
            await context.bot.send_message(
                chat_id=ADMIN_USER_ID,
                text=f"🆘 *CRITICAL BOT ERROR*\n\n"
                     f"Failed to check member status for user `{user.id}` in group `{TARGET_GROUP_ID}`.\n\n"
                     f"*Error:* `{membership.get('error_message')}`\n\n"
                     "👉 **ACTION REQUIRED: Make sure the bot is an ADMINISTRATOR in the target group!**",
                parse_mode=ParseMode.MARKDOWN
            )
            
        await update.message.reply_text(reply_text, parse_mode=ParseMode.MARKDOWN)
        return

    # --- සාමාජිකයෙක් නම්, DB එකට ඇතුලත් කිරීම ---
    try:
        logger.info(f"User {user.id} is in the group (status: {membership['status']}). Proceeding.")
        
        user_doc_ref = db.collection('subscribers').document(str(user.id))
        user_doc = user_doc_ref.get()

        if not user_doc.exists:
            # User ව DB එකට අලුතෙන් ඇතුලත් කිරීම
            user_data = {
                'user_id': user.id,
                'first_name': user.first_name,
                'last_name': user.last_name or '',
                'username': user.username or '',
                'subscribed_at': firestore.SERVER_TIMESTAMP
            }
            user_doc_ref.set(user_data)
            logger.info(f"New user {user.id} added to Firestore.")
            
            await context.bot.send_message(
                chat_id=user.id,
                text="✅ *Subscribed Successfully!*\n\n"
                     "You have been successfully subscribed to our broadcast list. "
                     "You will now receive important updates directly to your inbox.",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            # User දැනටමත් DB එකේ සිටී නම්
            logger.info(f"User {user.id} is already subscribed.")
            await context.bot.send_message(
                chat_id=user.id,
                text="ℹ️ You are already on the broadcast list."
            )

    except Exception as e:
        logger.error(f"General error in /start for user {user.id}: {e}")
        await update.message.reply_text("⚠️ A system error occurred. Please try again.")

# --- ADMIN COMMANDS (Admin ගේ විධාන) ---

async def vip_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """UPDATED: Displays the new admin command menu."""
    # /vip මෙනුව
    menu_text = (
        "👑 *Admin VIP Menu (Advanced)*\n\n"
        
        "*/vip*\n"
        "› Shows this menu.\n\n"
        
        "*/send*\n"
        "› Reply to a message. Bot will ask for confirmation.\n"
        "› **No buttons:** FORWARDS the message.\n"
        "› **With buttons:** COPIES the message.\n\n"

        "*/schedule* `[time]`\n"
        "› Same as `/send`, but schedules it.\n"
        "› `[time]` = 10m (minutes), 2h (hours), 1d (days).\n\n"

        "*Button Format (for /send & /schedule):*\n"
        "Type buttons on *new lines* after the command.\n"
                
        "*/stats*\n"
        "› Get the total number of subscribers.\n\n"
        
        "*/getuser* `[USER_ID]`\n"
        "› Get details for a specific subscriber.\n\n"
        
        "*/deluser* `[USER_ID]`\n"
        "› Manually remove a subscriber."
    )
    await update.message.reply_text(menu_text, parse_mode=ParseMode.MARKDOWN)

async def send_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /send command. NOW ASKS FOR CONFIRMATION."""
    # /send විධානය
    
    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ *How to use:*\nReply to the message you want to send and type `/send`.")
        return
        
    # Clear any pending actions
    context.chat_data.clear()

    message_to_send = update.message.reply_to_message
    buttons = parse_buttons(update.message.text) # Multi-line buttons පරීක්ෂා කිරීම
    subscriber_count = len(get_subscriber_ids())
    operation = "COPY with buttons" if buttons else "FORWARD" # Smart Send

    # Admin ගෙන් තහවුරු කිරීමට පෙර දත්ත තාවකාලිකව මතකයේ තබාගැනීම
    context.chat_data['pending_broadcast'] = {
        "admin_id": update.effective_user.id,
        "from_chat_id": message_to_send.chat_id,
        "message_id": message_to_send.message_id,
        "buttons": buttons,
        "count": subscriber_count,
        "operation": operation
    }

    # Admin ගෙන් තහවුරු කිරීම ඉල්ලීම
    await update.message.reply_text(
        f"⚠️ *Broadcast Confirmation*\n\n"
        f"You are about to *{operation.upper()}* this message to *{subscriber_count}* users.\n\n"
        f"Type `YES` to confirm or `NO` to cancel.",
        parse_mode=ParseMode.MARKDOWN
    )

async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /schedule command. ASKS FOR CONFIRMATION."""
    # /schedule විධානය

    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ *How to use:*\nReply to a message and type `/schedule [time]` (e.g., `/schedule 2h`).")
        return
    
    if not context.args:
        await update.message.reply_text("⚠️ *Time required.*\nUsage: `/schedule 10m` or `/schedule 2h` or `/schedule 1d`")
        return

    # Clear any pending actions
    context.chat_data.clear()

    time_str = context.args[0]
    time_in_seconds = parse_time(time_str) # කාලය තත්පර වලට හැරවීම
    
    if time_in_seconds is None:
        await update.message.reply_text("⚠️ *Invalid time format.*\nUse `m` (minutes), `h` (hours), or `d` (days).\nExample: `/schedule 2h`")
        return

    message_to_send = update.message.reply_to_message
    buttons = parse_buttons(update.message.text)
    subscriber_count = len(get_subscriber_ids())
    operation = "COPY with buttons" if buttons else "FORWARD"

    # Schedule එක තහවුරු කිරීමට පෙර දත්ත මතකයේ තබාගැනීම
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

    # Admin ගෙන් තහවුරු කිරීම ඉල්ලීම
    await update.message.reply_text(
        f"⏳ *Schedule Confirmation*\n\n"
        f"You are about to schedule this message to be *{operation.upper()}* to *{subscriber_count}* users in *{time_str}*.\n\n"
        f"Type `YES` to confirm or `NO` to cancel.",
        parse_mode=ParseMode.MARKDOWN
    )


async def handle_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the 'YES'/'NO' confirmation from the admin."""
    # Admin ගේ 'YES' හෝ 'NO' පිළිතුරට අනුව ක්‍රියා කිරීම
    
    text = update.message.text.upper()
    
    # Broadcast එකක් තහවුරු කිරීම
    if 'pending_broadcast' in context.chat_data:
        if text == 'YES':
            job_data = context.chat_data.pop('pending_broadcast')
            await update.message.reply_text("Confirmation received. Starting broadcast...")
            
            # Broadcast එක background task එකක් ලෙස පටන් ගැනීම
            context.application.create_task(do_broadcast(context, job_data))
            
        elif text == 'NO':
            context.chat_data.pop('pending_broadcast')
            await update.message.reply_text("Broadcast cancelled.")
        else:
            await update.message.reply_text("Invalid confirmation. Type `YES` or `NO`.")
        return

    # Schedule එකක් තහවුරු කිරීම
    if 'pending_schedule' in context.chat_data:
        if text == 'YES':
            job_data = context.chat_data.pop('pending_schedule')
            time_sec = job_data.pop('time_sec') # කාලය
            time_str = job_data.pop('time_str') # කාලය (text)
            
            # Job එක schedule කිරීම
            context.job_queue.run_once(scheduled_broadcast_job, time_sec, data=job_data, name=f"broadcast_{job_data['message_id']}")
            
            await update.message.reply_text(
                f"✅ *Successfully Scheduled!*\n\n"
                f"The broadcast will be sent in *{time_str}*.",
                parse_mode=ParseMode.MARKDOWN
            )
            
        elif text == 'NO':
            context.chat_data.pop('pending_schedule')
            await update.message.reply_text("Schedule cancelled.")
        else:
            await update.message.reply_text("Invalid confirmation. Type `YES` or `NO`.")
        return

    logger.info(f"Ignoring non-command text from admin: {text}")


async def scheduled_broadcast_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """The callback function that the JobQueue runs for a scheduled post."""
    # නියමිත වේලාවට schedule වූ job එක run කිරීම
    logger.info(f"Running scheduled job: {context.job.name}")
    job_data = context.job.data
    
    # ප්‍රධාන broadcast ශ්‍රිතය call කිරීම
    await do_broadcast(context, job_data)


# --- Other Admin Commands (අනෙකුත් Admin විධාන) ---

async def stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # /stats - ගණනය කිරීම්
    try:
        count = len(get_subscriber_ids())
        await update.message.reply_text(f"📊 *Bot Statistics*\nTotal Subscribers: *{count}*", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"Error fetching stats: {e}")

async def delete_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # /deluser - User කෙනෙක්ව ඉවත් කිරීම
    if not context.args:
        await update.message.reply_text("Usage: `/deluser [USER_ID]`")
        return
    user_id_to_delete = context.args[0]
    if not user_id_to_delete.isdigit():
        await update.message.reply_text("Invalid User ID. It must be a number.")
        return
    try:
        doc_ref = db.collection('subscribers').document(user_id_to_delete)
        if doc_ref.get().exists:
            doc_ref.delete()
            await update.message.reply_text(f"✅ User {user_id_to_delete} has been deleted.")
        else:
            await update.message.reply_text(f"⚠️ User {user_id_to_delete} not found.")
    except Exception as e:
        await update.message.reply_text(f"Error deleting user: {e}")

async def get_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # /getuser - User කෙනෙකුගේ විස්තර බැලීම
    if not context.args:
        await update.message.reply_text("Usage: `/getuser [USER_ID]`")
        return
    user_id_to_get = context.args[0]
    if not user_id_to_get.isdigit():
        await update.message.reply_text("Invalid User ID. It must be a number.")
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
                f"👤 *User Details: `{data.get('user_id')}`*\n\n"
                f"First Name: *{data.get('first_name')}*\n"
                f"Last Name: *{data.get('last_name') or 'N/A'}*\n"
                f"Username: *{username}*\n"
                f"Subscribed On: `{sub_time}`"
            )
            await update.message.reply_text(reply_text, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(f"⚠️ User {user_id_to_get} not found.")
    except Exception as e:
        await update.message.reply_text(f"Error getting user: {e}")


def main() -> None:
    """Start the bot."""
    # Bot එක පණගැන්වීම
    
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set! Please check your configuration.")
        return

    # JobQueue එක යොදාගන්නේ /schedule කිරීම සඳහා
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Admin ට startup notification එක යැවීම
    application.post_init = notify_admin_on_startup

    # Admin ගේ ID එක filter එකක් ලෙස යොදාගැනීම
    admin_filter = filters.User(user_id=ADMIN_USER_ID)

    # --- Handlers (විධාන භාරගැනීම) ---
    # Public command
    application.add_handler(CommandHandler("start", start_command, filters=filters.ChatType.PRIVATE))
    
    # Admin commands
    application.add_handler(CommandHandler("vip", vip_menu_handler, filters=admin_filter))
    application.add_handler(CommandHandler("send", send_command, filters=admin_filter))
    application.add_handler(CommandHandler("schedule", schedule_command, filters=admin_filter))
    application.add_handler(CommandHandler("stats", stats_handler, filters=admin_filter))
    application.add_handler(CommandHandler("deluser", delete_user_handler, filters=admin_filter))
    application.add_handler(CommandHandler("getuser", get_user_handler, filters=admin_filter))
    
    # Confirmation Handler ('YES'/'NO' පිළිතුරු සඳහා)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & admin_filter, handle_confirmation))

    logger.info("Bot started successfully (Advanced v1.0) and is polling...")
    application.run_polling()

if __name__ == '__main__':
    main()

