import os
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import firebase_admin
from firebase_admin import credentials, firestore
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.error import Forbidden, BadRequest

# --- Configuration ---
TELEGRAM_BOT_TOKEN = "8419617505:AAFwnP-m7fbhbcUYFKm85xQmz0FLsyupZbE"
ADMIN_USER_ID = 6687619682
TARGET_GROUP_ID = -1003074965096

# --- Firebase Setup ---
try:
    cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("✅ Successfully connected to Firebase.")
except Exception as e:
    print(f"❌ Error connecting to Firebase: {e}")
    exit()

# --- Logging Setup ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Web Server (for Koyeb) ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running successfully on Koyeb!")
        
def start_web_server():
    port = int(os.getenv("PORT", 8080))  # Koyeb sets this automatically
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    print(f"🌐 Web server listening on port {port}")
    server.serve_forever()

# --- Core Functions ---
async def save_user_to_db(user):
    try:
        user_ref = db.collection('users').document(str(user.id))
        user_data = {
            'user_id': user.id,
            'username': user.username,
            'first_name': user.first_name,
            'last_active': firestore.SERVER_TIMESTAMP
        }
        user_ref.set(user_data, merge=True)
        logger.info(f"User {user.id} ({user.username}) saved/updated in DB.")
        return True
    except Exception as e:
        logger.error(f"Error saving user {user.id}: {e}")
        return False


# --- Command Handlers ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.message.chat.type == 'private':
        saved = await save_user_to_db(user)
        if saved:
            await update.message.reply_text(
                f"Hello {user.first_name}!\n\nYou have been successfully registered for updates."
            )
        else:
            await update.message.reply_text("An error occurred during registration.")
    else:
        try:
            await context.bot.send_message(
                chat_id=user.id,
                text=f"Hello {user.first_name}! Please send /start to me privately to register."
            )
        except Forbidden:
            logger.warning(f"Cannot DM {user.id} (bot blocked).")
        except BadRequest:
            logger.warning(f"Cannot find chat with {user.id}.")


async def new_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat_id != TARGET_GROUP_ID:
        return

    for user in update.message.new_chat_members:
        if not user.is_bot:
            logger.info(f"New member {user.id}")
            await save_user_to_db(user)
            try:
                await context.bot.send_message(
                    chat_id=user.id,
                    text=f"Welcome {user.first_name}! Send /start here to subscribe for updates."
                )
            except Exception as e:
                logger.warning(f"Cannot message new user {user.id}: {e}")


async def send_broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_USER_ID:
        await update.message.reply_text("You are not authorized.")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a message with /send to broadcast it.")
        return

    try:
        users_stream = db.collection('users').stream()
        user_ids = [u.id for u in users_stream]
    except Exception as e:
        await update.message.reply_text(f"Error loading users: {e}")
        return

    success = 0
    failed = 0
    msg = await update.message.reply_text(f"Broadcasting to {len(user_ids)} users...")

    for user_id_str in user_ids:
        try:
            user_id = int(user_id_str)
            await context.bot.forward_message(
                chat_id=user_id,
                from_chat_id=update.message.reply_to_message.chat_id,
                message_id=update.message.reply_to_message.message_id
            )
            success += 1
        except Exception:
            failed += 1

    await context.bot.edit_message_text(
        chat_id=update.message.chat_id,
        message_id=msg.message_id,
        text=f"Broadcast complete.\n✅ Sent: {success}\n❌ Failed: {failed}"
    )

# --- Main ---
def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("send", send_broadcast_command))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member_handler))

    # Run HTTP server in background (for Koyeb)
    threading.Thread(target=start_web_server, daemon=True).start()

    print("🤖 Bot is starting...")
    application.run_polling()


if __name__ == "__main__":
    main()                         "To receive important updates and broadcasts, "
                         "please reply /start here in our private chat."
                )
            except Forbidden:
                logger.warning(f"Cannot send DM to new user {user.id} (Bot is blocked).")
            except BadRequest:
                logger.warning(f"Cannot find chat with new user {user.id} (User hasn't started the bot).")


async def send_broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles the /send command (Admin only) to broadcast a replied-to message.
    """
    user = update.effective_user

    # 1. Check if the user is the Admin
    if user.id != ADMIN_USER_ID:
        await update.message.reply_text("You are not authorized to use this command.")
        return

    # 2. Check if the command is a reply to another message
    if not update.message.reply_to_message:
        await update.message.reply_text("Please use this command as a reply to the message you want to broadcast.")
        return

    message_to_forward = update.message.reply_to_message
    
    # 3. Get all user IDs from Firebase
    try:
        users_stream = db.collection('users').stream()
        user_ids = [user.id for user in users_stream]
    except Exception as e:
        logger.error(f"Error fetching user IDs from Firebase: {e}")
        await update.message.reply_text(f"Error fetching users from database: {e}")
        return

    if not user_ids:
        await update.message.reply_text("There are no users registered to broadcast to.")
        return

    # 4. Start broadcasting
    success_count = 0
    failure_count = 0
    
    status_message = await update.message.reply_text(f"Starting broadcast to {len(user_ids)} users...")

    for user_id_str in user_ids:
        user_id = int(user_id_str)
        try:
            await context.bot.forward_message(
                chat_id=user_id,
                from_chat_id=message_to_forward.chat_id,
                message_id=message_to_forward.message_id
            )
            success_count += 1
        except Forbidden:
            logger.warning(f"Failed to send to {user_id} (Bot blocked).")
            failure_count += 1
            # Optional: You could remove this user from the DB
            # db.collection('users').document(str(user_id)).delete()
        except BadRequest as e:
            logger.warning(f"Failed to send to {user_id}: {e}")
            failure_count += 1
        except Exception as e:
            logger.error(f"Unknown error sending to {user_id}: {e}")
            failure_count += 1

    # 5. Send the final report to the Admin
    await context.bot.edit_message_text(
        text=f"Broadcast Complete!\n\n"
             f"Successfully sent: {success_count}\n"
             f"Failed to send: {failure_count}",
        chat_id=update.message.chat_id,
        message_id=status_message.message_id
    )
    logger.info(f"Broadcast finished. Success: {success_count}, Failed: {failure_count}")


def main():
    """Starts the bot."""
    
    # Check if config values were entered (although they are pre-filled now)
    if TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        print("Error: TELEGRAM_BOT_TOKEN is not set.")
        print("Please edit broadcast_bot.py and add your bot token.")
        return

    # Create the Application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # --- Add Handlers ---
    
    # /start command in Private Chats (DMs)
    application.add_handler(CommandHandler("start", start_command, filters=filters.ChatType.PRIVATE))
    
    # /start command in Group Chats
    application.add_handler(CommandHandler("start", start_command, filters=filters.ChatType.GROUPS))

    # /send command (for the Admin)
    application.add_handler(CommandHandler("send", send_broadcast_command))

    # New members joining
    # (The bot needs admin rights in the group for this to work)
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member_handler))

    # Run the bot
    print("Bot is starting...")
    application.run_polling()


if __name__ == "__main__":
    main()

