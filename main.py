from fastapi import FastAPI, Request, Header
from fastapi.responses import JSONResponse
from pymongo import MongoClient
from datetime import datetime, timedelta
import os

API_SECRET = os.getenv("API_SECRET", "kantohub_super_secret_key_6919601061")

MONGO_URI = os.getenv(
    "MONGO_URI",
    "mongodb+srv://kantohub:SUemxBr7P9LuMaZ@cluster0.xxxx.mongodb.net/?retryWrites=true&w=majority"
)

client = MongoClient(MONGO_URI)
db = client["kantohub"]
keys_col = db["licenses"]

app = FastAPI()

DURATION_MAP = {
    "3days": timedelta(days=3),
    "1week": timedelta(weeks=1),
    "1month": timedelta(days=30),
    "permanent": None
}

# ================= UTILS =================

def authorized(auth: str):
    if not auth:
        return False
    if auth.startswith("Bearer "):
        auth = auth.replace("Bearer ", "")
    return auth == API_SECRET

def is_expired(k):
    if k["expires_at"] is None:
        return False
    return datetime.utcnow() > k["expires_at"]

# ================= ROUTES =================

@app.get("/")
def root():
    return {"status": "KantoHub License API Online (MongoDB)"}

@app.post("/api/add-key")
async def add_key(req: Request, authorization: str = Header(None)):
    if not authorized(authorization):
        return JSONResponse({"error": "unauthorized"}, status_code=403)

    data = await req.json()

    if not data.get("system_name"):
        return JSONResponse({"error": "system_name is required"}, status_code=400)

    duration = data.get("duration", "permanent")
    expires_at = None

    if duration in DURATION_MAP and DURATION_MAP[duration]:
        expires_at = datetime.utcnow() + DURATION_MAP[duration]

    keys_col.insert_one({
        "system_name": data["system_name"],
        "placeid": str(data["placeid"]),
        "key": data["key"],
        "server_name": data["server_name"],
        "duration": duration,
        "assigned_to": data["assigned_to"],
        "generated_by": data["generated_by"],
        "timestamp_utc": datetime.utcnow(),
        "expires_at": expires_at,
        "used": False,
        "used_placeid": None,
        "used_at": None
    })

    return {"success": True}

@app.post("/api/verify")
async def verify(req: Request):
    body = await req.json()
    key = body.get("key")
    placeid = str(body.get("placeid"))

    k = keys_col.find_one({"key": key})
    if not k:
        return {"success": False, "reason": "invalid_key"}

    if is_expired(k):
        return {"success": False, "reason": "expired"}

    if k["placeid"] != placeid:
        return {"success": False, "reason": "wrong_place_id"}

    if not k["used"]:
        keys_col.update_one(
            {"_id": k["_id"]},
            {"$set": {
                "used": True,
                "used_placeid": placeid,
                "used_at": datetime.utcnow()
            }}
        )
        return {"success": True}

    if k["used_placeid"] == placeid:
        return {"success": True}

    return {"success": False, "reason": "used_elsewhere"}

@app.post("/api/check-key")
async def check_key(req: Request):
    body = await req.json()
    discord_id = body.get("discord_id")

    keys = list(keys_col.find({
        "assigned_to.id": discord_id
    }))

    result = []
    for k in keys:
        if not is_expired(k):
            result.append({
                "system_name": k["system_name"],
                "server_name": k["server_name"],
                "key": k["key"],
                "expires_at": k["expires_at"].isoformat() if k["expires_at"] else None
            })

    return {"keys": result}

@app.post("/api/delete-key")
async def delete_key(req: Request, authorization: str = Header(None)):
    if not authorized(authorization):
        return JSONResponse({"error": "unauthorized"}, status_code=403)

    body = await req.json()
    key = body.get("key")

    res = keys_col.delete_one({"key": key})
    if res.deleted_count == 0:
        return JSONResponse({"error": "key_not_found"}, status_code=404)

    return {"success": True}

@app.post("/api/all-keys")
async def all_keys(authorization: str = Header(None)):
    if not authorized(authorization):
        return JSONResponse({"error": "unauthorized"}, status_code=403)

    keys = []
    for k in keys_col.find():
        if not is_expired(k):
            keys.append({
                "system_name": k["system_name"],
                "server_name": k["server_name"],
                "key": k["key"],
                "placeid": k["placeid"],
                "assigned_to": k["assigned_to"],
                "expires_at": k["expires_at"].isoformat() if k["expires_at"] else None,
                "used": k["used"]
            })

    return {"keys": keys}
