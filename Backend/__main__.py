from asyncio import get_event_loop, sleep as asleep
from traceback import format_exc
from pyrogram import idle
from pyrogram.errors import FloodWait
from Backend import __version__, db
from Backend.logger import LOGGER
from Backend.fastapi import server
from Backend.helper.pyro import restart_notification
from Backend.pyrofork import StreamBot, multi_clients
from Backend.pyrofork.clients import initialize_clients

loop = get_event_loop()

async def start_telegram():
    """Start Telegram bots in the background after the web server is running."""
    try:
        await asleep(2)  # Give Uvicorn a moment to bind the port
        await db.connect()
        await asleep(1.2)

        stream_bot_started = False
        try:
            while True:
                try:
                    await StreamBot.start()
                    stream_bot_started = True
                    break
                except FloodWait as e:
                    LOGGER.warning(f"FloodWait of {e.value} seconds encountered for StreamBot. Sleeping for {e.value + 5} seconds...")
                    await asleep(e.value + 5)
        except Exception as e:
            LOGGER.error(f"Failed to start primary StreamBot (token may be invalid/revoked): {e}")

        if stream_bot_started and getattr(StreamBot, "me", None):
            StreamBot.username = StreamBot.me.username
            LOGGER.info(f"Bot Client : [@{StreamBot.username}]")
        else:
            StreamBot.username = None
            LOGGER.warning("Primary StreamBot is offline. Multi-clients will handle streaming if available.")

        await asleep(1.2)
        LOGGER.info("Initializing Multi Clients...")
        try:
            await initialize_clients()
        except Exception as e:
            LOGGER.error(f"Error initializing multi-clients: {e}")

        if stream_bot_started:
            try:
                await restart_notification()
            except Exception as e:
                LOGGER.error(f"Error sending restart notification: {e}")
            LOGGER.info("Project-S Telegram clients started successfully!")
        else:
            LOGGER.info("Project-S multi-clients started (primary StreamBot offline)!")
    except Exception:
        LOGGER.error("Error starting Telegram clients:\n" + format_exc())

async def start_services():
    try:
        LOGGER.info(f"Initializing Project-Stream v-{__version__}")

        # Start web server FIRST so health checks pass immediately
        LOGGER.info('Initializing Project-S Web Server...')
        loop.create_task(server.serve())

        # Start Telegram clients in background
        loop.create_task(start_telegram())

        LOGGER.info("Project-S Started Successfully!")
        await idle()
    except Exception:
        LOGGER.error("Error during startup:\n" + format_exc())

async def stop_services():
    try:
        LOGGER.info("Stopping services...")
        for client_id, client in list(multi_clients.items()):
            try:
                if client.is_connected:
                    await client.stop()
            except Exception as ce:
                LOGGER.error(f"Error stopping client {client_id}: {ce}")

        try:
            if StreamBot.is_connected:
                await StreamBot.stop()
        except Exception as ce:
            LOGGER.error(f"Error stopping primary StreamBot: {ce}")

        await db.disconnect()
        LOGGER.info("Services stopped successfully.")
    except Exception:
        LOGGER.error("Error during shutdown:\n" + format_exc())

if __name__ == '__main__':
    try:
        loop.run_until_complete(start_services())
    except KeyboardInterrupt:
        LOGGER.info('Service Stopping...')
    except Exception:
        LOGGER.error(format_exc())
    finally:
        loop.run_until_complete(stop_services())
        loop.stop()

