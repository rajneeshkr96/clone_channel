# main.py
import asyncio
import uuid
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from telethon import TelegramClient
from telethon.errors.rpcerrorlist import FloodWaitError
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.tl.types import PeerChannel

app = FastAPI()
tasks = {}
sessions = {}
runner_state = {}

class StartLoginRequest(BaseModel):
    phone: str
    api_id: int
    api_hash: str

class ConfirmCodeRequest(BaseModel):
    phone: str
    code: str
    api_id: int
    api_hash: str

class SubmitPasswordRequest(BaseModel):
    phone: str
    api_id: int
    api_hash: str
    password: str

class StartCloneRequest(BaseModel):
    phone: str
    api_id: int
    api_hash: str
    source_chat_id: int
    target_chat_id: int
    clone_start_id: int
    delay_seconds: float = 1.5
    limit: int = 100

@app.get("/")
def home():
    return {"status": "working"}

@app.post("/start-login")
async def start_login(req: StartLoginRequest):
    session_name = f"session_{req.phone}"
    client = TelegramClient(session_name, req.api_id, req.api_hash)
    await client.connect()

    if not await client.is_user_authorized():
        try:
            result = await client.send_code_request(req.phone)
            sessions[req.phone] = {
                "session_name": session_name,
                "phone_code_hash": result.phone_code_hash,
                "api_id": req.api_id,
                "api_hash": req.api_hash
            }
            return {
                "status": "code_sent",
                "phone_code_hash": result.phone_code_hash
            }
        except Exception as e:
            return {"error": str(e)}
    return {"status": "already_logged_in"}

@app.post("/confirm-login")
async def confirm_login(req: ConfirmCodeRequest):
    session_info = sessions.get(req.phone)
    if not session_info:
        raise HTTPException(status_code=400, detail="No code request found for this phone.")

    session_name = session_info["session_name"]
    phone_code_hash = session_info["phone_code_hash"]
    client = TelegramClient(session_name, req.api_id, req.api_hash)
    await client.connect()

    try:
        await client.sign_in(phone=req.phone, code=req.code, phone_code_hash=phone_code_hash)
        return {"status": "signed_in_without_password"}
    except Exception as e:
        if "password is required" in str(e):
            return {
                "status": "2fa_required",
                "message": "Two-step verification enabled. Please provide password using /submit-password."
            }
        return {"error": str(e)}

@app.post("/submit-password")
async def submit_password(req: SubmitPasswordRequest):
    session_info = sessions.get(req.phone)
    if not session_info:
        raise HTTPException(status_code=400, detail="No session info found for this phone.")

    session_name = session_info["session_name"]
    client = TelegramClient(session_name, req.api_id, req.api_hash)
    await client.connect()

    try:
        await client.sign_in(password=req.password)
        return {"status": "signed_in_with_password"}
    except Exception as e:
        return {"error": str(e)}

@app.post("/start-clone")
async def start_clone(req: StartCloneRequest):
    runner_id = str(uuid.uuid4())
    session_name = sessions.get(req.phone, {}).get("session_name", f"session_{req.phone}")

    runner_state[runner_id] = {
        "runner_id": runner_id,
        "status": "starting",
        "started_at": datetime.utcnow().isoformat(),
        "total_messages_fetched": 0,
        "messages_cloned": 0,
        "last_cloned_id": None,
        "error": None
    }

    async def clone():
        client = TelegramClient(session_name, req.api_id, req.api_hash)
        await client.connect()

        try:
            source = await client.get_input_entity(PeerChannel(req.source_chat_id))
            target = await client.get_input_entity(PeerChannel(req.target_chat_id))
        except Exception as e:
            runner_state[runner_id]["status"] = "error"
            runner_state[runner_id]["error"] = str(e)
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
                runner_state[runner_id]["total_messages_fetched"] = len(all_messages)
                await asyncio.sleep(0.5)
            except FloodWaitError as fwe:
                await asyncio.sleep(fwe.seconds)
            except Exception as e:
                runner_state[runner_id]["error"] = str(e)
                break

        all_messages.sort(key=lambda msg: msg.id)
        count = 0

        for message in all_messages:
            if message.action:
                continue
            try:
                if message.media:
                    await client.send_file(target, file=message.media, caption=message.message or "")
                elif message.message:
                    await client.send_message(target, message.message)

                count += 1
                runner_state[runner_id]["messages_cloned"] = count
                runner_state[runner_id]["last_cloned_id"] = message.id

                if count % 1000 == 0:
                    await asyncio.sleep(req.rest_sec)
                await asyncio.sleep(req.delay_seconds)
            except FloodWaitError as fwe:
                await asyncio.sleep(fwe.seconds)
            except Exception:
                continue

        runner_state[runner_id]["status"] = "completed"
        await client.disconnect()

    task = asyncio.create_task(clone())
    tasks[runner_id] = task
    return {"runner_id": runner_id}

@app.post("/stop-clone")
async def stop_clone(runner_id: str):
    task = tasks.get(runner_id)
    if not task:
        raise HTTPException(status_code=404, detail="Runner ID not found")
    task.cancel()
    del tasks[runner_id]
    return {"status": "stopped", "runner_id": runner_id}

@app.get("/status")
async def check_status(runner_id: str):
    state = runner_state.get(runner_id)
    task = tasks.get(runner_id)

    if not state:
        return JSONResponse(content={"status": "not_found", "runner_id": runner_id}, status_code=404)

    if task:
        if task.cancelled():
            state["status"] = "cancelled"
        elif task.done():
            state["status"] = state.get("status", "completed")
        else:
            state["status"] = "running"

    return state

@app.get("/runners")
async def list_all_runners():
    runner_statuses = []

    for runner_id, task in tasks.items():
        if task.cancelled():
            status = "cancelled"
        elif task.done():
            status = "completed"
        else:
            status = "running"

        runner_statuses.append({
            "runner_id": runner_id,
            "status": status
        })

    return {
        "total_runners": len(runner_statuses),
        "runners": runner_statuses
    }


@app.get("/login-status")
async def login_status(phone: str):
    session_info = sessions.get(phone)
    if not session_info:
        return {"status": "not_logged_in"}
    client = TelegramClient(session_info["session_name"], session_info["api_id"], session_info["api_hash"])
    await client.connect()
    try:
        authorized = await client.is_user_authorized()
        return {"status": "logged_in" if authorized else "not_logged_in"}
    finally:
        await client.disconnect()
