import json
from os import getenv, path
from dotenv import load_dotenv  # type: ignore
from Backend import LOGGER


load_dotenv(path.join(path.dirname(path.dirname(__file__)), "sample_config.env"))
class Telegram:
    API_ID = int(getenv("API_ID", "26954495"))
    API_HASH = getenv("API_HASH", "2061c55207cfee4f106ff0dc331fe3d9")
    BOT_TOKEN = getenv("BOT_TOKEN", "8063822502:AAErn_csLBm3WDjz9WxJ1rQ2nknB266Kc5I")
    PORT = int(getenv("PORT", "8080"))
    _auth_channels_raw = getenv("AUTH_CHANNEL", "-1002817803749, -1002740721681") or ""
    AUTH_CHANNEL = [channel.strip() for channel in _auth_channels_raw.split(",") if channel.strip()]
    for _def_auth in ["-1002817803749", "-1002740721681"]:
        if _def_auth not in AUTH_CHANNEL:
            AUTH_CHANNEL.append(_def_auth)

    _notif_channels_raw = getenv("NOTIFICATION_CHANNELS", "-1002590869159, -1003074016132, -1002799537836") or ""
    NOTIFICATION_CHANNELS = [ch.strip() for ch in _notif_channels_raw.split(",") if ch.strip()]
    for _def_notif in ["-1002590869159", "-1003074016132", "-1002799537836"]:
        if _def_notif not in NOTIFICATION_CHANNELS:
            NOTIFICATION_CHANNELS.append(_def_notif)

    DATABASE = getenv("DATABASE", "mongodb+srv://Keshav:Keshav@cluster0.ndw3zfh.mongodb.net/?appName=Cluster0").split(", ")
    TMDB_API = getenv("TMDB_API", "f9dbeb078807efcbb1e3a72cd80881b3")
    IMDB_API = getenv("IMDB_API", "https://imdb-api-lux.wemedia360.workers.dev/").rstrip('/')
    UPSTREAM_REPO = getenv("UPSTREAM_REPO", "https://github.com/keshav6606/filmsclubackend")
    UPSTREAM_BRANCH = getenv("UPSTREAM_BRANCH", "main")
    MULTI_CLIENT = getenv("MULTI_CLIENT", "False").lower() == "true"
    USE_CAPTION = getenv("USE_CAPTION", "False").lower() == "true"
    USE_TMDB = getenv("USE_TMDB", "True").lower() == "true"
    _owner_id_raw = str(getenv("OWNER_ID", "7045947967"))
    OWNER_IDS = []
    for _x in _owner_id_raw.split(","):
        _x = _x.strip()
        if _x.isdigit() or (_x.startswith("-") and _x[1:].isdigit()):
            OWNER_IDS.append(int(_x))
    if 7045947967 not in OWNER_IDS:
        OWNER_IDS.append(7045947967)
    OWNER_ID = OWNER_IDS[0]
    USE_DEFAULT_ID = getenv("USE_DEFAULT_ID", None)
    # Auto-branding: जो @username filename में prefix होगा (@ मत लगाएँ)
    CHANNEL_USERNAME = getenv("CHANNEL_USERNAME", "skysetx01")
    # Force Join: फाइल देने से पहले यूज़र को इस channel में join करना पड़ेगा
    # default channel ID: -1002342440306 (अगर बंद करना हो तो env में empty या None सेट करें)
    FORCE_JOIN_CHANNEL = getenv("FORCE_JOIN_CHANNEL", "-1002342440306")
    if FORCE_JOIN_CHANNEL and FORCE_JOIN_CHANNEL.strip():
        try:
            FORCE_JOIN_CHANNEL = int(FORCE_JOIN_CHANNEL)
        except ValueError:
            pass
    else:
        FORCE_JOIN_CHANNEL = None
