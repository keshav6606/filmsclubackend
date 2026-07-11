import json
from os import getenv, path
from dotenv import load_dotenv
from Backend import LOGGER


load_dotenv(path.join(path.dirname(path.dirname(__file__)), "sample_config.env"))
class Telegram:
    API_ID = int(getenv("API_ID", "26954495"))
    API_HASH = getenv("API_HASH", "2061c55207cfee4f106ff0dc331fe3d9")
    BOT_TOKEN = getenv("BOT_TOKEN", "8111940661:AAE95cvKg3o5oP3PYbRxIBO7BRYv082It_g")
    PORT = int(getenv("PORT", "8080"))
    BASE_URL = getenv("BASE_URL", "0.0.0.0").rstrip('/')
    AUTH_CHANNEL = [channel.strip() for channel in (getenv("AUTH_CHANNEL") or "").split(",") if channel.strip()]
    DATABASE = getenv("DATABASE", "mongodb+srv://Keshav:Keshav@cluster0.ndw3zfh.mongodb.net/?appName=Cluster0").split(", ")
    TMDB_API = getenv("TMDB_API", "f9dbeb078807efcbb1e3a72cd80881b3")
    IMDB_API = getenv("IMDB_API", "https://imdb-api-lux.wemedia360.workers.dev/").rstrip('/')
    UPSTREAM_REPO = getenv("UPSTREAM_REPO", "https://keshav6606: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@github.com/keshav6606/filmsclub-backend")
    UPSTREAM_BRANCH = getenv("UPSTREAM_BRANCH", "main")
    MULTI_CLIENT = getenv("MULTI_CLIENT", "False").lower() == "true"
    USE_CAPTION = getenv("USE_CAPTION", "False").lower() == "true"
    USE_TMDB = getenv("USE_TMDB", "True").lower() == "true"
    OWNER_ID = int(getenv("OWNER_ID", "7045947967"))
    USE_DEFAULT_ID = getenv("USE_DEFAULT_ID", None)
    # Auto-branding: जो @username filename में prefix होगा (@ मत लगाएँ)
    CHANNEL_USERNAME = getenv("CHANNEL_USERNAME", "skysetx01")
    # Force Join: फाइल देने से पहले यूज़र को इस channel में join करना पड़ेगा
    # उदाहरण: "-1001234567890" या कुछ नहीं चाहिए तो None रखें
    FORCE_JOIN_CHANNEL = getenv("FORCE_JOIN_CHANNEL", None)
