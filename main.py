import asyncio
from telethon import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.tl.types import PeerChannel
from telethon.errors.rpcerrorlist import FloodWaitError

# --- Configuration ---
api_id = 20142771
api_hash = '0d7aa3923c419850b6ae37180043b379'
phone = '+14632325265'

source_chat_id = -1002039777642
target_chat_id = -1002791585068

delay_seconds = 1.5
limit = 100 # Fetch more messages per request to reduce API calls

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
    offset_id = 0 # Start from the latest message (or a high number if you know the max ID)
    
    print(f"Fetching ALL messages from source channel (this might take a while)...")

    # Phase 1: Fetch all messages from newest to oldest
    while True:
        try:
            history = await client(GetHistoryRequest(
                peer=source_entity,
                offset_id=offset_id,
                offset_date=None,
                add_offset=0,
                limit=limit,
                max_id=0, # When offset_id is not 0, max_id=0 fetches older messages than offset_id
                min_id=4750, # No minimum ID for fetching
                hash=0
            ))

            messages = history.messages
            if not messages:
                break # No more messages

            # Add fetched messages to our list
            all_messages_to_clone.extend(messages)
            
            # Update offset_id to the oldest message in the current batch for the next fetch
            offset_id = messages[-1].id
            print(f"Fetched up to message ID {offset_id}. Total messages collected: {len(all_messages_to_clone)}")
            await asyncio.sleep(0.5) # Small delay to avoid hitting limits during fetch phase

        except FloodWaitError as fwe:
            print(f"🚨 FloodWaitError during history fetch: Sleeping for {fwe.seconds} seconds.")
            await asyncio.sleep(fwe.seconds)
        except Exception as e:
            print(f"❌ Error fetching history: {e}")
            break
            
    print(f"\n--- Finished fetching history. Total messages found: {len(all_messages_to_clone)} ---")
    
    # Phase 2: Sort all collected messages by ID in ascending order (oldest first)
    print("Sorting messages in sequential order...")
    all_messages_to_clone.sort(key=lambda msg: msg.id)
    
    total_cloned = 0
    print(f"Starting cloning of messages from the oldest to the newest.")

    # Phase 3: Clone messages sequentially
    for message in all_messages_to_clone:
        # Skip service messages (user joined, channel created etc.)
        if message.action:
            # print(f"➡️ Skipping service message {message.id}")
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
                # print(f"⚠️ Skipped empty/unsupported message {message.id}")
                continue

            total_cloned += 1
            print(f"✅ Cloned message {message.id} (Total cloned: {total_cloned})")
            await asyncio.sleep(delay_seconds) # Respect the delay between sending messages
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