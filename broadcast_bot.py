# -*- coding: utf-8 -*-
"""
Telegram Broadcast Bot (English Version)
- FULLY UPDATED for python-telegram-bot v20+
- NEW: Handles /start in Private Chat (DM)
- NEW: Checks if the user is a member of the TARGET_GROUP_ID before subscribing.
"""

import logging
import firebase_admin
from firebase_admin import credentials, firestore
from telegram import Update, Bot
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

# --- BOT HANDLER FUNCTIONS (ASYNC) ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles the /start command.
    Checks if it's a Private Message, then verifies group membership.
    """
    user = update.effective_user
    chat = update.effective_chat
    
    # We only want to handle /start from a private chat (DM)
    if chat.type != 'private':
        logger.info(f"Ignoring /start from non-private chat {chat.id}")
        # Optionally, reply in the group to guide the user
        if str(chat.id) == str(TARGET_GROUP_ID):
            try:
                await update.message.reply_text(
                    f"👋 @{user.username or user.first_name}, please send me /start in a private chat (DM) to subscribe!",
                    reply_to_message_id=update.message.message_id
                )
            except Exception as e:
                logger.warning(f"Failed to reply to /start in group: {e}")
        return

    logger.info(f"Received /start in DM from user {user.id}")

    # --- NEW LOGIC: Check if user is in the target group ---
    try:
        # This call requires the bot to be an ADMIN in the TARGET_GROUP_ID
        member = await context.bot.get_chat_member(chat_id=TARGET_GROUP_ID, user_id=user.id)
        
        # User is considered "in the group" if they are member, admin, creator, or restricted (e.g., muted)
        if member.status not in ['member', 'administrator', 'creator', 'restricted']:
            logger.info(f"User {user.id} is NOT in the group (status: {member.status}). Subscription denied.")
            await update.message.reply_text(
                "⛔ *Subscription Failed*\n\n"
                "You must be an active member of our main group to subscribe to broadcasts.\n\n"
                "Please join the group and then type /start here again.",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        # --- User is in the group, proceed with subscription ---
        logger.info(f"User {user.id} is in the group (status: {member.status}). Proceeding with subscription.")
        
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

    except (BadRequest, Forbidden) as e:
        logger.error(f"Error checking chat member status for {user.id} in group {TARGET_GROUP_ID}: {e}")
        await update.message.reply_text(
            "⚠️ An error occurred while verifying your membership. Please try again later.\n\n"
            "(If this persists, please contact an admin.)"
        )
        # Notify the BOT ADMIN that permissions might be wrong
        await context.bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=f"🆘 *CRITICAL BOT ERROR*\n\n"
                 f"Failed to check member status for user `{user.id}` in group `{TARGET_GROUP_ID}`.\n\n"
                 f"*Error:* `{e}`\n\n"
                 "👉 **ACTION REQUIRED: Make sure the bot is an ADMINISTRATOR in the target group!**",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"General error in /start for user {user.id}: {e}")
        await update.message.reply_text("⚠️ A system error occurred. Please try again.")


async def broadcast_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /send command to broadcast a message."""
    user = update.effective_user

    # Admin check
    if user.id != ADMIN_USER_ID:
        logger.warning(f"Unauthorized /send attempt by user {user.id}")
        await update.message.reply_text("⛔ Sorry, you are not authorized to use this command.")
        return

    # Check if the /send command is replying to a message
    if not update.message.reply_to_message:
        logger.info(f"Admin {user.id} used /send without replying to a message.")
        await update.message.reply_text(
            "⚠️ *How to use:*\n"
            "1. Send the message you want to broadcast (text, photo, video, etc.).\n"
            "2. **Reply** to that message and type `/send`.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # Get the message to be broadcasted
    message_to_broadcast = update.message.reply_to_message
    
    # Get all subscribers from Firestore
    try:
        users_ref = db.collection('subscribers').stream()
        subscriber_ids = [user.id for user in users_ref]
        
        if not subscriber_ids:
            await update.message.reply_text("Database is empty. No subscribers found to broadcast to.")
            return

        await update.message.reply_text(
            f"🚀 *Broadcast started...*\n\n"
            f"Forwarding message to *{len(subscriber_ids)}* subscriber(s).",
            parse_mode=ParseMode.MARKDOWN
        )
        
        success_count = 0
        failure_count = 0

        # Loop through each subscriber and forward the message
        for user_id_str in subscriber_ids:
            try:
                user_id_int = int(user_id_str)
                await context.bot.forward_message(
                    chat_id=user_id_int,
                    from_chat_id=message_to_broadcast.chat_id,
                    message_id=message_to_broadcast.message_id
                )
                success_count += 1
            except Exception as e:
                failure_count += 1
                logger.error(f"Failed to forward message to {user_id_str}: {e}")
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

def main() -> None:
    """Start the bot using the new Application builder."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set! Please check your configuration.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Add handlers
    # We only want /start to work in private chats
    application.add_handler(CommandHandler("start", start_command))
    
    # /send command only works for the Admin
    application.add_handler(CommandHandler(
        "send", 
        broadcast_handler, 
        filters=filters.User(user_id=ADMIN_USER_ID)
    ))

    logger.info("Bot started successfully (DM check method) and is polling...")
    application.run_polling()

if __name__ == '__main__':
    main()

