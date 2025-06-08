import asyncio
import os
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.tl.types import PeerChannel
from telethon.errors.rpcerrorlist import FloodWaitError

# --- Load environment variables ---
load_dotenv()

api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
phone = os.getenv("PHONE")

source_chat_id = int(os.getenv("SOURCE_CHAT_ID"))
target_chat_id = int(os.getenv("TARGET_CHAT_ID"))
clone_start_id = int(os.getenv("CLONE_START_ID"))
wait = 1800
delay_seconds = 1.5
limit = 100  # Number of messages per API request

# --- Initialize Client ---
client = TelegramClient('channel_clone_session', api_id, api_hash)

# --- Main Cloning Function ---
async def main():
    await client.start(phone)
    print("✅ Logged in.")

    try:
        source_entity = await client.get_input_entity(PeerChannel(source_chat_id))
        target_entity = await client.get_input_entity(PeerChannel(target_chat_id))
        print(f"Source channel: {source_entity.title if hasattr(source_entity, 'title') else 'Unknown'}")
        print(f"Target channel: {target_entity.title if hasattr(target_entity, 'title') else 'Unknown'}")
    except Exception as e:
        print(f"❌ Error getting chat entities. Make sure IDs are correct and you have access: {e}")
        await client.disconnect()
        return

    all_messages_to_clone = []
    offset_id = 0

    print(f"Fetching ALL messages from source channel (this might take a while)...")

    # --- Phase 1: Fetch history ---
    while True:
        try:
            history = await client(GetHistoryRequest(
                peer=source_entity,
                offset_id=offset_id,
                offset_date=None,
                add_offset=0,
                limit=limit,
                max_id=0,
                min_id=clone_start_id,
                hash=0
            ))

            messages = history.messages
            if not messages:
                break

            all_messages_to_clone.extend(messages)
            offset_id = messages[-1].id
            print(f"Fetched up to message ID {offset_id}. Total messages collected: {len(all_messages_to_clone)}")
            await asyncio.sleep(0.5)

        except FloodWaitError as fwe:
            print(f"🚨 FloodWaitError during history fetch: Sleeping for {fwe.seconds} seconds.")
            await asyncio.sleep(fwe.seconds)
        except Exception as e:
            print(f"❌ Error fetching history: {e}")
            break

    print(f"\n--- Finished fetching history. Total messages found: {len(all_messages_to_clone)} ---")

    # --- Phase 2: Sort messages ---
    print("Sorting messages in sequential order...")
    all_messages_to_clone.sort(key=lambda msg: msg.id)

    # --- Phase 3: Clone messages ---
    total_cloned = 0
    print(f"Starting cloning of messages from the oldest to the newest.")

    for index, message in enumerate(all_messages_to_clone):
        if message.action:
            continue

        try:
            if message.media:
                await client.send_file(
                    target_entity,
                    file=message.media,
                    caption=message.message or "",
                    silent=False,
                    allow_cache=True
                )
            elif message.message:
                await client.send_message(target_entity, message.message)
            else:
                continue

            total_cloned += 1
            print(f"✅ Cloned message {message.id} (Total cloned: {total_cloned})")

            # 🕒 Wait 30 minutes after every 1500 messages
            if total_cloned % 600 == 0:
                print("⏳ Reached 1500 messages. Waiting for 30 minutes to avoid rate limits...")
                await asyncio.sleep(wait)  # 30 minutes

            await asyncio.sleep(delay_seconds)

        except FloodWaitError as fwe:
            print(f"🚨 FloodWaitError: Sleeping for {fwe.seconds} seconds.")
            await asyncio.sleep(fwe.seconds)
        except Exception as e:
            print(f"❌ Error cloning message {message.id}: {e}")

    print(f"🎉 Done! Total messages cloned: {total_cloned}")
    await client.disconnect()

# --- Run the client ---
if __name__ == '__main__':
    with client:
        client.loop.run_until_complete(main())
