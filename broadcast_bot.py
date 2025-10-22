# -*- coding: utf-8 -*-
"""
Telegram Broadcast Bot (English Version)
- FULLY UPDATED for python-telegram-bot v20+
- NEW FEATURES:
  - /stats: Get total subscriber count.
  - /testsend: Send a test broadcast to the admin.
  - /send with Buttons: Send broadcasts with an Inline Button.
  - /deluser [id]: Manually remove a subscriber.
  - /getuser [id]: Get details of a subscriber.
- CHANGE: /send now COPIES messages instead of forwarding for a cleaner look.
"""

import logging
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    filters
)

# --- START OF CONFIGURATION ---

# 1. Telegram Bot Token (Get from @BotFather)
TELEGRAM_BOT_TOKEN = "8419617505:AAFwnP-m7fbhbcUYFKm85xQmz0FLsyupZbE"

# 2. Admin User ID (Your Telegram User ID)
ADMIN_USER_ID = 6687619682

# 3. Target Group ID (The group to check for membership)
TARGET_GROUP_ID = -1003074965096

# --- END OF CONFIGURATION ---

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
    logger.info("Firebase initialized successfully!")
except Exception as e:
    logger.error(f"Failed to initialize Firebase: {e}")
    exit()

# --- HELPER FUNCTION ---

async def check_group_membership(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> dict:
    """Checks if a user is in the target group. Returns a dictionary."""
    try:
        # This call requires the bot to be an ADMIN in the TARGET_GROUP_ID
        member = await context.bot.get_chat_member(chat_id=TARGET_GROUP_ID, user_id=user_id)
        
        if member.status in ['member', 'administrator', 'creator', 'restricted']:
            return {"is_member": True, "status": member.status}
        else:
            # Statuses like 'left' or 'kicked'
            return {"is_member": False, "status": member.status}
            
    except (BadRequest, Forbidden) as e:
        logger.error(f"Error checking chat member status for {user_id}: {e}")
        # If bot can't check (e.g., not admin), deny subscription
        return {"is_member": False, "status": "error", "error_message": str(e)}
    except Exception as e:
        logger.error(f"General error checking membership for {user_id}: {e}")
        return {"is_member": False, "status": "error", "error_message": str(e)}

# --- BOT HANDLER FUNCTIONS (ASYNC) ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /start command in DMs and verifies group membership."""
    user = update.effective_user
    chat = update.effective_chat
    
    if chat.type != 'private':
        logger.info(f"Ignoring /start from non-private chat {chat.id}")
        if str(chat.id) == str(TARGET_GROUP_ID):
            try:
                await update.message.reply_text(
                    f"👋 @{user.username or user.first_name}, please send me /start in a private chat (DM) to subscribe!",
                    reply_to_message_id=update.message.message_id
                )
            except Exception:
                pass # Ignore if can't reply
        return

    logger.info(f"Received /start in DM from user {user.id}")

    # Check group membership
    membership = await check_group_membership(context, user.id)

    if not membership["is_member"]:
        logger.info(f"User {user.id} is NOT in the group (status: {membership['status']}). Subscription denied.")
        reply_text = (
            "⛔ *Subscription Failed*\n\n"
            "You must be an active member of our main group to subscribe to broadcasts.\n\n"
            "Please join the group and then type /start here again."
        )
        
        # If the bot couldn't check permissions, notify the user and admin
        if membership["status"] == "error":
            reply_text = "⚠️ An error occurred while verifying your membership. Please try again later."
            # Notify the BOT ADMIN that permissions might be wrong
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

    # --- User is in the group, proceed with subscription ---
    try:
        logger.info(f"User {user.id} is in the group (status: {membership['status']}). Proceeding with subscription.")
        
        user_doc_ref = db.collection('subscribers').document(str(user.id))
        user_doc = user_doc_ref.get()

        if not user_doc.exists:
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
            logger.info(f"User {user.id} is already subscribed.")
            await context.bot.send_message(
                chat_id=user.id,
                text="ℹ️ You are already on the broadcast list."
            )

    except Exception as e:
        logger.error(f"General error in /start for user {user.id}: {e}")
        await update.message.reply_text("⚠️ A system error occurred. Please try again.")

# --- ADMIN COMMANDS ---

async def broadcast_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles the /send command.
    Copies the replied-to message to all subscribers.
    Can add an optional Inline Button.
    Usage:
    /send (copies message without button)
    /send [Button Text] | [Button URL] (copies message with button)
    """
    user = update.effective_user

    # Check if the command is replying to a message
    if not update.message.reply_to_message:
        await update.message.reply_text(
            "⚠️ *How to use:*\n"
            "1. Send the message you want to broadcast.\n"
            "2. **Reply** to that message and type `/send`.\n\n"
            "*To add a button:*\n"
            "Reply and type `/send Button Text | https://your-link.com`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    message_to_broadcast = update.message.reply_to_message
    
    # Check for button
    button = None
    if context.args:
        try:
            full_args = " ".join(context.args)
            button_text, button_url = full_args.split('|', 1)
            button_text = button_text.strip()
            button_url = button_url.strip()
            
            if not (button_url.startswith("http://") or button_url.startswith("https://")):
                await update.message.reply_text("⚠️ Invalid URL. It must start with `http://` or `https://`.")
                return
                
            button = InlineKeyboardMarkup([[InlineKeyboardButton(text=button_text, url=button_url)]])
            logger.info(f"Admin {user.id} is broadcasting with a button: {button_text}")
            
        except ValueError:
            await update.message.reply_text(
                "⚠️ *Invalid button format!*\n"
                "Please use: `/send Button Text | https://your-link.com`\n\n"
                "(Note the `|` symbol between the text and the URL)"
            )
            return
        except Exception as e:
            await update.message.reply_text(f"Error parsing button: {e}")
            return

    # Get all subscribers from Firestore
    try:
        users_ref = db.collection('subscribers').stream()
        subscriber_ids = [user.id for user in users_ref]
        
        if not subscriber_ids:
            await update.message.reply_text("Database is empty. No subscribers found.")
            return

        await update.message.reply_text(
            f"🚀 *Broadcast started...*\n\n"
            f"Copying message to *{len(subscriber_ids)}* subscriber(s).",
            parse_mode=ParseMode.MARKDOWN
        )
        
        success_count = 0
        failure_count = 0

        # Loop through each subscriber and copy the message
        for user_id_str in subscriber_ids:
            try:
                user_id_int = int(user_id_str)
                await context.bot.copy_message(
                    chat_id=user_id_int,
                    from_chat_id=message_to_broadcast.chat_id,
                    message_id=message_to_broadcast.message_id,
                    reply_markup=button  # This will be None if no button was created
                )
                success_count += 1
            except Exception as e:
                failure_count += 1
                logger.error(f"Failed to copy message to {user_id_str}: {e}")
                if "bot was blocked by the user" in str(e).lower():
                    logger.info(f"User {user_id_str} blocked the bot. Removing from database.")
                    db.collection('subscribers').document(user_id_str).delete()

        # Send a summary report to the admin
        await context.bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=f"✅ *Broadcast Complete!*\n\n"
                 f"Sent to: *{success_count}* users\n"
                 f"Failed for: *{failure_count}* users",
            parse_mode=ParseMode.MARKDOWN
        )

    except Exception as e:
        logger.error(f"Failed to fetch subscribers from Firestore: {e}")
        await update.message.reply_text(f"An error occurred while fetching subscribers: {e}")

async def test_send_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /testsend command. Copies the replied-to message to the Admin."""
    if not update.message.reply_to_message:
        await update.message.reply_text(
            "⚠️ *How to use:*\n"
            "1. Send the message you want to test.\n"
            "2. **Reply** to that message and type `/testsend`."
        )
        return

    message_to_test = update.message.reply_to_message
    
    # Check for button (same logic as broadcast)
    button = None
    if context.args:
        try:
            full_args = " ".join(context.args)
            button_text, button_url = full_args.split('|', 1)
            button_text = button_text.strip()
            button_url = button_url.strip()
            button = InlineKeyboardMarkup([[InlineKeyboardButton(text=button_text, url=button_url)]])
        except Exception:
            await update.message.reply_text("Invalid button format, but sending test without it.")
            
    try:
        await context.bot.copy_message(
            chat_id=ADMIN_USER_ID,
            from_chat_id=message_to_test.chat_id,
            message_id=message_to_test.message_id,
            reply_markup=button
        )
        await update.message.reply_text("✅ Test message sent to your DM.")
    except Exception as e:
        logger.error(f"Failed to send test message: {e}")
        await update.message.reply_text(f"Failed to send test message: {e}")

async def stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /stats command. Counts all subscribers."""
    try:
        users_ref = db.collection('subscribers').stream()
        count = len(list(users_ref))
        await update.message.reply_text(
            f"📊 *Bot Statistics*\n\n"
            f"Total Subscribers: *{count}*",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        await update.message.reply_text(f"Error fetching stats: {e}")

async def delete_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /deluser [user_id]. Manually deletes a user from Firestore."""
    if not context.args:
        await update.message.reply_text("Usage: `/deluser [USER_ID]`")
        return

    user_id_to_delete = context.args[0]
    
    if not user_id_to_delete.isdigit():
        await update.message.reply_text("Invalid User ID. It must be a number.")
        return
        
    try:
        doc_ref = db.collection('subscribers').document(user_id_to_delete)
        doc = doc_ref.get()
        
        if doc.exists:
            doc_ref.delete()
            await update.message.reply_text(f"✅ User {user_id_to_delete} has been successfully deleted from the database.")
            logger.info(f"Admin manually deleted user {user_id_to_delete}")
        else:
            await update.message.reply_text(f"⚠️ User {user_id_to_delete} not found in the database.")
            
    except Exception as e:
        logger.error(f"Failed to delete user {user_id_to_delete}: {e}")
        await update.message.reply_text(f"Error deleting user: {e}")

async def get_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /getuser [user_id]. Fetches user details from Firestore."""
    if not context.args:
        await update.message.reply_text("Usage: `/getuser [USER_ID]`")
        return

    user_id_to_get = context.args[0]

    if not user_id_to_get.isdigit():
        await update.message.reply_text("Invalid User ID. It must be a number.")
        return

    try:
        doc_ref = db.collection('subscribers').document(user_id_to_get)
        doc = doc_ref.get()
        
        if doc.exists:
            data = doc.to_dict()
            # Format subscription date
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
            await update.message.reply_text(f"⚠️ User {user_id_to_get} not found in the database.")
            
    except Exception as e:
        logger.error(f"Failed to get user {user_id_to_get}: {e}")
        await update.message.reply_text(f"Error getting user: {e}")

def main() -> None:
    """Start the bot using the new Application builder."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set! Please check your configuration.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Create an admin-only filter for convenience
    admin_filter = filters.User(user_id=ADMIN_USER_ID)

    # Add handlers
    # Public command (only works in DM)
    application.add_handler(CommandHandler("start", start_command, filters=filters.ChatType.PRIVATE))
    
    # Admin commands
    application.add_handler(CommandHandler("send", broadcast_handler, filters=admin_filter))
    application.add_handler(CommandHandler("testsend", test_send_handler, filters=admin_filter))
    application.add_handler(CommandHandler("stats", stats_handler, filters=admin_filter))
    application.add_handler(CommandHandler("deluser", delete_user_handler, filters=admin_filter))
    application.add_handler(CommandHandler("getuser", get_user_handler, filters=admin_filter))

    logger.info("Bot started successfully (v20+ with Admin Features) and is polling...")
    application.run_polling()

if __name__ == '__main__':
    main()

