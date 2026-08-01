from asyncio import create_task, sleep as asleep
from urllib.parse import urlparse
from Backend.logger import LOGGER
from Backend import db
from Backend.config import Telegram
from Backend.helper.custom_filter import CustomFilters
from Backend.helper.encrypt import decode_string
from Backend.helper.metadata import metadata
from Backend.helper.pyro import apply_channel_branding, get_readable_file_size, remove_urls
from Backend.pyrofork import StreamBot
from pyrogram import filters, Client
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from os import path as ospath
from pyrogram.errors import FloodWait
from pyrogram.enums.parse_mode import ParseMode
from themoviedb import aioTMDb
from asyncio import Queue, create_task
from os import execl as osexecl
from asyncio import create_subprocess_exec, gather
from sys import executable
from aiofiles import open as aiopen
from pyrogram import enums


tmdb = aioTMDb(key=Telegram.TMDB_API, language="en-US", region="US")
# Initialize database connection
import random
import string
from passlib.context import CryptContext
from datetime import datetime, timedelta

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

def generate_password(length=10):
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

@StreamBot.on_message(filters.command("user") & filters.private & CustomFilters.owner)
async def create_user(bot: Client, message: Message):
    try:
        args = message.text.split()
        if len(args) != 3:
            await message.reply_text("❌ Usage: `/user <username> <expiry_days>`", parse_mode=ParseMode.MARKDOWN)
            return

        username = args[1]
        expiry_days = int(args[2])

        users_collection = db.db["auth_users"]  # Use the Tracking database

        # Check if username already exists
        existing_user = await users_collection.find_one({"username": username})
        if existing_user:
            await message.reply_text(f"❌ User `{username}` already exists!", parse_mode=ParseMode.MARKDOWN)
            return

        password = generate_password()
        hashed_password = pwd_ctx.hash(password)
        expires_at = datetime.utcnow() + timedelta(days=expiry_days)

        user_data = {
            "username": username,
            "password": hashed_password,
            "expires_at": expires_at
        }
        await users_collection.insert_one(user_data)

        await message.reply_text(
            f"✅ User created!\n\n"
            f"👤 Username: `{username}`\n"
            f"🔑 Password: `{password}`\n"
            f"🕒 Expires in: `{expiry_days}` days\n"
            f"📅 Expiry Date: `{expires_at.strftime('%Y-%m-%d %H:%M:%S')} UTC`",
            parse_mode=ParseMode.MARKDOWN
        )

    except Exception as e:
        LOGGER.error(f"Error in /user command: {e}")
        await message.reply_text("❌ An error occurred while creating the user.")

@StreamBot.on_message(filters.command('restart') & filters.private & CustomFilters.owner)
async def restart(bot: Client, message: Message):
    try:
        # Notify the user that the bot is restarting
        
        restart_message = await message.reply_text(
    '<blockquote>⚙️ Restarting Backend API... \n\n✨ Please wait as we bring everything back online! 🚀</blockquote>',
        quote=True,
        parse_mode=enums.ParseMode.HTML
        )
        LOGGER.info("Restart initiated by owner.")

        # Run the update script
        proc1 = await create_subprocess_exec('python3', 'update.py')
        await gather(proc1.wait())

        # Save restart message details for notification after restart
        async with aiopen(".restartmsg", "w") as f:
            await f.write(f"{restart_message.chat.id}\n{restart_message.id}\n")

        # Restart the bot process
        osexecl(executable, executable, "-m", "Backend")

    except Exception as e:
        LOGGER.error(f"Error during restart: {e}")
        await message.reply_text("**❌ Failed to restart. Check logs for details.**")




async def delete_messages_after_delay(messages):
    await asleep(300)  
    for msg in messages:
        try:
            await msg.delete()
        except Exception as e:
            LOGGER.error(f"Error deleting message {msg.id}: {e}")
        await asleep(2)  


async def is_user_joined(bot: Client, user_id: int) -> bool:
    """Check karo ki user ne FORCE_JOIN_CHANNEL join kiya hai ya nahi."""
    channel = Telegram.FORCE_JOIN_CHANNEL
    if not channel:
        return True  # Force join off hai
    try:
        member = await bot.get_chat_member(channel, user_id)
        # Banned/left users ko block karo
        from pyrogram.enums import ChatMemberStatus
        if member.status in [
            ChatMemberStatus.BANNED,
            ChatMemberStatus.LEFT,
            ChatMemberStatus.RESTRICTED,
        ]:
            return False
        return True
    except Exception:
        return False


@StreamBot.on_message(filters.command('start') & filters.private)
async def start(bot: Client, message: Message):
    LOGGER.info(f"Received command: {message.text}")
    
    command_part = message.text.split('start ')[-1]
    
    if command_part.startswith("file_"):
        usr_cmd = command_part[len("file_"):].strip()
        
        parts = usr_cmd.split("_")
        
        if len(parts) == 2:
            try:
                tmdb_id, quality = parts
                tmdb_id = int(tmdb_id)
                season = None
                quality_details = await db.get_quality_details(tmdb_id, quality)
            except ValueError:
                LOGGER.error(f"Error parsing movie command: {usr_cmd}")
                await message.reply_text("Invalid command format for movie.")
                return
        
        elif len(parts) == 3:
            try:
                tmdb_id, season, quality = parts
                tmdb_id = int(tmdb_id)
                season = int(season)
                quality_details = await db.get_quality_details(tmdb_id, quality, season)
            except ValueError:
                LOGGER.error(f"Error parsing TV show command: {usr_cmd}")
                await message.reply_text("Invalid command format for TV show.")
                return
        elif len(parts) == 4:
            try:
                tmdb_id, season, episode, quality = parts
                tmdb_id = int(tmdb_id)
                season = int(season)
                episode = int(episode) if episode.isdigit() else episode
                quality_details = await db.get_quality_details(tmdb_id, quality, season, episode)
            except ValueError:
                LOGGER.error(f"Error parsing TV show command: {usr_cmd}")
                await message.reply_text("Invalid command format for TV show.")
                return

        else:
            await message.reply_text("Invalid command format.")
            return

        sent_messages = []

        # --- Force Join Check ---
        if Telegram.FORCE_JOIN_CHANNEL:
            joined = await is_user_joined(bot, message.from_user.id)
            if not joined:
                channel = Telegram.FORCE_JOIN_CHANNEL
                # Channel username nikalo (invite link ya @username)
                try:
                    chat = await bot.get_chat(channel)
                    invite = f"https://t.me/{chat.username}" if chat.username else await bot.export_chat_invite_link(channel)
                    ch_name = chat.title or "Our Channel"
                except Exception:
                    invite = f"https://t.me/{Telegram.CHANNEL_USERNAME}"
                    ch_name = "Our Channel"

                return await message.reply_text(
                    f"⚠️ **Channel Join Required!**\n\n"
                    f"📌 Humari movies & series paane ke liye pehle hamara channel join karo:\n"
                    f"👉 **{ch_name}**\n\n"
                    f"Channel join karne ke baad 🔁 Retry karo.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton(
                            f"✅ Join {ch_name}",
                            url=invite
                        )
                    ]])
                )
        # --- Force Join Check End ---
        for detail in quality_details:
            decoded_data = await decode_string(detail['id'])
            channel = f"-100{decoded_data['chat_id']}"
            msg_id = decoded_data['msg_id']
            name = detail['name']
            if "\\n" in name and name.endswith(".mkv"):
                name = name.rsplit(".mkv", 1)[0].replace("\\n", "\n")
            try:
                file = await bot.get_messages(int(channel), int(msg_id))
                media = file.document or file.video
                if media:
                    sent_msg = await message.reply_cached_media(
                        file_id=media.file_id,
                        caption=f'{name}'
                    )
                    sent_messages.append(sent_msg)
                    await asleep(1)
            except FloodWait as e:
                LOGGER.info(f"Sleeping for {e.value}s")
                await asleep(e.value)
                await message.reply_text(f"Got Floodwait of {e.value}s")
            except Exception as e:
                LOGGER.error(f"Error retrieving/sending media: {e}")
                await message.reply_text("Error retrieving media.")

        if sent_messages:
            warning_msg = await message.reply_text(
                "Forward these files to your saved messages. These files will be deleted from the bot within 5 minutes."
            )
            sent_messages.append(warning_msg)
            create_task(delete_messages_after_delay(sent_messages))
    else:
        await message.reply_text(
            "Welcome to @Filmy4uhdbot! 🎬\n\n"
            "I am here to provide direct download links for movies & series from filmy4uhd.site .\n"
            "📥 Just send a file link to get started!"
        )


@StreamBot.on_message(filters.command('help') & filters.private)
async def help_command(bot: Client, message: Message):
    try:
        is_owner = False
        if message.from_user:
            is_owner = (message.from_user.id == Telegram.OWNER_ID)
        elif message.sender_chat:
            is_owner = (message.sender_chat.id == Telegram.OWNER_ID)

        if is_owner:
            help_text = (
                "🤖 **Available Commands:**\n\n"
                "🎬 **/start** - Start the bot & get welcome message.\n"
                "ℹ️ **/help** - Show this help message.\n\n"
                "⚙️ **Admin Commands (Owner Only):**\n"
                "👤 **/user `<username> <expiry_days>`** - Create a temporary user.\n"
                "♻️ **/restart** - Update code from GitHub and restart the bot.\n"
                "📋 **/log** - Get the system log file (`log.txt`).\n"
                "💬 **/caption** - Toggle Caption vs Filename mode for indexing.\n"
                "📽️ **/tmdb** - Toggle metadata provider between TMDb and IMDb.\n"
                "🆔 **/set `<TMDb-ID>`** - Set default TMDb ID fallback (or `/set` to clear).\n"
                "🗑️ **/delete `<URL>`** - Delete a movie/TV show from the database."
            )
        else:
            help_text = (
                "🤖 **Available Commands:**\n\n"
                "🎬 **/start** - Start the bot & get welcome message.\n"
                "ℹ️ **/help** - Show this help message."
            )
        await message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        LOGGER.error(f"Error in /help command: {e}")



@StreamBot.on_message(filters.command('log') & filters.private & CustomFilters.owner)
async def get_logs(bot: Client, message: Message):
    try:
        path = ospath.abspath('log.txt')
        return await message.reply_document(
        document=path, quote=True, disable_notification=True
        )
    except Exception as e:
        print(f"An error occurred: {e}")




# Global queue for processing file updates
import asyncio
from asyncio import Lock

file_queue = Queue()
db_lock = Lock()

# Debounce tasks store करने के लिए
# Key: (tmdb_id, media_type, season_number, episode_number)
notification_tasks = {}


async def send_channel_notification(metadata_info):
    """
    FORCE_JOIN_CHANNEL पर नई फ़ाइल अपलोड का सुंदर नोटिफिकेशन भेजता है।
    इसमें TMDb/IMDb डिटेल्स, इमेज, उपलब्ध क्वालिटीज़ और वेबसाइट का सही पाथ-लिंक शामिल होता है।
    यदि पहले से ही पोस्ट मौजूद है तो उसे एडिट करता है।
    """
    channel = Telegram.FORCE_JOIN_CHANNEL
    if not channel:
        LOGGER.info("No FORCE_JOIN_CHANNEL set, skipping notification.")
        return

    try:
        tmdb_id = int(metadata_info['tmdb_id'])
        media_type = metadata_info['media_type']

        # Database से अपडेटेड डिटेल्स फ़ेच करें
        media_details = await db.get_media_details(tmdb_id)
        if not media_details:
            LOGGER.warning(f"Could not fetch details for tmdb_id {tmdb_id} from database.")
            return

        title = media_details.get('title', 'Unknown Title')
        year = media_details.get('release_year', 0)
        rating = media_details.get('rating', 0.0)
        
        genres_list = media_details.get('genres', [])
        genres = ", ".join(genres_list) if genres_list else "N/A"
        
        languages_list = media_details.get('languages', [])
        languages = ", ".join(languages_list) if languages_list else "Hindi"
        
        rip = media_details.get('rip', 'Blu-ray')
        
        description = media_details.get('description', '')
        if len(description) > 300:
            description = description[:297] + "..."

        # सभी उपलब्ध क्वालिटीज़ (Qualities) निकालें
        qualities = set()
        existing_msg_id = None

        if media_type == "movie":
            existing_msg_id = media_details.get('channel_message_id')
            for item in media_details.get('telegram', []):
                qualities.add(item.get('quality', 'HD'))
        else:
            # TV show case: सिर्फ इसी सीजन और एपिसोड की क्वालिटी और message ID निकालें
            season_num = metadata_info.get('season_number')
            episode_num = metadata_info.get('episode_number')
            for season in media_details.get('seasons', []):
                if season.get('season_number') == season_num:
                    for episode in season.get('episodes', []):
                        if str(episode.get('episode_number')) == str(episode_num):
                            existing_msg_id = episode.get('channel_message_id')
                            for item in episode.get('telegram', []):
                                qualities.add(item.get('quality', 'HD'))

        qualities_str = ", ".join(sorted(list(qualities))) if qualities else "HD"

        # मीडिया टाइप के अनुसार टाइटल तैयार करें
        if media_type == "tv" and 'season_number' in metadata_info and 'episode_number' in metadata_info:
            ep_num_str = str(metadata_info['episode_number'])
            ep_title = metadata_info.get('episode_title', f"Episode {ep_num_str}")
            if '-' in ep_num_str or 'to' in ep_num_str or 'combined' in ep_num_str.lower():
                title_str = f"🎥 **Title:** {title} - S{metadata_info['season_number']} E{ep_num_str} ({ep_title}) [{year}]"
            else:
                title_str = f"🎥 **Title:** {title} - S{metadata_info['season_number']}E{ep_num_str} ({ep_title}) [{year}]"
        else:
            title_str = f"🎥 **Title:** {title} ({year})"

        # Vercel फ़्रंटएंड के अनुसार पाथ-लिंक बनाएं
        path_type = "mov" if media_type == "movie" else "ser"
        website_link = f"https://filmy4uhd.vercel.app/{path_type}/{tmdb_id}"

        # सुंदर कैप्शन/पोस्ट
        caption = (
            f"🎬 **New Upload Alert!** 🎬\n\n"
            f"{title_str}\n"
            f"⭐️ **Rating:** {rating}/10\n"
            f"🎭 **Genres:** {genres}\n"
            f"🔊 **Languages:** {languages}\n"
            f"💿 **Quality:** {qualities_str} [{rip}]\n\n"
            f"📝 **Plot:** {description}\n\n"
            f"🔗 **Watch/Download Online:**\n"
            f"👉 {website_link}"
        )

        image_url = media_details.get('backdrop') or media_details.get('poster')

        reply_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("🌐 Watch/Download Now", url=website_link)
        ]])

        edited = False
        if existing_msg_id:
            try:
                if image_url:
                    await StreamBot.edit_message_caption(
                        chat_id=int(channel),
                        message_id=int(existing_msg_id),
                        caption=caption,
                        reply_markup=reply_markup
                    )
                else:
                    await StreamBot.edit_message_text(
                        chat_id=int(channel),
                        message_id=int(existing_msg_id),
                        text=caption,
                        reply_markup=reply_markup
                    )
                edited = True
                LOGGER.info(f"Notification edited successfully in {channel} (Message ID: {existing_msg_id})")
            except Exception as e:
                LOGGER.warning(f"Failed to edit message {existing_msg_id}: {e}. Sending new message instead...")
                existing_msg_id = None

        if not edited:
            if image_url:
                sent_msg = await StreamBot.send_photo(
                    chat_id=int(channel),
                    photo=image_url,
                    caption=caption,
                    reply_markup=reply_markup
                )
            else:
                sent_msg = await StreamBot.send_message(
                    chat_id=int(channel),
                    text=caption,
                    reply_markup=reply_markup,
                    disable_web_page_preview=False
                )
            # Database में मैसेज ID सेव करें
            await db.update_channel_message_id(
                tmdb_id=tmdb_id,
                media_type=media_type,
                message_id=sent_msg.id,
                season_number=metadata_info.get('season_number'),
                episode_number=metadata_info.get('episode_number')
            )
            LOGGER.info(f"New notification sent successfully to {channel} for {title} (Message ID: {sent_msg.id})")
    except Exception as e:
        LOGGER.error(f"Failed to send channel notification: {e}")


async def debounce_notification(metadata_info):
    """
    अगर एक साथ कई क्वालिटीज़ अपलोड की जा रही हैं, तो उन्हें ग्रुप करता है
    ताकि चैनल पर केवल 1 ही समेकित नोटिफिकेशन भेजा जाए।
    """
    tmdb_id = int(metadata_info['tmdb_id'])
    media_type = metadata_info['media_type']
    season_number = metadata_info.get('season_number', None)
    episode_number = metadata_info.get('episode_number', None)
    
    # Unique task key
    task_key = (tmdb_id, media_type, season_number, str(episode_number))

    # अगर पहले से कोई पेंडिंग नोटिफिकेशन शेड्यूल्ड है, उसे कैंसिल करें
    if task_key in notification_tasks:
        notification_tasks[task_key].cancel()

    # नया डीलेड (delayed) टास्क बनाएं
    async def delayed_send():
        try:
            # 20 सेकंड वेट करें (ताकि अन्य क्वालिटीज़ भी इंडेक्स हो जाएं)
            await asyncio.sleep(20)
            await send_channel_notification(metadata_info)
        except asyncio.CancelledError:
            # नया फाइल आने के कारण यह टास्क कैंसिल हो गया है
            pass
        finally:
            # डिक्शनरी से टास्क रिमूव करें
            if notification_tasks.get(task_key) == current_task:
                notification_tasks.pop(task_key, None)

    current_task = asyncio.create_task(delayed_send())
    notification_tasks[task_key] = current_task


async def process_file():
    while True:
        metadata_info, hash, channel, msg_id, size, title = await file_queue.get()
        async with db_lock:
            updated_id = await db.insert_media(metadata_info, hash=hash, channel=channel, msg_id=msg_id, size=size, name=title)
            if updated_id:
                LOGGER.info(f"{metadata_info['media_type']} updated with ID: {updated_id}")
                # Grouped/Debounced notification भेजें
                await debounce_notification(metadata_info)
            else:
                LOGGER.info("Update failed due to validation errors.")
        file_queue.task_done()

for _ in range(1):
    create_task(process_file())


@StreamBot.on_message(filters.channel & (filters.document | filters.video))
async def file_receive_handler(bot: Client, message: Message):
    if str(message.chat.id) in Telegram.AUTH_CHANNEL:
        try:
            if message.video or message.document.mime_type.startswith("video/"):
                file = message.video or message.document
                if Telegram.USE_CAPTION and message.caption:
                    title = message.caption.replace("\n", "\\n")
                else:
                    title = file.file_name or file.file_id

                msg_id = message.id
                hash = file.file_unique_id[:6]
                size = get_readable_file_size(file.file_size)
                channel = str(message.chat.id).replace("-100", "")
                
                # metadata() ke andar ab clean_movie_title() apply hoti hai
                metadata_info = await metadata(title, file)
                if metadata_info is None:
                    return await message.reply_text("> Not added check log")

                # सभी बाहरी @username हटाकर @skysetx01 brand लगाओ (DB में यही जाएगा)
                title = apply_channel_branding(title)
                if not title.endswith(('.mkv', '.mp4')):
                    title += '.mkv'
                await file_queue.put((metadata_info, hash, int(channel), msg_id, size, title))
            else:
                await message.reply_text("> Not supported")
        except FloodWait as e:
            LOGGER.info(f"Sleeping for {str(e.value)}s")
            await asleep(e.value)
            await message.reply_text(text=f"Got Floodwait of {str(e.value)}s",
                                disable_web_page_preview=True, parse_mode=ParseMode.MARKDOWN)
    else:
        await message.reply(text="> Channel is not in AUTH_CHANNEL")


@Client.on_message(filters.command('caption') & filters.private & CustomFilters.owner)
async def toggle_caption(bot: Client, message: Message):
    try:
        Telegram.USE_CAPTION = not Telegram.USE_CAPTION
        await message.reply_text(f"Now Bot Uses {'Caption' if Telegram.USE_CAPTION else 'Filename'}")
    except Exception as e:
        print(f"An error occurred: {e}")

@Client.on_message(filters.command('tmdb') & filters.private & CustomFilters.owner)
async def toggle_tmdb(bot: Client, message: Message):
    try:
        Telegram.USE_TMDB = not Telegram.USE_TMDB
        await message.reply_text(f"Now Bot Uses {'TMDB' if Telegram.USE_TMDB else 'IMDB'}")
    except Exception as e:
        print(f"An error occurred: {e}")

@Client.on_message(filters.command('set') & filters.private & CustomFilters.owner)
async def set_id(bot: Client, message: Message):

    url_part = message.text.split()[1:]  # Skip the command itself

    try:
        if len(url_part) == 1:

            Telegram.USE_DEFAULT_ID = url_part[0]  # Get the first element
            await message.reply_text(f"Now Bot Uses Default URL: {Telegram.USE_DEFAULT_ID}")
        else:
            # Remove the default ID
            Telegram.USE_DEFAULT_ID = None
            await message.reply_text("Removed default ID.")
    except Exception as e:
        await message.reply_text(f"An error occurred: {e}")





@Client.on_message(filters.command('delete') & filters.private & CustomFilters.owner)
async def delete(bot: Client, message: Message):
    try:
        split_text = message.text.split()
        if len(split_text) != 2:
            return await message.reply_text("Use this format: /delete https://domain/ser/3123")
        
        url = split_text[1]
        parsed_url = urlparse(url)
        path_parts = parsed_url.path.split('/')
        
        if len(path_parts) >= 3 and path_parts[-2] in ('ser', 'mov') and path_parts[-1].isdigit():
            media_type = path_parts[-2]
            tmdb_id = path_parts[-1]
            delete = await db.delete_document(media_type, int(tmdb_id))
            if delete:
                return await message.reply_text(f"{media_type} with ID {tmdb_id} has been deleted successfully.")
            else:
                return await message.reply_text(f"ID {tmdb_id} wasn't found in the database.")
        else:
            return await message.reply_text("The URL format is incorrect.")
    
    except Exception as e:
        await message.reply_text(f"An error occurred: {str(e)}")


@StreamBot.on_message(
    (filters.private & filters.text & ~filters.command(["start", "help", "user", "restart", "log", "caption", "tmdb", "set", "delete", "search", "find"])) |
    (filters.command(["search", "find"]) & (filters.group | filters.private)) |
    (filters.text & filters.group)
)
async def bot_search_handler(bot: Client, message: Message):
    """
    सर्च हैंडलर:
    - प्राइवेट चैट में: कोई भी टेक्स्ट (मूवी का नाम) भेजने पर सीधे काम करेगा।
    - ग्रुप चैट में:
      1. /search <मूवी नाम> या /find <मूवी नाम> कमांड पर काम करेगा।
      2. बोट को मेंशन करने पर (जैसे: movies request @botusername movie_name)
      3. बोट के किसी भी मैसेज का रिप्लाई देने पर।
      4. ग्रुप चैट में कोई भी नॉर्मल टेक्स्ट भेजने पर (यह केवल तभी रिप्लाई करेगा जब डेटाबेस में फ़ाइल मौजूद हो, अन्यथा शांत रहेगा)।
    """
    import re
    is_group = message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]
    is_command = False
    
    if is_group:
        is_triggered = False
        query = ""
        
        # 1. Check command first
        if message.command:
            is_triggered = True
            is_command = True
            query = " ".join(message.command[1:]).strip()
        # 2. Check bot username mention
        elif message.text and f"@{bot.me.username}" in message.text:
            is_triggered = True
            is_command = True
            raw_text = message.text.replace(f"@{bot.me.username}", "").strip()
            cleaned = re.sub(r'(?i)\b(movies?|show|series|request|find|search|please|give|send|get)\b', '', raw_text)
            query = cleaned.strip()
        # 3. Check reply to bot's messages
        elif message.reply_to_message and message.reply_to_message.from_user and message.reply_to_message.from_user.id == bot.me.id:
            is_triggered = True
            is_command = True
            query = message.text.strip()
        # 4. Check normal group text
        elif message.text:
            is_triggered = True
            query = message.text.strip()
            
        if not is_triggered or not query:
            return
    else:
        # Private chat direct text
        query = message.text.strip()
        if not query:
            return

    # 1. Force Join Check
    if Telegram.FORCE_JOIN_CHANNEL:
        joined = await is_user_joined(bot, message.from_user.id)
        if not joined:
            # केवल कमांड या प्राइवेट चैट में जॉइन एरर शो करें, ग्रुप चैट में सामान्य टेक्स्ट पर शांत रहें
            if is_group and not is_command:
                return
                
            channel = Telegram.FORCE_JOIN_CHANNEL
            try:
                chat = await bot.get_chat(channel)
                invite = f"https://t.me/{chat.username}" if chat.username else await bot.export_chat_invite_link(channel)
                ch_name = chat.title or "Our Channel"
            except Exception:
                invite = f"https://t.me/{Telegram.CHANNEL_USERNAME}"
                ch_name = "Our Channel"

            return await message.reply_text(
                f"⚠️ **Channel Join Required!**\n\n"
                f"📌 Humari movies & series search karne aur direct link paane ke liye pehle hamara channel join karo:\n"
                f"👉 **{ch_name}**\n\n"
                f"Channel join karne ke baad/Start join request accept hone ke baad search karein.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        f"✅ Join {ch_name}",
                        url=invite
                    )
                ]])
            )

    # 2. Search in Database
    # ग्रुप में सामान्य टेक्स्ट पर "Searching..." मैसेज न भेजें ताकि चैटरूम स्पैम न हो
    show_searching = not (is_group and not is_command)
    searching_msg = None
    if show_searching:
        searching_msg = await message.reply_text("🔍 Searching for your request, please wait...")
        
    try:
        search_results = await db.search_documents(query, page=1, page_size=5)
        results = search_results.get("results", [])
        
        # --- LOCAL DATABASE RESULTS FOUND ---
        if results:
            if searching_msg:
                await searching_msg.delete()
                
            text = f"🎬 **Search Results for '{query}'** 🎬\n\n"
            buttons = []
            image_url = None
            
            for index, doc in enumerate(results, 1):
                tmdb_id = doc.get("tmdb_id")
                title = doc.get("title", "Unknown Title")
                media_type = doc.get("media_type", "movie")
                
                # Fetch full details
                media_details = await db.get_media_details(tmdb_id)
                year = media_details.get('release_year', 0) if media_details else doc.get('release_year', 0)
                rating = media_details.get('rating', 0.0) if media_details else doc.get('rating', 0.0)
                genres_list = media_details.get('genres', []) if media_details else doc.get('genres', [])
                genres = ", ".join(genres_list) if genres_list else "N/A"
                
                qualities = set()
                rip = "Blu-ray"
                if media_details:
                    rip = media_details.get('rip', 'Blu-ray')
                    # Get first matching result poster/backdrop image
                    if index == 1:
                        image_url = media_details.get('backdrop') or media_details.get('poster')
                    
                    if media_type == "movie":
                        for item in media_details.get('telegram', []):
                            qualities.add(item.get('quality', 'HD'))
                    else:
                        for season in media_details.get('seasons', []):
                            for episode in season.get('episodes', []):
                                for item in episode.get('telegram', []):
                                    qualities.add(item.get('quality', 'HD'))
                
                qualities_str = ", ".join(sorted(list(qualities))) if qualities else "HD"
                path_type = "mov" if media_type == "movie" else "ser"
                website_link = f"https://filmy4uhd.vercel.app/{path_type}/{tmdb_id}"
                
                text += (
                    f"🍿 **{index}. {title} ({year})**\n"
                    f"⭐️ **Rating:** {rating}/10 | 🎭 **Genres:** {genres}\n"
                    f"💿 **Quality:** {qualities_str} [{rip}]\n"
                    f"🔗 [Watch/Download Page]({website_link})\n\n"
                )
                
                buttons.append([InlineKeyboardButton(f"🌐 {index}. {title} ({year})", url=website_link)])
                
            # Send photo with caption if image is available, else send text
            sent = False
            if image_url:
                try:
                    await message.reply_photo(
                        photo=image_url,
                        caption=text.strip(),
                        reply_markup=InlineKeyboardMarkup(buttons)
                    )
                    sent = True
                except Exception as ex:
                    LOGGER.warning(f"Failed to reply with photo for search: {ex}")
            
            if not sent:
                await message.reply_text(
                    text=text.strip(),
                    reply_markup=InlineKeyboardMarkup(buttons),
                    disable_web_page_preview=True
                )
            return

        # --- NO LOCAL RESULTS ---
        # ग्रुप चैट में सामान्य बातचीत/टेक्स्ट पर बिना मैच के बोट शांत रहेगा
        if is_group and not is_command:
            return

        # --- FALLBACK TO TMDB SEARCH --- (सिर्फ कमांड या इनबॉक्स के लिए)
        LOGGER.info(f"No local results for '{query}'. Searching TMDb...")
        
        tmdb_movies = await tmdb.search().movies(query=query)
        tmdb_tv = await tmdb.search().tv(query=query)
        
        combined_tmdb = []
        if tmdb_movies:
            for item in tmdb_movies[:3]:
                combined_tmdb.append((item, "movie"))
        if tmdb_tv:
            for item in tmdb_tv[:3]:
                combined_tmdb.append((item, "tv"))
                
        if not combined_tmdb:
            if searching_msg:
                return await searching_msg.edit_text(
                    f"❌ No results found for **'{query}'** in our database or on TMDb.\n\n"
                    f"Please check the spelling and try again."
                )
            return
            
        if searching_msg:
            await searching_msg.delete()
            
        text = f"🎬 **TMDb Search Results (Not Uploaded Yet)** 🎬\n"
        text += f"⚠️ *Note: These are not in our database yet, but you can visit their pages or request the admin below to upload them.*\n\n"
        buttons = []
        image_url = None
        
        for index, (item, media_type) in enumerate(combined_tmdb[:5], 1):
            tmdb_id = item.id
            if media_type == "movie":
                title = item.title
                year = item.release_date.year if item.release_date else 0
                rating = item.vote_average or 0.0
            else:
                title = item.name
                year = item.first_air_date.year if item.first_air_date else 0
                rating = item.vote_average or 0.0
                
            # Get the first result's image from TMDb
            if index == 1:
                try:
                    if media_type == "movie":
                        first_details = await tmdb.movie(tmdb_id).details()
                    else:
                        first_details = await tmdb.tv(tmdb_id).details()
                    image_url = f"https://image.tmdb.org/t/p/w500{first_details.poster_path}" if first_details.poster_path else \
                                (f"https://image.tmdb.org/t/p/original{first_details.backdrop_path}" if first_details.backdrop_path else None)
                except Exception:
                    pass
                
            path_type = "mov" if media_type == "movie" else "ser"
            website_link = f"https://filmy4uhd.vercel.app/{path_type}/{tmdb_id}"
            
            text += (
                f"🎥 **{index}. {title} ({year})**\n"
                f"⭐️ **Rating:** {rating:.1f}/10\n"
                f"🔗 [Request Page]({website_link})\n\n"
            )
            
            buttons.append([
                InlineKeyboardButton(f"🌐 Link {index}", url=website_link),
                InlineKeyboardButton(f"🙋‍♂️ Request Upload {index}", callback_data=f"req_{media_type}_{tmdb_id}")
            ])
            
        # Send TMDb consolidated result
        sent = False
        if image_url:
            try:
                await message.reply_photo(
                    photo=image_url,
                    caption=text.strip(),
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
                sent = True
            except Exception as ex:
                LOGGER.warning(f"Failed to reply with TMDb fallback photo: {ex}")
                
        if not sent:
            await message.reply_text(
                text=text.strip(),
                reply_markup=InlineKeyboardMarkup(buttons),
                disable_web_page_preview=True
            )
        return
                
    except Exception as e:
        LOGGER.error(f"Error in bot search handler: {e}")
        await message.reply_text("❌ An error occurred while searching. Please try again later.")


@StreamBot.on_callback_query(filters.regex(r"^req_"))
async def request_callback_handler(bot: Client, query: CallbackQuery):
    """
    जब कोई यूजर '🙋‍♂️ Request Upload' पर क्लिक करता है,
    तो यह बोट ओनर (Telegram.OWNER_ID) को सीधे टेलीग्राम पर अनुरोध भेजता है।
    """
    user = query.from_user
    data_parts = query.data.split("_")
    if len(data_parts) != 3:
        return await query.answer("Invalid request data.", show_alert=True)
        
    media_type = data_parts[1]
    tmdb_id = int(data_parts[2])
    
    try:
        if media_type == "movie":
            details = await tmdb.movie(tmdb_id).details()
            title = details.title
            year = details.release_date.year if details.release_date else 0
        else:
            details = await tmdb.tv(tmdb_id).details()
            title = details.name
            year = details.first_air_date.year if details.first_air_date else 0
            
        # Owner ID पर रिक्वेस्ट फॉरवर्ड करें
        owner_id = Telegram.OWNER_ID
        request_text = (
            f"📢 **New Media Request Received!** 📢\n\n"
            f"🎥 **Title:** {title} ({year})\n"
            f"🆔 **TMDB ID:** `{tmdb_id}` ({media_type.upper()})\n\n"
            f"👤 **Requested By:** {user.mention} (ID: `{user.id}`)\n"
            f"🕒 **Time:** {now.strftime('%d/%m/%y %I:%M:%S %p')}"
        )
        
        await bot.send_message(chat_id=owner_id, text=request_text)
        
        # User को अलर्ट दिखाएं
        await query.answer(f"✅ Your request for '{title} ({year})' has been sent to the Admin!", show_alert=True)
        
        # बटन को 'Requested' में अपडेट कर दें
        # मूल बटन्स में से केवल क्लिक किए गए बटन को बदलें
        new_buttons = []
        for row in query.message.reply_markup.inline_keyboard:
            new_row = []
            for btn in row:
                if btn.callback_data == query.data:
                    new_row.append(InlineKeyboardButton("✅ Requested", callback_data="none"))
                else:
                    new_row.append(btn)
            new_buttons.append(new_row)
            
        try:
            await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(new_buttons))
        except Exception:
            pass
            
    except Exception as e:
        LOGGER.error(f"Error in request callback handler: {e}")
        await query.answer("❌ Failed to send request. Please try again later.", show_alert=True)
        
