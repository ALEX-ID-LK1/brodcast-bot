# -*- coding: utf-8 -*-
"""
Telegram Broadcast Bot (English Version)
- FULLY UPDATED for python-telegram-bot v20+
- Fixes all ImportError issues (ParseMode, Filters)
- Uses new Application builder pattern (replaces Updater)
- Uses async/await for handlers
"""

import logging
import firebase_admin
from firebase_admin import credentials, firestore
from telegram import Update, Bot
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    filters  # <-- FIX: Replaced 'Filters' with 'filters' (lowercase)
)

# --- START OF CONFIGURATION ---

# 1. Telegram Bot Token (Get from @BotFather)
TELEGRAM_BOT_TOKEN = "8419617505:AAFwnP-m7fbhbcUYFKm85xQmz0FLsyupZbE"

# 2. Admin User ID (Your Telegram User ID)
ADMIN_USER_ID = 6687619682

# 3. Target Group ID (The group ID to monitor for /start commands)
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

# --- BOT HANDLER FUNCTIONS (NOW ASYNC) ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /start command."""
    user = update.effective_user
    chat = update.effective_chat
    
    logger.info(f"Received /start from user {user.id} in chat {chat.id}")

    # Check if the /start command is from the TARGET_GROUP_ID
    if str(chat.id) == str(TARGET_GROUP_ID):
        try:
            # Save user to Firestore
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
                
                # Send a private confirmation message
                await context.bot.send_message(
                    chat_id=user.id,
                    text="✅ *Subscribed Successfully!*\n\n"
                         "You have been successfully subscribed to our broadcast list. "
                         "You will now receive important updates directly to your inbox.",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                logger.info(f"User {user.id} is already subscribed.")
                # Optionally, send a "you are already subscribed" message
                await context.bot.send_message(
                    chat_id=user.id,
                    text="ℹ️ You are already on the broadcast list."
                )

        except Exception as e:
            logger.error(f"Error handling /start command for user {user.id}: {e}")
            try:
                await context.bot.send_message(
                    chat_id=user.id,
                    text="⚠️ An error occurred while subscribing. Please try again later."
                )
            except Exception as e_inner:
                logger.error(f"Failed to send error DM to user {user.id}: {e_inner}")

    else:
        # If /start is in a private chat or another group
        logger.info(f"Ignoring /start from user {user.id} in non-target chat {chat.id}")
        if chat.type == 'private':
            await update.message.reply_text(
                f"👋 Hello! To subscribe, please go to our main group and type /start.\n\n"
                f"(You must be a member of the group with ID: `{TARGET_GROUP_ID}`)",
                parse_mode=ParseMode.MARKDOWN
            )

async def broadcast_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /send command to broadcast a message."""
    user = update.effective_user

    # Admin check (already handled by filter, but good for safety)
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

    # --- FIX: New v20+ way to start the bot ---
    # 1. Create the Application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # 2. Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler(
        "send", 
        broadcast_handler, 
        filters=filters.User(user_id=ADMIN_USER_ID)  # <-- FIX: Use new 'filters.User'
    ))

    # 3. Run the Bot
    logger.info("Bot started successfully (v20+ method) and is polling...")
    application.run_polling()
    # No 'idle()' needed

if __name__ == '__main__':
    main()

