"""
ADVANCED Telegram Broadcast Bot (English Version)
- Fully updated for python-telegram-bot v20+
- All code in a single file.
- All scheduling features have been REMOVED for stability and simplicity.

--- ADVANCED FEATURES ---
1.  Multi-Line Buttons:
    - Provide buttons and URLs in new lines after the command.
    - Example:
      /send
      Button 1 | https://link1.com
      Button 2 | https://link2.com

2.  Smart Send (Auto Forward/Copy):
    - /send (without buttons) -> Forwards the message.
    - /send (with buttons) -> Copies the message with buttons.

3.  Button Confirmation:
    - Admin must confirm every broadcast by clicking a "YES" or "NO" button.

4.  Broadcast Throttling:
    - Sends messages at a safe rate (25 msgs/sec) to avoid Telegram rate-limits.

5.  Updated /vip Menu & Startup Notification.
"""

import logging
import firebase_admin
import asyncio
import re
from firebase_admin import credentials, firestore
from datetime import datetime # Still needed for 'subscribed_at'
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
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

# --- START OF CONFIGURATION ---
TELEGRAM_BOT_TOKEN = "8419617505:AAFwnP-m7fbhbcUYFKm85xQmz0FLsyupZbE"
ADMIN_USER_ID = 6687619682
TARGET_GROUP_ID = -1003074965096
# --- END OF CONFIGURATION ---

# --- ADVANCED CONFIG ---
# Number of messages sent per second. 25 is a safe limit (Telegram's limit is ~30/sec)
BROADCAST_RATE_LIMIT = 25 

# Setup logging
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
    # Exit if Firebase connection fails
    exit()

# --- HELPER FUNCTIONS ---

async def check_group_membership(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> dict:
    """Checks if a user is a member of the target group."""
    try:
        member = await context.bot.get_chat_member(chat_id=TARGET_GROUP_ID, user_id=user_id)
        if member.status in ['member', 'administrator', 'creator', 'restricted']:
            return {"is_member": True, "status": member.status}
        else:
            # 'left' or 'kicked'
            return {"is_member": False, "status": member.status}
    except (BadRequest, Forbidden) as e:
        logger.error(f"Error checking membership for {user_id}: {e}")
        # This happens if the bot is not an admin in the group
        return {"is_member": False, "status": "error", "error_message": str(e)}
    except Exception as e:
        logger.error(f"Generic error in check_group_membership: {e}")
        return {"is_member": False, "status": "error", "error_message": str(e)}

async def notify_admin_on_startup(app: Application) -> None:
    """Sends a DM to the Admin when the bot starts."""
    try:
        await app.bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=f"🤖 *Bot is now ONLINE! (English Version)*\n\n"
                 f"Throttling: *{BROADCAST_RATE_LIMIT} msg/sec*\n"
                 f"Features: Button Confirm, Multi-Button, No Schedule.\n"
                 f"Use /vip to see your admin commands.",
            parse_mode=ParseMode.MARKDOWN
        )
        logger.info("Admin startup notification sent.")
    except Exception as e:
        logger.error(f"Failed to send startup notification to Admin: {e}")

def parse_buttons(message_text: str) -> (InlineKeyboardMarkup | None):
    """Parses the multi-line button format."""
    lines = message_text.split('\n')[1:] # Skip the first line (the command)
    buttons = []
    if not lines:
        return None # No buttons provided

    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        try:
            # Split by '|'
            button_text, button_url = line.split('|', 1)
            button_text = button_text.strip()
            button_url = button_url.strip()
            
            # Basic URL validation
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
    """Gets all subscriber IDs from the database."""
    try:
        users_ref = db.collection('subscribers').stream()
        return [user.id for user in users_ref]
    except Exception as e:
        logger.error(f"Could not get subscriber IDs from Firestore: {e}")
        return []


async def do_broadcast(context: ContextTypes.DEFAULT_TYPE, job_data: dict) -> None:
    """
    The main broadcast function (with throttling).
    Called by `button_confirmation_handler`.
    """
    
    # Get data from the job
    admin_id = job_data["admin_id"]
    from_chat_id = job_data["from_chat_id"]
    message_id = job_data["message_id"]
    # 'buttons' is stored as a dict, needs to be converted back to an object
    buttons_dict = job_data.get("buttons")
    buttons_markup = InlineKeyboardMarkup.from_dict(buttons_dict) if buttons_dict else None
    
    operation = "copy" if buttons_markup else "forward" # Smart Send
    
    subscriber_ids = get_subscriber_ids()
    if not subscriber_ids:
        await context.bot.send_message(admin_id, "Broadcast cancelled. The subscriber database is empty.")
        return

    total_users = len(subscriber_ids)
    success_count = 0
    failure_count = 0
    
    # Notify Admin that the broadcast has started
    await context.bot.send_message(
        admin_id,
        f"🚀 *Broadcast Started...*\n\n"
        f"Operation: *{operation.upper()}*\n"
        f"Sending to *{total_users}* users (Rate: {BROADCAST_RATE_LIMIT} msg/sec).\n\n"
        f"You will get a final report when this is complete.",
        parse_mode=ParseMode.MARKDOWN
    )
    
    # Throttled Loop
    for user_id_str in subscriber_ids:
        try:
            user_id_int = int(user_id_str)
            
            if operation == "copy":
                await context.bot.copy_message(
                    chat_id=user_id_int,
                    from_chat_id=from_chat_id,
                    message_id=message_id,
                    reply_markup=buttons_markup
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
            # Auto-remove users who blocked the bot or are deactivated
            if "bot was blocked by the user" in str(e).lower() or "user is deactivated" in str(e).lower():
                logger.info(f"User {user_id_str} blocked the bot. Removing from database...")
                try:
                    db.collection('subscribers').document(user_id_str).delete()
                except Exception as del_e:
                    logger.error(f"Failed to delete user {user_id_str}: {del_e}")
        except Exception as e:
            failure_count += 1
            logger.error(f"Unknown error sending to {user_id_str}: {e}")

        # The Throttling sleep
        await asyncio.sleep(1 / BROADCAST_RATE_LIMIT)

    # Send final report to Admin
    await context.bot.send_message(
        admin_id,
        f"✅ *Broadcast Complete!*\n\n"
        f"Successfully Sent: *{success_count}*\n"
        f"Failed to Send: *{failure_count}*\n"
        f"(Blocked/Deactivated users have been auto-removed)",
        parse_mode=ParseMode.MARKDOWN
    )

# --- BOT HANDLER FUNCTIONS ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /start command and checks group membership."""
    user = update.effective_user
    chat = update.effective_chat
    
    # Ignore /start in group chats
    if chat.type != 'private':
        if str(chat.id) == str(TARGET_GROUP_ID):
            try:
                await update.message.reply_text(
                    f"👋 @{user.username or user.first_name}, please send me /start privately (in a DM)!",
                    reply_to_message_id=update.message.message_id
                )
            except Exception: pass
        return

    logger.info(f"Received /start from User {user.id} (DM)")
    
    # Check if user is in the target group
    membership = await check_group_membership(context, user.id)

    if not membership["is_member"]:
        logger.info(f"User {user.id} is not in the group (Status: {membership['status']}). Subscription rejected.")
        reply_text = (
            "⛔ *Subscription Failed*\n\n"
            "To use this bot and receive broadcasts, you must be a member of our main group.\n\n"
            "Please join the group and then type /start here again."
        )
        
        if membership["status"] == "error":
            # This means the bot is not an admin in the group
            reply_text = "⚠️ A system error occurred while checking your membership. Please try again later."
            # Notify Admin of the critical error
            await context.bot.send_message(
                chat_id=ADMIN_USER_ID,
                text=f"🆘 *CRITICAL BOT ERROR*\n\n"
                     f"Cannot check membership for User `{user.id}` (Group: `{TARGET_GROUP_ID}`).\n\n"
                     f"*Error:* `{membership.get('error_message')}`\n\n"
                     "👉 **ACTION REQUIRED: You MUST make the bot an ADMINISTRATOR in your group!**",
                parse_mode=ParseMode.MARKDOWN
            )
            
        await update.message.reply_text(reply_text, parse_mode=ParseMode.MARKDOWN)
        return

    # --- User is a member, add to DB ---
    try:
        logger.info(f"User {user.id} is in the group (Status: {membership['status']}).")
        
        user_doc_ref = db.collection('subscribers').document(str(user.id))
        user_doc = user_doc_ref.get()

        if not user_doc.exists:
            # Add new user to DB
            user_data = {
                'user_id': user.id,
                'first_name': user.first_name,
                'last_name': user.last_name or '',
                'username': user.username or '',
                'subscribed_at': firestore.SERVER_TIMESTAMP
            }
            user_doc_ref.set(user_data)
            logger.info(f"New subscriber {user.id} added to Firestore.")
            
            await context.bot.send_message(
                chat_id=user.id,
                text="✅ *Subscription Successful!*\n\n"
                     "You have been successfully added to our broadcast list. "
                     "You will now receive all important updates directly.",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            # User is already in DB
            logger.info(f"User {user.id} is already subscribed.")
            await context.bot.send_message(
                chat_id=user.id,
                text="ℹ️ You are already subscribed to our broadcast list."
            )

    except Exception as e:
        logger.error(f"Error in /start handler for User {user.id}: {e}")
        await update.message.reply_text("⚠️ A system error occurred. Please try again later.")

# --- ADMIN COMMANDS ---

async def vip_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays the updated Admin VIP Menu."""
    menu_text = (
        "👑 *Admin VIP Menu (English Version)*\n\n"
        
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

async def send_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /send command. Asks for button confirmation."""
    
    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ *Usage Error:*\nReply to the message you want to send and type `/send`.")
        return
        
    context.chat_data.clear() # Clear any old pending confirmations
    
    message_to_send = update.message.reply_to_message
    buttons = parse_buttons(update.message.text) # Check for multi-line buttons
    subscriber_count = len(get_subscriber_ids())
    operation = "COPY with buttons" if buttons else "FORWARD" # Smart Send

    # Store data temporarily while waiting for confirmation
    context.chat_data['pending_broadcast'] = {
        "admin_id": update.effective_user.id,
        "from_chat_id": message_to_send.chat_id,
        "message_id": message_to_send.message_id,
        # Convert InlineKeyboardMarkup to a dict for storage
        "buttons": buttons.to_dict() if buttons else None,
        "count": subscriber_count,
        "operation": operation
    }

    # Ask Admin for confirmation (with buttons)
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
    """Handles the 'YES'/'NO' button clicks for confirmation."""
    
    query = update.callback_query
    await query.answer() # Acknowledge the button click
    
    data = query.data # "confirm_broadcast_yes" or "confirm_broadcast_no"
    
    # --- Broadcast Confirmation ---
    if data == "confirm_broadcast_yes":
        job_data = context.chat_data.pop('pending_broadcast', None)
        if job_data is None:
            await query.edit_message_text("⚠️ This action has expired or was already confirmed.", reply_markup=None)
            return
        
        await query.edit_message_text("✅ Confirmed. Starting broadcast...", reply_markup=None)
        # Start the broadcast as a background task
        context.application.create_task(do_broadcast(context, job_data))
        
    elif data == "confirm_broadcast_no":
        context.chat_data.pop('pending_broadcast', None)
        await query.edit_message_text("❌ Broadcast Canceled.", reply_markup=None)


# --- Other Admin Commands ---

async def stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/stats - Shows subscriber count."""
    try:
        count = len(get_subscriber_ids())
        await update.message.reply_text(f"📊 *Bot Statistics*\nTotal Subscribers: *{count}*", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"Error getting stats: {e}")

async def delete_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/deluser - Removes a user from the database."""
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
    """/getuser - Shows details for a specific user."""
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
    
    # Run notify_admin_on_startup after the bot is initialized
    application.post_init = notify_admin_on_startup

    # Filter for Admin-only commands
    admin_filter = filters.User(user_id=ADMIN_USER_ID)
    
    # --- Handlers ---
    # Public command
    application.add_handler(CommandHandler("start", start_command, filters=filters.ChatType.PRIVATE))
    
    # Admin commands
    application.add_handler(CommandHandler("vip", vip_menu_handler, filters=admin_filter))
    application.add_handler(CommandHandler("send", send_command, filters=admin_filter))
    application.add_handler(CommandHandler("stats", stats_handler, filters=admin_filter))
    application.add_handler(CommandHandler("deluser", delete_user_handler, filters=admin_filter))
    application.add_handler(CommandHandler("getuser", get_user_handler, filters=admin_filter))
    
    # Confirmation Button Handler
    application.add_handler(CallbackQueryHandler(button_confirmation_handler, pattern="^confirm_"))

    logger.info("Bot (English Version) started successfully... polling...")
    application.run_polling()

if __name__ == '__main__':
    main()

