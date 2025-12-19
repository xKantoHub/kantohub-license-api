from fastapi import FastAPI, Request, Header
from fastapi.responses import JSONResponse
import json, os
from datetime import datetime, timedelta

API_SECRET = os.getenv("API_SECRET", "kantohub_super_secret_key_6919601061")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
KEY_FILE = os.path.join(DATA_DIR, "keys.json")

app = FastAPI()

DURATION_MAP = {
    "3days": timedelta(days=3),
    "1week": timedelta(weeks=1),
    "1month": timedelta(days=30),
    "permanent": None
}

def authorized(auth: str):
    if not auth:
        return False
    if auth.startswith("Bearer "):
        auth = auth.replace("Bearer ", "")
    return auth == API_SECRET

def ensure_file():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(KEY_FILE):
        with open(KEY_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)

def load_keys():
    ensure_file()
    with open(KEY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_keys(keys):
    ensure_file()
    with open(KEY_FILE, "w", encoding="utf-8") as f:
        json.dump(keys, f, indent=4)

def is_expired(k):
    if k["expires_at"] is None:
        return False
    return datetime.utcnow() > datetime.fromisoformat(k["expires_at"])

def cleanup(keys):
    return [k for k in keys if not is_expired(k)]

@app.post("/api/add-key")
async def add_key(req: Request, authorization: str = Header(None)):
    if not authorized(authorization):
        return JSONResponse({"error": "unauthorized"}, status_code=403)

    data = await req.json()

    duration = data.get("duration", "permanent")
    expires_at = None

    if DURATION_MAP.get(duration):
        expires_at = (datetime.utcnow() + DURATION_MAP[duration]).isoformat()

    keys = cleanup(load_keys())

    keys.append({
        "placeid": str(data.get("placeid")), 
        "key": data.get("key"),
        "server_name": data.get("server_name"),
        "duration": duration,
        "assigned_to": data.get("assigned_to"),
        "generated_by": data.get("generated_by"),
        "timestamp_utc": data.get("timestamp_utc"),
        "expires_at": expires_at,
        "used": False,
        "used_placeid": None,
        "used_at": None
    })

    save_keys(keys)
    return {"success": True}

@app.post("/api/verify")
async def verify(req: Request):
    body = await req.json()
    key = body.get("key")
    placeid = str(body.get("placeid")) 

    keys = cleanup(load_keys())

    for k in keys:
        if k["key"] == key:
            if is_expired(k):
                save_keys(cleanup(keys))
                return {"success": False, "reason": "expired"}

            if k["placeid"] != placeid:
                return {"success": False, "reason": "wrong_place_id"}

            if not k["used"]:
                k["used"] = True
                k["used_placeid"] = placeid
                k["used_at"] = datetime.utcnow().isoformat()
                save_keys(keys)
                return {"success": True}

            if k["used_placeid"] == placeid:
                return {"success": True}

            return {"success": False, "reason": "used_elsewhere"}

    return {"success": False, "reason": "invalid_key"}

@app.post("/api/check-key")
async def check_key(req: Request):
    body = await req.json()
    discord_id = body.get("discord_id")

    keys = cleanup(load_keys())
    save_keys(keys)

    return {
        "keys": [
            k for k in keys
            if k.get("assigned_to", {}).get("id") == discord_id
        ]
    }

@app.post("/api/delete-key")
async def delete_key(req: Request, authorization: str = Header(None)):
    if not authorized(authorization):
        return JSONResponse({"error": "unauthorized"}, status_code=403)

    body = await req.json()
    target = body.get("key")

    keys = load_keys()
    new_keys = [k for k in keys if k["key"] != target]

    if len(keys) == len(new_keys):
        return JSONResponse({"error": "key_not_found"}, status_code=404)

    save_keys(new_keys)
    return {"success": True, "revoked": target}
