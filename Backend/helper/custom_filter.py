from pyrogram.filters import create
from Backend.config import Telegram
from pyrogram.enums import ChatMemberStatus

class CustomFilters:

    @staticmethod
    async def owner_filter(client, message):
        user = message.from_user or message.sender_chat
        if not user:
            return False
        uid = user.id
        if hasattr(Telegram, "OWNER_IDS") and uid in Telegram.OWNER_IDS:
            return True
        if uid == Telegram.OWNER_ID:
            return True
        # Also grant owner access if user is owner/administrator in any AUTH_CHANNEL
        for ch in Telegram.AUTH_CHANNEL:
            try:
                member = await client.get_chat_member(int(ch.strip()), uid)
                if member.status in [ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR]:
                    return True
            except Exception:
                continue
        return False

    owner = create(owner_filter)