import asyncio
import re
from asyncio import create_task, sleep as asleep, Queue, Lock
from urllib.parse import urlparse, quote
from traceback import format_exc
from Backend.logger import LOGGER
from Backend import db, now, timezone
from Backend.config import Telegram
from Backend.helper.custom_filter import CustomFilters
from Backend.helper.encrypt import decode_string
from Backend.helper.metadata import metadata
from Backend.helper.pyro import apply_channel_branding, get_readable_file_size, remove_urls
from Backend.pyrofork import StreamBot
from pyrogram import filters, Client  # type: ignore
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery  # type: ignore
from os import path as ospath
from pyrogram.errors import FloodWait  # type: ignore
from pyrogram.enums import ParseMode, ChatMemberStatus  # type: ignore
from themoviedb import aioTMDb  # type: ignore
from os import execl as osexecl
from asyncio import create_subprocess_exec, gather
from sys import executable
from aiofiles import open as aiopen  # type: ignore
from pyrogram import enums  # type: ignore
import random
import string
from passlib.context import CryptContext  # type: ignore
from datetime import datetime, timedelta

try:
    tmdb = aioTMDb(api_key=Telegram.TMDB_API, language="en-US", region="US")
except TypeError:
    tmdb = aioTMDb(key=Telegram.TMDB_API, language="en-US", region="US")

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




async def delete_messages_after_delay(messages, chat_id=None, reget_url=None):
    await asleep(300)  # 5 minutes auto-delete
    for msg in messages:
        try:
            await msg.delete()
        except Exception as e:
            LOGGER.error(f"Error deleting message {msg.id}: {e}")
        await asleep(1)  

    if chat_id and reget_url:
        try:
            await StreamBot.send_message(
                chat_id=chat_id,
                text=(
                    "🗑️ **Files deleted due to copyright protection.**\n\n"
                    "If you still need the files, click the button below to retrieve them again:"
                ),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔁 Get File Again", url=reget_url)
                ]])
            )
        except Exception as e:
            LOGGER.error(f"Failed to send re-get file message: {e}")


async def is_user_joined(bot: Client, user_id: int) -> bool:
    """Check karo ki user ne FORCE_JOIN_CHANNEL join kiya hai ya nahi."""
    channel = Telegram.FORCE_JOIN_CHANNEL
    if not channel:
        return True  # Force join off hai
    try:
        member = await bot.get_chat_member(channel, user_id)
        # Banned/left users ko block karo
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
    
    command_part = message.text.split('start ', 1)[-1].strip() if 'start ' in message.text else ""
    
    # Handle variations of prefixes: "file_", "mov_", "ser_", or direct numeric id
    if command_part.startswith("file_") or command_part.startswith("mov_") or command_part.startswith("ser_") or (command_part and command_part.isdigit()):
        usr_cmd = command_part
        if usr_cmd.startswith("file_"):
            usr_cmd = usr_cmd[len("file_"):].strip()
        if usr_cmd.startswith("mov_"):
            usr_cmd = usr_cmd[len("mov_"):].strip()
        elif usr_cmd.startswith("ser_"):
            usr_cmd = usr_cmd[len("ser_"):].strip()

        parts = usr_cmd.split("_")

        requested_lang = None
        if len(parts) > 1:
            possible_lang = parts[-1].lower()
            if possible_lang in ['hindi', 'english', 'tamil', 'telugu', 'malayalam', 'bengali', 'kannada', 'marathi', 'punjabi', 'gujarati', 'dual', 'multi', 'all'] or possible_lang.startswith('lang-'):
                requested_lang = possible_lang
                parts = parts[:-1]

        season = None
        episode = None
        tmdb_id = None
        quality_details = []

        if len(parts) == 1:
            try:
                tmdb_id = int(parts[0])
                quality_details = await db.get_quality_details(tmdb_id, quality="all")
                if not quality_details:
                    quality_details = await db.get_quality_details(tmdb_id, quality="all", season=0)
            except ValueError:
                LOGGER.error(f"Error parsing single TMDB ID command: {usr_cmd}")
                await message.reply_text("Invalid command format.")
                return

        elif len(parts) == 2:
            try:
                tmdb_id = int(parts[0])
                quality = parts[1]
                quality_details = await db.get_quality_details(tmdb_id, quality)
                if not quality_details:
                    quality_details = await db.get_quality_details(tmdb_id, quality, season=0)
            except ValueError:
                LOGGER.error(f"Error parsing movie command: {usr_cmd}")
                await message.reply_text("Invalid command format for movie.")
                return

        elif len(parts) == 3:
            try:
                tmdb_id = int(parts[0])
                if parts[1].isdigit() and parts[2].isdigit():
                    season = int(parts[1])
                    episode = int(parts[2])
                    quality_details = await db.get_quality_details(tmdb_id, quality="all", season=season, episode=episode)
                else:
                    season = int(parts[1])
                    quality = parts[2]
                    quality_details = await db.get_quality_details(tmdb_id, quality, season=season)
            except ValueError:
                LOGGER.error(f"Error parsing TV show command: {usr_cmd}")
                await message.reply_text("Invalid command format for TV show.")
                return

        elif len(parts) >= 4:
            try:
                tmdb_id = int(parts[0])
                season = int(parts[1])
                episode = int(parts[2]) if parts[2].isdigit() else parts[2]
                quality = "_".join(parts[3:])
                quality_details = await db.get_quality_details(tmdb_id, quality, season=season, episode=episode)
            except ValueError:
                LOGGER.error(f"Error parsing TV show command: {usr_cmd}")
                await message.reply_text("Invalid command format for TV show.")
                return

        else:
            await message.reply_text("Invalid command format.")
            return

        if not quality_details:
            await message.reply_text("Requested media file not found.")
            return

        # Check available languages among quality_details
        lang_groups = {}
        for detail in quality_details:
            l_val = detail.get('language') or 'Hindi'
            lang_groups.setdefault(l_val.strip(), []).append(detail)

        # If user did NOT specify a language filter AND multiple language versions exist:
        if len(lang_groups) > 1 and not requested_lang:
            bot_username = (bot.me.username if bot.me and bot.me.username else Telegram.CHANNEL_USERNAME or 'Filmy4uhdbot').lstrip('@')
            keyboard = []
            for l_name in lang_groups.keys():
                flag = "🇮🇳 " if "Hindi" in l_name else "🇬🇧 " if "English" in l_name else "🔊 "
                clean_lang = l_name.replace(" ", "-").lower()
                keyboard.append([InlineKeyboardButton(
                    f"{flag}{l_name} ({len(lang_groups[l_name])} File)",
                    url=f"https://t.me/{bot_username}?start={command_part}_{clean_lang}"
                )])

            keyboard.append([InlineKeyboardButton("🌐 Send All Languages", url=f"https://t.me/{bot_username}?start={command_part}_all")])

            return await message.reply_text(
                "🎧 **Select Audio / Language:**\n\n"
                "This file is available in multiple languages. Please choose your preferred language below:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        # If user specified a language filter and it's not "all":
        if requested_lang and requested_lang != 'all':
            req_clean = requested_lang.replace("-", " ").lower()
            filtered_details = [
                d for d in quality_details 
                if req_clean in (d.get('language') or '').lower() or (d.get('language') or '').lower() in req_clean
            ]
            if filtered_details:
                quality_details = filtered_details

        sent_messages = []

        # --- Force Join Check ---
        if Telegram.FORCE_JOIN_CHANNEL:
            joined = await is_user_joined(bot, message.from_user.id)
            if not joined:
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

        # Base host configuration
        raw_base_url = (Telegram.BASE_URL or "").strip().rstrip('/')
        if not raw_base_url or raw_base_url in ["0.0.0.0", "127.0.0.1", "localhost"]:
            server_host = f"http://127.0.0.1:{Telegram.PORT}"
        elif raw_base_url.startswith("http://") or raw_base_url.startswith("https://"):
            server_host = raw_base_url
        else:
            server_host = f"https://{raw_base_url}"

        for detail in quality_details:
            try:
                decoded_data = await decode_string(detail['id'])
            except Exception as dec_err:
                LOGGER.error(f"Error decoding media id {detail.get('id')}: {dec_err}")
                continue

            raw_cid = str(decoded_data.get('chat_id', '')).strip()
            if raw_cid.startswith("-100"):
                channel_id = int(raw_cid)
            elif raw_cid.startswith("-"):
                channel_id = int(f"-100{raw_cid[1:]}")
            else:
                channel_id = int(f"-100{raw_cid}")

            msg_id = int(decoded_data['msg_id'])
            name = detail.get('name', 'Media File')
            if "\\n" in name and name.endswith(".mkv"):
                name = name.rsplit(".mkv", 1)[0].replace("\\n", "\n")

            try:
                file = await bot.get_messages(channel_id, msg_id)
                if not file or file.empty:
                    LOGGER.warning(f"File message {msg_id} in channel {channel_id} is empty or deleted.")
                    continue

                media = file.document or file.video or file.audio
                if not media:
                    LOGGER.warning(f"No media document/video found in message {msg_id} in channel {channel_id}")
                    continue

                file_caption = (
                    f"🎬 **{name}**\n\n"
                    f"⏱️ **Forward this file to your Saved Messages.**\n"
                    f"This file will be deleted from the bot in 5 minutes due to copyright protection."
                )

                # Prepare buttons safely with URL encoding
                bot_buttons = None
                try:
                    encoded_name = quote(name)
                    if season is not None and episode is not None:
                        stream_url = f"{server_host}/watch/{tmdb_id}?season_number={season}&episode_number={episode}"
                    elif season is not None:
                        stream_url = f"{server_host}/watch/{tmdb_id}?season_number={season}"
                    else:
                        stream_url = f"{server_host}/watch/{tmdb_id}"

                    dl_url = f"{server_host}/dl/{detail['id']}/{encoded_name}?dl=1"

                    bot_buttons = InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("📱 Play in Next Player / Online", url=stream_url),
                            InlineKeyboardButton("📥 Fast Download", url=dl_url)
                        ]
                    ])
                except Exception as btn_err:
                    LOGGER.warning(f"Could not create inline buttons for {name}: {btn_err}")
                    bot_buttons = None

                try:
                    sent_msg = await message.reply_cached_media(
                        file_id=media.file_id,
                        caption=file_caption,
                        reply_markup=bot_buttons
                    )
                except Exception as reply_err:
                    LOGGER.warning(f"reply_cached_media failed with buttons ({reply_err}), retrying without buttons...")
                    sent_msg = await message.reply_cached_media(
                        file_id=media.file_id,
                        caption=file_caption
                    )

                sent_messages.append(sent_msg)
                await asleep(1)

            except FloodWait as e:
                LOGGER.info(f"Sleeping for {e.value}s")
                await asleep(e.value)
                await message.reply_text(f"Got Floodwait of {e.value}s")
            except Exception as e:
                LOGGER.error(f"Error retrieving/sending media: {e}\n{format_exc()}")
                await message.reply_text("Error retrieving media.")

        if sent_messages:
            bot_username = (bot.me.username if bot.me and bot.me.username else Telegram.CHANNEL_USERNAME or 'Filmy4uhdbot').lstrip('@')
            reget_url = f"https://t.me/{bot_username}?start={command_part}"
            create_task(delete_messages_after_delay(sent_messages, message.chat.id, reget_url))
    else:
        user_name = message.from_user.first_name if message.from_user else "Movie Lover"
        bot_uname = (bot.me.username if bot.me and bot.me.username else "Filmy4uhdbot").lstrip('@')
        welcome_text = (
            f"🎬 **Welcome to @{bot_uname}, {user_name}!** ✨\n\n"
            "🍿 **Your Ultimate Destination for HD Movies & Web Series!**\n\n"
            "⚡ **Bot Features:**\n"
            "• 🚀 **Direct High-Speed Download Links**\n"
            "• 📺 **Buffer-Free Online Streaming Player**\n"
            "• 🎧 **Multi-Audio (Hindi, Dual Audio, South, English)**\n"
            "• 📱 **Available in 480p, 720p, 1080p & 4K Quality**\n\n"
            "🌐 **Official Website:** [filmy4uhd.vercel.app](https://filmy4uhd.vercel.app)\n\n"
            "👇 *Click below to explore our website or get help:*"
        )
        buttons = [
            [
                InlineKeyboardButton("🌐 Visit Website", url="https://filmy4uhd.vercel.app"),
                InlineKeyboardButton("🔍 Search Movies", url="https://filmy4uhd.vercel.app/search")
            ]
        ]
        if Telegram.CHANNEL_USERNAME:
            chan_user = str(Telegram.CHANNEL_USERNAME).lstrip('@')
            buttons.append([
                InlineKeyboardButton("📢 Updates Channel", url=f"https://t.me/{chan_user}")
            ])
        buttons.append([
            InlineKeyboardButton("📖 How To Use", callback_data="help_user"),
            InlineKeyboardButton("⚡ Bot Status", callback_data="status_user")
        ])
        await message.reply_text(
            welcome_text,
            reply_markup=InlineKeyboardMarkup(buttons),
            disable_web_page_preview=True,
            parse_mode=ParseMode.MARKDOWN
        )


@StreamBot.on_callback_query(filters.regex("^(help_user|status_user|back_home)$"))
async def start_callbacks(bot: Client, query: CallbackQuery):
    data = query.data
    bot_uname = (bot.me.username if bot.me and bot.me.username else "Filmy4uhdbot").lstrip('@')
    user_name = query.from_user.first_name if query.from_user else "Movie Lover"

    if data == "help_user":
        help_text = (
            "📖 **How To Use This Bot & Website:**\n\n"
            "1️⃣ Open our official website: [filmy4uhd.vercel.app](https://filmy4uhd.vercel.app)\n"
            "2️⃣ Search for any Movie or Web Series.\n"
            "3️⃣ Click on **'Download'** or **'Watch Online'** on your desired quality.\n"
            "4️⃣ The website will redirect you here, and the bot will instantly deliver your direct fast link and player!\n\n"
            "💡 *Tip: Make sure you have joined our updates channel to stay updated on new releases!*"
        )
        buttons = [[InlineKeyboardButton("🔙 Back to Home", callback_data="back_home")]]
        await query.message.edit_text(help_text, reply_markup=InlineKeyboardMarkup(buttons), disable_web_page_preview=True, parse_mode=ParseMode.MARKDOWN)

    elif data == "status_user":
        from time import time
        from Backend import StartTime, __version__
        from Backend.helper.pyro import get_readable_time
        from Backend.pyrofork import multi_clients, work_loads

        status_text = (
            "⚡ **System & Bot Status:**\n\n"
            f"🤖 **Bot Name:** @{bot_uname}\n"
            f"🟢 **Server Status:** Online & Operational\n"
            f"⏱️ **Uptime:** {get_readable_time(time() - StartTime)}\n"
            f"🚀 **CDN Stream Workers:** {len(multi_clients)} active bots\n"
            f"📦 **Version:** v{__version__}\n"
            f"🌐 **Website:** [filmy4uhd.vercel.app](https://filmy4uhd.vercel.app)"
        )
        buttons = [[InlineKeyboardButton("🔙 Back to Home", callback_data="back_home")]]
        await query.message.edit_text(status_text, reply_markup=InlineKeyboardMarkup(buttons), disable_web_page_preview=True, parse_mode=ParseMode.MARKDOWN)

    elif data == "back_home":
        welcome_text = (
            f"🎬 **Welcome to @{bot_uname}, {user_name}!** ✨\n\n"
            "🍿 **Your Ultimate Destination for HD Movies & Web Series!**\n\n"
            "⚡ **Bot Features:**\n"
            "• 🚀 **Direct High-Speed Download Links**\n"
            "• 📺 **Buffer-Free Online Streaming Player**\n"
            "• 🎧 **Multi-Audio (Hindi, Dual Audio, South, English)**\n"
            "• 📱 **Available in 480p, 720p, 1080p & 4K Quality**\n\n"
            "🌐 **Official Website:** [filmy4uhd.vercel.app](https://filmy4uhd.vercel.app)\n\n"
            "👇 *Click below to explore our website or get help:*"
        )
        buttons = [
            [
                InlineKeyboardButton("🌐 Visit Website", url="https://filmy4uhd.vercel.app"),
                InlineKeyboardButton("🔍 Search Movies", url="https://filmy4uhd.vercel.app/search")
            ]
        ]
        if Telegram.CHANNEL_USERNAME:
            chan_user = str(Telegram.CHANNEL_USERNAME).lstrip('@')
            buttons.append([
                InlineKeyboardButton("📢 Updates Channel", url=f"https://t.me/{chan_user}")
            ])
        buttons.append([
            InlineKeyboardButton("📖 How To Use", callback_data="help_user"),
            InlineKeyboardButton("⚡ Bot Status", callback_data="status_user")
        ])
        await query.message.edit_text(
            welcome_text,
            reply_markup=InlineKeyboardMarkup(buttons),
            disable_web_page_preview=True,
            parse_mode=ParseMode.MARKDOWN
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
                "📂 **/index** - Auto-index all AUTH_CHANNELs, `/index <chat_id>`, or reply to a channel post.\n"
                "🛑 **/cancel_index** - Stop ongoing channel indexing.\n"
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


def get_existing_msg_id(media_details: dict, media_type: str, ch_id: int, metadata_info: dict) -> Optional[int]:
    ch_key = f"ch_{str(ch_id).replace('-', 'm')}"
    if media_type == "movie":
        ids_map = media_details.get("channel_message_ids") or {}
        if isinstance(ids_map, dict) and ch_key in ids_map:
            return ids_map[ch_key]
        return media_details.get("channel_message_id")
    else:
        season_num = metadata_info.get("season_number")
        episode_num = metadata_info.get("episode_number")
        for season in media_details.get("seasons", []):
            if season.get("season_number") == season_num:
                for episode in season.get("episodes", []):
                    if str(episode.get("episode_number")) == str(episode_num):
                        ids_map = episode.get("channel_message_ids") or {}
                        if isinstance(ids_map, dict) and ch_key in ids_map:
                            return ids_map[ch_key]
                        return episode.get("channel_message_id")
    return None


async def send_channel_notification(metadata_info):
    """
    कॉन्फ़िगर किए गए सभी चैनल्स (NOTIFICATION_CHANNELS & FORCE_JOIN_CHANNEL) पर
    नई फ़ाइल अपलोड का पूरा डेकोरेटेड नोटिफिकेशन (Review, Rating, Short Story / Synopsis) भेजता है।
    यदि पहले से ही पोस्ट मौजूद है तो उसे एडिट करता है।
    """
    target_channels = []
    for ch in Telegram.NOTIFICATION_CHANNELS:
        try:
            target_channels.append(int(ch))
        except (ValueError, TypeError):
            continue

    if Telegram.FORCE_JOIN_CHANNEL:
        try:
            fj = int(Telegram.FORCE_JOIN_CHANNEL)
            if fj not in target_channels:
                target_channels.append(fj)
        except (ValueError, TypeError):
            pass

    if not target_channels:
        LOGGER.info("No notification channels configured, skipping notification.")
        return

    try:
        tmdb_id = int(metadata_info['tmdb_id'])
        media_type = metadata_info['media_type']

        # Database से अपडेटेड डिटेल्स फ़ेच करें
        media_details = await db.get_media_details(tmdb_id)
        if not media_details:
            LOGGER.warning(f"Could not fetch details for tmdb_id {tmdb_id} from database.")
            return

        raw_title = media_details.get('title', 'Unknown Title')
        title = re.sub(r'[*_`~]', '', raw_title).strip()
        year = media_details.get('release_year', 0)
        rating = media_details.get('rating', 0.0)
        runtime = media_details.get('runtime', 0)
        
        genres_list = media_details.get('genres', [])
        genres = ", ".join(re.sub(r'[*_`~]', '', g) for g in genres_list) if genres_list else "Action, Drama"
        
        languages_list = media_details.get('languages', [])
        languages = ", ".join(re.sub(r'[*_`~]', '', l) for l in languages_list) if languages_list else "Hindi, English"
        
        rip = re.sub(r'[*_`~]', '', media_details.get('rip', 'WEB-DL'))
        
        raw_description = media_details.get('description', '') or ''
        clean_desc = re.sub(r'[*_`~]', '', raw_description).strip()
        if clean_desc:
            if len(clean_desc) > 280:
                clean_desc = clean_desc[:277].rsplit(' ', 1)[0] + "..."
            short_story = f"_{clean_desc}_"
        else:
            short_story = "_Experience an exciting blend of entertainment, emotion, and thrilling action. Streaming now in high quality!_"

        # Dynamic review tag based on rating
        try:
            rating_val = float(rating)
        except (ValueError, TypeError):
            rating_val = 0.0

        if rating_val >= 8.5:
            verdict = "🔥 Masterpiece • Must Watch!"
        elif rating_val >= 7.5:
            verdict = "🌟 Superhit • Highly Recommended"
        elif rating_val >= 6.5:
            verdict = "✨ Great Watch • Worth Your Time"
        elif rating_val >= 5.0:
            verdict = "🍿 Entertaining • Good One-Time Watch"
        elif rating_val > 0:
            verdict = "🎬 Casual Watch • Decent"
        else:
            verdict = "✨ Fresh Arrival"

        rating_display = f"{rating_val:.1f}/10" if rating_val > 0 else "N/A"

        # सभी उपलब्ध क्वालिटीज़ (Qualities) निकालें
        qualities = set()
        if media_type == "movie":
            for item in media_details.get('telegram', []):
                qualities.add(item.get('quality', 'HD'))
        else:
            season_num = metadata_info.get('season_number')
            episode_num = metadata_info.get('episode_number')
            for season in media_details.get('seasons', []):
                if season.get('season_number') == season_num:
                    for episode in season.get('episodes', []):
                        if str(episode.get('episode_number')) == str(episode_num):
                            for item in episode.get('telegram', []):
                                qualities.add(item.get('quality', 'HD'))

        qualities_str = ", ".join(sorted(list(qualities))) if qualities else "HD"

        # Vercel फ़्रंटएंड के अनुसार पाथ-लिंक बनाएं
        path_type = "mov" if media_type == "movie" else "ser"
        website_link = f"https://filmy4uhd.vercel.app/{path_type}/{tmdb_id}"

        # मीडिया टाइप के अनुसार टाइटल और हेडर तैयार करें
        if media_type == "tv" and 'season_number' in metadata_info and 'episode_number' in metadata_info:
            season_num = metadata_info.get('season_number', 1)
            ep_num_str = str(metadata_info['episode_number'])
            ep_title = metadata_info.get('episode_title', f"Episode {ep_num_str}")
            ep_title = re.sub(r'[*_`~]', '', ep_title).strip()
            
            header = "📺 ━━━━━━━━━━━━━━━━━━━ 📺\n⚡ **NEW EPISODE RELEASE** ⚡\n📺 ━━━━━━━━━━━━━━━━━━━ 📺"
            info_block = (
                f"🍿 **Series:** **{title}**\n"
                f"📌 **Season {season_num} | Episode {ep_num_str}** ({ep_title})\n"
                f"📅 **Year:** {year}\n"
                f"⭐ **Rating & Review:** **{rating_display}** • {verdict}\n"
                f"🎭 **Genres:** {genres}\n"
                f"🔊 **Audio:** {languages}\n"
                f"💿 **Quality:** **{qualities_str}** [{rip}]\n"
            )
        else:
            header = "🎬 ━━━━━━━━━━━━━━━━━━━ 🎬\n⚡ **NEW MOVIE RELEASE** ⚡\n🎬 ━━━━━━━━━━━━━━━━━━━ 🎬"
            runtime_line = f"⏱ **Duration:** {runtime} mins\n" if runtime and runtime > 0 else ""
            info_block = (
                f"🍿 **Movie:** **{title}**\n"
                f"📅 **Release Year:** {year}\n"
                f"⭐ **Rating & Review:** **{rating_display}** • {verdict}\n"
                f"🎭 **Genres:** {genres}\n"
                f"🔊 **Audio:** {languages}\n"
                f"💿 **Quality:** **{qualities_str}** [{rip}]\n"
                f"{runtime_line}"
            )

        caption = (
            f"{header}\n\n"
            f"{info_block}\n"
            f"📖 **Short Story / Synopsis:**\n"
            f"{short_story}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ **Direct Streaming & Fast Download:**\n"
            f"👉 {website_link}"
        )

        image_url = media_details.get('backdrop') or media_details.get('poster')

        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 Watch / Download Now", url=website_link)],
            [InlineKeyboardButton("🔍 Search More Movies", url="https://filmy4uhd.vercel.app")]
        ])

        # सभी कॉन्फ़िगर किए गए चैनल्स पर ब्रॉडकास्ट करें
        for ch_id in target_channels:
            try:
                existing_msg_id = get_existing_msg_id(media_details, media_type, ch_id, metadata_info)
                edited = False

                if existing_msg_id:
                    try:
                        if image_url:
                            await StreamBot.edit_message_caption(
                                chat_id=ch_id,
                                message_id=int(existing_msg_id),
                                caption=caption,
                                reply_markup=reply_markup
                            )
                        else:
                            await StreamBot.edit_message_text(
                                chat_id=ch_id,
                                message_id=int(existing_msg_id),
                                text=caption,
                                reply_markup=reply_markup
                            )
                        edited = True
                        LOGGER.info(f"Notification edited successfully in {ch_id} (Message ID: {existing_msg_id})")
                    except Exception as e:
                        LOGGER.warning(f"Failed to edit message {existing_msg_id} in {ch_id}: {e}. Sending new message...")
                        existing_msg_id = None

                if not edited:
                    sent_msg = None
                    try:
                        if image_url:
                            sent_msg = await StreamBot.send_photo(
                                chat_id=ch_id,
                                photo=image_url,
                                caption=caption,
                                reply_markup=reply_markup
                            )
                        else:
                            sent_msg = await StreamBot.send_message(
                                chat_id=ch_id,
                                text=caption,
                                reply_markup=reply_markup,
                                disable_web_page_preview=False
                            )
                    except Exception as e:
                        # Markdown parsing fallback
                        plain_caption = re.sub(r'[*_`~]', '', caption)
                        if image_url:
                            sent_msg = await StreamBot.send_photo(
                                chat_id=ch_id,
                                photo=image_url,
                                caption=plain_caption,
                                reply_markup=reply_markup
                            )
                        else:
                            sent_msg = await StreamBot.send_message(
                                chat_id=ch_id,
                                text=plain_caption,
                                reply_markup=reply_markup,
                                disable_web_page_preview=False
                            )

                    if sent_msg:
                        # Database में इस channel की मैसेज ID सेव करें
                        await db.update_channel_message_id(
                            tmdb_id=tmdb_id,
                            media_type=media_type,
                            message_id=sent_msg.id,
                            channel_id=ch_id,
                            season_number=metadata_info.get('season_number'),
                            episode_number=metadata_info.get('episode_number')
                        )
                        LOGGER.info(f"New notification sent successfully to {ch_id} for {title} (Message ID: {sent_msg.id})")
            except Exception as ch_err:
                LOGGER.error(f"Error processing notification for channel {ch_id}: {ch_err}")
    except Exception as e:
        LOGGER.error(f"Failed to send channel notifications: {e}")


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

_worker_started = False

def ensure_worker():
    global _worker_started
    if not _worker_started:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(process_file())
            _worker_started = True
        except RuntimeError:
            pass

try:
    loop = asyncio.get_running_loop()
    loop.create_task(process_file())
    _worker_started = True
except RuntimeError:
    pass


@StreamBot.on_message(filters.channel & (filters.document | filters.video))
async def file_receive_handler(bot: Client, message: Message):
    ensure_worker()
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


# ==============================================================================
# 🚀 AUTOMATIC & MANUAL CHANNEL INDEXING SYSTEM
# ==============================================================================

indexing_state = {
    "is_running": False,
    "current_channel": None,
    "total_found": 0,
    "indexed": 0,
    "skipped": 0,
    "cancel_requested": False
}

async def index_single_message(bot: Client, message: Message, send_notification: bool = False) -> bool:
    """Helper to parse and index a single Telegram video/document into MongoDB."""
    if not (message.video or (message.document and message.document.mime_type and message.document.mime_type.startswith("video/"))):
        return False
    file = message.video or message.document
    if not file:
        return False

    if Telegram.USE_CAPTION and message.caption:
        title = message.caption.replace("\n", "\\n")
    else:
        title = file.file_name or file.file_id

    if not title:
        return False

    msg_id = message.id
    f_hash = file.file_unique_id[:6]
    size = get_readable_file_size(file.file_size)
    channel = str(message.chat.id).replace("-100", "")

    metadata_info = await metadata(title, file)
    if not metadata_info:
        return False

    title = apply_channel_branding(title)
    if not title.endswith(('.mkv', '.mp4')):
        title += '.mkv'

    async with db_lock:
        updated_id = await db.insert_media(
            metadata_info,
            hash=f_hash,
            channel=int(channel),
            msg_id=msg_id,
            size=size,
            name=title
        )
        if updated_id and send_notification:
            await debounce_notification(metadata_info)
        return bool(updated_id)


async def scan_and_index_channel(bot: Client, channel_id: int, start_msg_id: int = 0, progress_msg: Optional[Message] = None):
    """Scans all messages from channel_id and indexes them into the database."""
    global indexing_state
    indexing_state["is_running"] = True
    indexing_state["current_channel"] = channel_id
    indexing_state["cancel_requested"] = False
    indexing_state["indexed"] = 0
    indexing_state["skipped"] = 0
    indexing_state["total_found"] = 0

    try:
        chat = await bot.get_chat(channel_id)
        chat_title = chat.title or str(channel_id)
    except Exception:
        chat_title = str(channel_id)

    LOGGER.info(f"Starting channel indexing for '{chat_title}' ({channel_id}) from msg_id {start_msg_id}...")

    last_processed_id = start_msg_id
    from time import time
    last_edit_time = time()
    total_processed = 0

    try:
        async for msg in bot.get_chat_history(channel_id):
            if indexing_state["cancel_requested"]:
                LOGGER.info("Indexing cancelled by user request.")
                break

            if start_msg_id > 0 and msg.id <= start_msg_id:
                break

            if msg.video or (msg.document and msg.document.mime_type and msg.document.mime_type.startswith("video/")):
                indexing_state["total_found"] += 1
                try:
                    success = await index_single_message(bot, msg, send_notification=False)
                    if success:
                        indexing_state["indexed"] += 1
                    else:
                        indexing_state["skipped"] += 1
                except Exception as ex:
                    LOGGER.error(f"Error indexing message {msg.id}: {ex}")
                    indexing_state["skipped"] += 1

            total_processed += 1
            if msg.id > last_processed_id:
                last_processed_id = msg.id

            if progress_msg and (time() - last_edit_time > 4):
                last_edit_time = time()
                try:
                    await progress_msg.edit_text(
                        f"🔄 **Indexing in Progress...**\n\n"
                        f"📢 **Channel:** `{chat_title}`\n"
                        f"📥 **Scanned Messages:** {total_processed}\n"
                        f"🎬 **Media Found:** {indexing_state['total_found']}\n"
                        f"✅ **Added / Updated:** {indexing_state['indexed']}\n"
                        f"⚠️ **Skipped:** {indexing_state['skipped']}\n\n"
                        f"🛑 *Send `/cancel_index` to stop anytime.*",
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception:
                    pass

        if db.db is not None and last_processed_id > 0:
            try:
                await db.db["channel_tracker"].update_one(
                    {"channel_id": channel_id},
                    {"$set": {"last_msg_id": last_processed_id, "updated_at": datetime.utcnow()}},
                    upsert=True
                )
            except Exception as e:
                LOGGER.error(f"Failed to update channel_tracker in DB: {e}")

    except FloodWait as fw:
        LOGGER.warning(f"FloodWait of {fw.value}s encountered during channel indexing.")
        await asleep(fw.value)
    except Exception as e:
        LOGGER.error(f"Error in scan_and_index_channel: {e}")
    finally:
        indexing_state["is_running"] = False

    return chat_title, indexing_state["indexed"], indexing_state["skipped"], indexing_state["total_found"]


async def auto_index_channels():
    """Background startup task: automatically catches up on missed channel messages after restart."""
    await asleep(15)
    if not Telegram.AUTH_CHANNEL:
        return

    LOGGER.info("Starting background catch-up indexing for AUTH_CHANNELs...")
    for ch in Telegram.AUTH_CHANNEL:
        try:
            ch_id = int(ch.strip())
            last_id = 0
            if db.db is not None:
                doc = await db.db["channel_tracker"].find_one({"channel_id": ch_id})
                if doc:
                    last_id = doc.get("last_msg_id", 0)
            await scan_and_index_channel(StreamBot, ch_id, start_msg_id=last_id)
        except Exception as e:
            LOGGER.warning(f"Auto-index failed for channel {ch}: {e}")
    LOGGER.info("Auto-indexing for AUTH_CHANNELs completed.")


try:
    asyncio.get_running_loop().create_task(auto_index_channels())
except RuntimeError:
    pass


@StreamBot.on_message(filters.command(['index']) & filters.private & CustomFilters.owner)
async def manual_index_command(bot: Client, message: Message):
    """
    Owner command to index:
    - Replied message's channel
    - Specific channel ID or @username (/index <channel>)
    - All AUTH_CHANNELs (/index)
    """
    target_chat_id = None
    start_id = 0

    if message.reply_to_message:
        rep = message.reply_to_message
        if rep.forward_from_chat:
            target_chat_id = rep.forward_from_chat.id
            start_id = rep.forward_from_message_id or 0
        elif rep.sender_chat:
            target_chat_id = rep.sender_chat.id
            start_id = rep.id

    args = message.text.split()
    if not target_chat_id and len(args) > 1:
        target_str = args[1].strip()
        try:
            if target_str.startswith("-100") or target_str.startswith("-") or target_str.isdigit():
                target_chat_id = int(target_str)
            else:
                chat_obj = await bot.get_chat(target_str)
                target_chat_id = chat_obj.id
        except Exception as e:
            await message.reply_text(f"❌ Could not access channel `{target_str}`: {e}\n*Make sure bot is added as Admin in the channel.*", parse_mode=ParseMode.MARKDOWN)
            return

    if indexing_state["is_running"]:
        await message.reply_text("⚠️ An indexing task is already running! Send `/cancel_index` to stop it.")
        return

    if not target_chat_id:
        if not Telegram.AUTH_CHANNEL:
            await message.reply_text("❌ No target channel specified and `AUTH_CHANNEL` list is empty in config.")
            return

        status_msg = await message.reply_text("🔄 **Starting Indexing for all configured AUTH_CHANNELs...**", parse_mode=ParseMode.MARKDOWN)
        total_indexed = 0
        total_found = 0
        for ch in Telegram.AUTH_CHANNEL:
            try:
                ch_id = int(ch.strip())
                title, indexed, skipped, found = await scan_and_index_channel(bot, ch_id, progress_msg=status_msg)
                total_indexed += indexed
                total_found += found
            except Exception as ex:
                LOGGER.error(f"Error indexing {ch}: {ex}")

        await status_msg.edit_text(
            f"✅ **All AUTH_CHANNELs Indexed Successfully!**\n\n"
            f"🎬 **Total Media Scanned:** {total_found}\n"
            f"📥 **Added to Database:** {total_indexed}",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    status_msg = await message.reply_text(f"⏳ **Connecting to channel `{target_chat_id}` to start indexing...**", parse_mode=ParseMode.MARKDOWN)
    try:
        title, indexed, skipped, total = await scan_and_index_channel(bot, target_chat_id, start_msg_id=start_id, progress_msg=status_msg)
        await status_msg.edit_text(
            f"🎉 **Channel Indexing Completed!**\n\n"
            f"📢 **Channel:** `{title}`\n"
            f"🎬 **Media Scanned:** {total}\n"
            f"✅ **Added / Updated in Database:** {indexed}\n"
            f"⚠️ **Skipped:** {skipped}",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ Indexing failed: {e}")


@StreamBot.on_message(filters.command(['cancel_index']) & filters.private & CustomFilters.owner)
async def cancel_index_command(bot: Client, message: Message):
    if indexing_state["is_running"]:
        indexing_state["cancel_requested"] = True
        await message.reply_text("🛑 **Indexing cancellation requested. It will stop in a few seconds.**")
    else:
        await message.reply_text("ℹ️ No indexing task is currently running.")


@StreamBot.on_message(filters.command('caption') & filters.private & CustomFilters.owner)
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
                InlineKeyboardButton(f"🌐 View on Web {index}", url=website_link)
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

        
