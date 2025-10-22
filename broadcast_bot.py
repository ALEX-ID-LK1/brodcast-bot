# -*- coding: utf-8 -*-
"""
Telegram Broadcast Bot (English Version)
- Updated to fix SyntaxError on line 159.
"""

import logging
import firebase_admin
from firebase_admin import credentials, firestore
from telegram import Update, Bot, ParseMode, ForceReply
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

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
    # If Firebase fails, we can't really continue.
    exit()

# --- BOT HANDLER FUNCTIONS ---

def start_command(update: Update, context: CallbackContext) -> None:
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
                context.bot.send_message(
                    chat_id=user.id,
                    text="✅ *Subscribed Successfully!*\n\n"
                         "You have been successfully subscribed to our broadcast list. "
                         "You will now receive important updates directly to your inbox.",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                logger.info(f"User {user.id} is already subscribed.")
                # Optionally, send a "you are already subscribed" message
                context.bot.send_message(
                    chat_id=user.id,
                    text="ℹ️ You are already on the broadcast list."
                )

        except Exception as e:
            logger.error(f"Error handling /start command for user {user.id}: {e}")
            # Try to inform the user privately that an error occurred
            try:
                context.bot.send_message(
                    chat_id=user.id,
                    text="⚠️ An error occurred while subscribing. Please try again later."
                )
            except Exception as e_inner:
                logger.error(f"Failed to send error DM to user {user.id}: {e_inner}")

    else:
        # If /start is in a private chat or another group
        logger.info(f"Ignoring /start from user {user.id} in non-target chat {chat.id}")
        if chat.type == 'private':
            update.message.reply_text(
                f"👋 Hello! To subscribe, please go to our main group and type /start.\n\n"
                f"(You must be a member of the group with ID: `{TARGET_GROUP_ID}`)",
                parse_mode=ParseMode.MARKDOWN
            )

def broadcast_handler(update: Update, context: CallbackContext) -> None:
    """Handles the /send command to broadcast a message."""
    user = update.effective_user

    # Only allow the ADMIN_USER_ID to use this command
    if user.id != ADMIN_USER_ID:
        logger.warning(f"Unauthorized /send attempt by user {user.id}")
        update.message.reply_text("⛔ Sorry, you are not authorized to use this command.")
        return

    # Check if the /send command is replying to a message
    if not update.message.reply_to_message:
        logger.info(f"Admin {user.id} used /send without replying to a message.")
        update.message.reply_text(
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
            update.message.reply_text("Database is empty. No subscribers found to broadcast to.")
            return

        update.message.reply_text(
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
                context.bot.forward_message(
                    chat_id=user_id_int,
                    from_chat_id=message_to_broadcast.chat_id,
                    message_id=message_to_broadcast.message_id
                )
                success_count += 1
            except Exception as e:
                failure_count += 1
                logger.error(f"Failed to forward message to {user_id_str}: {e}")
                # If a user blocked the bot, we can remove them
                if "bot was blocked by the user" in str(e).lower():
                    logger.info(f"User {user_id_str} blocked the bot. Removing from database.")
                    db.collection('subscribers').document(user_id_str).delete()

        # Send a summary report to the admin
        context.bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=f"✅ *Broadcast Complete!*\n\n"
                 f"Sent to: *{success_count}* users\n"
                 f"Failed for: *{failure_count}* users",
            parse_mode=ParseMode.MARKDOWN
        )

    except Exception as e:
        logger.error(f"Failed to fetch subscribers from Firestore: {e}")
        update.message.reply_text(f"An error occurred while fetching subscribers: {e}")

def main() -> None:
    """Start the bot."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set! Please check your configuration.")
        return

    updater = Updater(TELEGRAM_BOT_TOKEN)
    dispatcher = updater.dispatcher

    # Add handlers
    dispatcher.add_handler(CommandHandler("start", start_command))
    dispatcher.add_handler(CommandHandler("send", broadcast_handler, filters=Filters.user(user_id=ADMIN_USER_ID)))

    # Start the Bot
    updater.start_polling()
    logger.info("Bot started successfully and is polling for updates...")
    updater.idle()

if __name__ == '__main__':
    main()

