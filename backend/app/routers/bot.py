from fastapi import APIRouter
from ..bot_runner import start_bot, stop_bot, get_status

router = APIRouter(prefix="/bot", tags=["bot"])


@router.post("/start")
async def start():
    started = await start_bot()
    return {"ok": started, "status": get_status()}


@router.post("/stop")
async def stop():
    stopped = await stop_bot()
    return {"ok": stopped, "status": get_status()}


@router.get("/status")
def status():
    return {"status": get_status()}
