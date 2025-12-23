from fastapi import FastAPI, Request, Header
from fastapi.responses import JSONResponse
from pymongo import MongoClient
from datetime import datetime, timedelta
from fastapi.responses import RedirectResponse
from pymongo import ReturnDocument
import requests
import jwt
import os

DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "DISCORD_CLIENT_ID_HERE")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "DISCORD_CLIENT_SECRET_HERE")

DISCORD_REDIRECT_URI = os.getenv(
    "DISCORD_REDIRECT_URI",
    "https://kantohub-license-api.onrender.com/auth/discord/callback"
)

OWNER_DISCORD_ID = os.getenv("OWNER_DISCORD_ID", "1378265291095543870")

JWT_SECRET = os.getenv("JWT_SECRET", "super_secure_jwt_secret_123")
JWT_ALGO = "HS256"

API_SECRET = os.getenv("API_SECRET", "kantohub_super_secret_key_6919601061")

MONGO_URI = os.getenv(
    "MONGO_URI",
    "mongodb+srv://kantohub:SUemxBr7P9LuMaZ@cluster0.ymqrtsw.mongodb.net/?appName=Cluster0"
)

client = MongoClient(MONGO_URI)
db = client["kantohub"]
keys_col = db["licenses"]
credits_col = db["credits"]
stock_col = db["stock"]

app = FastAPI()

DURATION_MAP = {
    "3days": timedelta(days=3),
    "1week": timedelta(weeks=1),
    "1month": timedelta(days=30),
    "permanent": None
}

# INIT STOCK
stock_col.update_one(
    {"name": "global"},
    {"$setOnInsert": {"credits": 0}},
    upsert=True
)

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

    key_value = data["key"]
    key_prefix = key_value.split("-", 1)[0]

    keys_col.insert_one({
        "system_name": data["system_name"],
        "placeid": str(data["placeid"]),
        "key": key_value,
        "key_prefix": key_prefix,             
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

@app.get("/auth/discord/login")
def discord_login():
    url = (
        "https://discord.com/oauth2/authorize"
        f"?client_id={DISCORD_CLIENT_ID}"
        f"&redirect_uri={DISCORD_REDIRECT_URI}"
        "&response_type=code"
        "&scope=identify"
    )
    return RedirectResponse(url)

@app.get("/auth/discord/callback")
def discord_callback(code: str):
    # Exchange code → access token
    token_res = requests.post(
        "https://discord.com/api/oauth2/token",
        data={
            "client_id": DISCORD_CLIENT_ID,
            "client_secret": DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": DISCORD_REDIRECT_URI
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )

    token_json = token_res.json()
    access_token = token_json.get("access_token")

    if not access_token:
        return JSONResponse({"error": "discord_oauth_failed"}, status_code=400)
    user_res = requests.get(
        "https://discord.com/api/users/@me",
        headers={"Authorization": f"Bearer {access_token}"}
    )

    user = user_res.json()
    discord_id = user.get("id")
    if discord_id != OWNER_DISCORD_ID:
        return JSONResponse({"error": "not_authorized"}, status_code=403)
    jwt_token = jwt.encode(
        {
            "discord_id": discord_id,
            "exp": datetime.utcnow() + timedelta(hours=12)
        },
        JWT_SECRET,
        algorithm=JWT_ALGO
    )
    return RedirectResponse(
        f"https://banksfam.netlify.app/?admin_token={jwt_token}"
    )

@app.get("/auth/verify-admin")
def verify_admin(authorization: str = Header(None)):
    if not authorization:
        return {"ok": False}

    if authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "")
    else:
        token = authorization

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        if payload.get("discord_id") != OWNER_DISCORD_ID:
            return {"ok": False}
        return {"ok": True}
    except jwt.ExpiredSignatureError:
        return {"ok": False}
    except jwt.InvalidTokenError:
        return {"ok": False}

@app.post("/api/stock-credits")
async def stock_credits(req: Request, authorization: str = Header(None)):
    if not authorized(authorization):
        return JSONResponse({"error": "unauthorized"}, status_code=403)

    amount = int((await req.json())["amount"])
    stock_col.update_one({"name": "global"}, {"$inc": {"credits": amount}})
    stock = stock_col.find_one({"name": "global"})
    return {"success": True, "stock": stock["credits"]}

@app.post("/api/check-stock")
async def check_stock(authorization: str = Header(None)):
    if not authorized(authorization):
        return JSONResponse({"error": "unauthorized"}, status_code=403)

    stock = stock_col.find_one({"name": "global"}) or {"credits": 0}
    return {"credits": stock["credits"]}

@app.post("/api/give-credits")
async def give_credits(req: Request, authorization: str = Header(None)):
    if not authorized(authorization):
        return JSONResponse({"error": "unauthorized"}, status_code=403)

    data = await req.json()
    stock = stock_col.find_one({"name": "global"})

    if stock["credits"] < data["credits"]:
        return JSONResponse({"error": "not_enough_stock"}, status_code=400)

    stock_col.update_one({"name": "global"}, {"$inc": {"credits": -data["credits"]}})

    credits_col.update_one(
        {"discord_id": data["discord_id"]},
        {
            "$set": {"prefix": data["prefix"]},
            "$inc": {"credits": data["credits"]}
        },
        upsert=True
    )

    return {"success": True}

@app.post("/api/use-credit")
async def use_credit(req: Request, authorization: str = Header(None)):
    if not authorized(authorization):
        return JSONResponse(
            {"success": False, "reason": "unauthorized"},
            status_code=403
        )

    data = await req.json()
    discord_id = data.get("discord_id")

    if not discord_id:
        return JSONResponse(
            {"success": False, "reason": "discord_id_required"},
            status_code=400
        )

    user = credits_col.find_one_and_update(
        {
            "discord_id": discord_id,
            "credits": {"$gt": 0}
        },
        {
            "$inc": {"credits": -1}
        },
        return_document=ReturnDocument.BEFORE
    )

    if not user:
        return {
            "success": False,
            "reason": "no_enough_credits"
        }

    return {
        "success": True,
        "prefix": user["prefix"],
        "remaining": user["credits"] - 1
    }
