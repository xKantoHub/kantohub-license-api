from fastapi import FastAPI, Request, Header
from fastapi.responses import JSONResponse
import json, os
from datetime import datetime, timedelta

API_SECRET = os.getenv("API_SECRET")
KEY_FILE = "/data/keys.json"

app = FastAPI()

DURATION_MAP = {
    "3days": timedelta(days=3),
    "1week": timedelta(weeks=1),
    "1month": timedelta(days=30),
    "permanent": None
}

# ---------------- UTILITIES ----------------
def load_keys():
    if not os.path.exists(KEY_FILE):
        return []
    with open(KEY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_keys(data):
    os.makedirs(os.path.dirname(KEY_FILE), exist_ok=True)
    with open(KEY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def is_expired(k):
    if k["expires_at"] is None:
        return False
    return datetime.utcnow() > datetime.fromisoformat(k["expires_at"])

def cleanup_expired(keys):
    return [k for k in keys if not is_expired(k)]

# ---------------- ROUTES ----------------
@app.get("/")
def root():
    return {"status": "License API Online"}

# -------- ADD KEY --------
@app.post("/api/add-key")
async def add_key(req: Request, authorization: str = Header(None)):
    if authorization != API_SECRET:
        return JSONResponse({"error": "unauthorized"}, status_code=403)

    data = await req.json()
    duration = data.get("duration", "permanent")

    expires_at = None
    if DURATION_MAP.get(duration):
        expires_at = (datetime.utcnow() + DURATION_MAP[duration]).isoformat()

    keys = cleanup_expired(load_keys())

    keys.append({
        **data,
        "duration": duration,
        "expires_at": expires_at,
        "used": False,
        "used_placeid": None,
        "used_at": None
    })

    save_keys(keys)
    return {"success": True}

# -------- VERIFY KEY --------
@app.post("/api/verify")
async def verify(req: Request):
    body = await req.json()
    key = body.get("key")
    placeid = str(body.get("placeId"))

    keys = cleanup_expired(load_keys())

    for k in keys:
        if k["key"] == key:
            if is_expired(k):
                save_keys(cleanup_expired(keys))
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

            return {"success": False, "reason": "key_used_elsewhere"}

    return {"success": False, "reason": "invalid_key"}

# -------- CHECK KEY --------
@app.post("/api/check-key")
async def check_key(req: Request):
    body = await req.json()
    discord_id = body.get("discord_id")

    keys = cleanup_expired(load_keys())
    save_keys(keys)

    return {
        "keys": [
            k for k in keys
            if k["assigned_to"]["id"] == discord_id
        ]
    }
