from fastapi import FastAPI, Request, Header
from fastapi.responses import JSONResponse
import json, os
from datetime import datetime

API_SECRET = os.getenv("API_SECRET", "dev_secret")
KEY_FILE = "keys.json"

app = FastAPI()

def load_keys():
    if not os.path.exists(KEY_FILE):
        return []
    with open(KEY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_keys(data):
    with open(KEY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

@app.get("/")
def root():
    return {"status": "License API Online"}

@app.post("/api/add-key")
async def add_key(req: Request, authorization: str = Header(None)):
    if authorization != API_SECRET:
        return JSONResponse({"error": "unauthorized"}, status_code=403)

    data = await req.json()
    keys = load_keys()
    keys.append({
        **data,
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
    placeid = str(body.get("placeId"))

    keys = load_keys()
    for k in keys:
        if k["key"] == key:
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
