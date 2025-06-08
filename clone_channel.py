# main.py
import asyncio
import uuid
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from telethon import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.tl.types import PeerChannel
from telethon.errors.rpcerrorlist import FloodWaitError

app = FastAPI()
tasks = {}
@app.get("/")
async def home():
    return {"message": "working"}
    
class StartCloneRequest(BaseModel):
    api_id: int
    api_hash: str
    phone: str
    source_chat_id: int
    target_chat_id: int
    clone_start_id: int
    delay_seconds: float = 1.5
    limit: int = 100
@app.post("/start")
async def start_clone(req: StartCloneRequest):
    runner_id = str(uuid.uuid4())
    session_name = f"session_{runner_id}"

    async def clone():
        client = TelegramClient(session_name, req.api_id, req.api_hash)
        await client.start(req.phone)

        try:
            source = await client.get_input_entity(PeerChannel(req.source_chat_id))
            target = await client.get_input_entity(PeerChannel(req.target_chat_id))
        except Exception as e:
            print(f"❌ Error fetching entities: {e}")
            await client.disconnect()
            return

        all_messages = []
        offset_id = 0

        while True:
            try:
                history = await client(GetHistoryRequest(
                    peer=source,
                    offset_id=offset_id,
                    offset_date=None,
                    add_offset=0,
                    limit=req.limit,
                    max_id=0,
                    min_id=req.clone_start_id,
                    hash=0
                ))

                msgs = history.messages
                if not msgs:
                    break
                all_messages.extend(msgs)
                offset_id = msgs[-1].id
                await asyncio.sleep(0.5)
            except FloodWaitError as fwe:
                print(f"⚠️ Flood wait while fetching: {fwe.seconds} seconds")
                await asyncio.sleep(fwe.seconds)
            except Exception as e:
                print(f"❌ Error fetching messages: {e}")
                break

        all_messages.sort(key=lambda msg: msg.id)

        cloned_count = 0
        for message in all_messages:
            if message.action:
                continue

            try:
                if message.media:
                    await client.send_file(target, file=message.media, caption=message.message or "")
                elif message.message:
                    await client.send_message(target, message.message)
                else:
                    continue

                cloned_count += 1
                await asyncio.sleep(req.delay_seconds)

                # ⏸️ Pause after every 1000 messages
                if cloned_count % 1000 == 0:
                    print(f"⏸️ Pausing for 30 minutes after sending {cloned_count} messages...")
                    await asyncio.sleep(1800)

            except FloodWaitError as fwe:
                print(f"🚨 FloodWaitError while sending: {fwe.seconds} seconds")
                await asyncio.sleep(fwe.seconds)
            except Exception as e:
                print(f"❌ Error cloning message ID {message.id}: {e}")
                continue

        await client.disconnect()
        print(f"✅ Finished cloning {cloned_count} messages")

    task = asyncio.create_task(clone())
    tasks[runner_id] = task
    return {"runner_id": runner_id}

@app.post("/stop")
async def stop_clone(runner_id: str):
    task = tasks.get(runner_id)
    if not task:
        raise HTTPException(status_code=404, detail="Runner ID not found")
    task.cancel()
    del tasks[runner_id]
    return {"status": "stopped", "runner_id": runner_id}
