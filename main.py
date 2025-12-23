from fastapi import FastAPI, Request, Header
from fastapi.responses import JSONResponse
from pymongo import MongoClient, ReturnDocument
from datetime import datetime, timedelta
import os

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

@app.get("/")
def root():
    return {"status": "KantoHub License API Online XD;*"}

@app.post("/api/add-key")
async def add_key(req: Request, authorization: str = Header(None)):
    if not authorized(authorization):
        return JSONResponse({"error": "unauthorized"}, status_code=403)

    data = await req.json()

    duration = data.get("duration", "permanent")
    expires_at = None
    if duration in DURATION_MAP and DURATION_MAP[duration]:
        expires_at = datetime.utcnow() + DURATION_MAP[duration]

    key_value = data["key"]

    keys_col.insert_one({
        "system_name": data["system_name"],
        "placeid": str(data["placeid"]),
        "key": key_value,
        "server_name": data["server_name"],
        "assigned_to": data["assigned_to"],
        "timestamp_utc": datetime.utcnow(),
        "expires_at": expires_at,
        "used": False,
        "used_placeid": None,
        "used_at": None
    })
    credits_col.update_one(
        {"user_id": data["assigned_to"]},
        {"$push": {"generated_keys": data["key"]}}
    )

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

@app.post("/api/check-key")
async def check_key(req: Request):
    body = await req.json()
    user_id = body.get("user_id")

    keys = keys_col.find({"assigned_to": user_id})
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

    key = (await req.json()).get("key")
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
    user_id = data["user_id"]
    credits = int(data["credits"])
    keyprefix = data["keyprefix"]

    stock = stock_col.find_one({"name": "global"})
    if stock["credits"] < credits:
        return JSONResponse({"error": "not_enough_stock"}, status_code=400)

    stock_col.update_one(
        {"name": "global"},
        {"$inc": {"credits": -credits}}
    )

    credits_col.update_one(
        {"user_id": user_id},
        {
            "$set": {"keyprefix": keyprefix},
            "$inc": {"credits": credits},
            "$setOnInsert": {"generated_keys": []}
        },
        upsert=True
    )
    return {"success": True}

@app.post("/api/use-credit")
async def use_credit(req: Request, authorization: str = Header(None)):
    if not authorized(authorization):
        return JSONResponse({"error": "unauthorized"}, status_code=403)

    data = await req.json()
    user_id = data["user_id"]
    keyprefix = data["keyprefix"]
    user = credits_col.find_one({"user_id": user_id})
    if not user or user.get("credits", 0) <= 0:
        return {"success": False, "reason": "no_credits"}
    if user.get("keyprefix") != keyprefix:
        return {"success": False, "reason": "invalid_prefix"}
    credits_col.update_one(
        {"user_id": user_id},
        {"$inc": {"credits": -1}}
    )

    updated = credits_col.find_one({"user_id": user_id})
    if updated["credits"] <= 0:
        credits_col.update_one(
            {"user_id": user_id},
            {"$unset": {"keyprefix": ""}}
        )

    return {"success": True}

@app.post("/api/get-credits")
async def get_credits(req: Request, authorization: str = Header(None)):
    if not authorized(authorization):
        return JSONResponse({"error": "unauthorized"}, status_code=403)

    user_id = (await req.json()).get("user_id")

    user = credits_col.find_one({"user_id": user_id})
    return {
        "credits": user["credits"] if user else 0
        "keyprefix": user.get("keyprefix") if user else None
    }

@app.post("/api/credit-users")
async def credit_users(authorization: str = Header(None)):
    if not authorized(authorization):
        return JSONResponse({"error": "unauthorized"}, status_code=403)

    users = []
    for u in credits_col.find():
        users.append({
            "user_id": u["user_id"],
            "credits": u.get("credits", 0),
            "keyprefix": u.get("keyprefix"),
            "generated_keys": u.get("generated_keys", [])
        })

    return {"users": users}

@app.post("/api/add-credits")
async def add_credits(req: Request, authorization: str = Header(None)):
    if not authorized(authorization):
        return JSONResponse({"error": "unauthorized"}, status_code=403)

    data = await req.json()
    user_id = data["user_id"]
    amount = int(data["credits"])

    if amount <= 0:
        return {"success": False, "reason": "invalid_amount"}

    credits_col.update_one(
        {"user_id": user_id},
        {"$inc": {"credits": amount}},
        upsert=True
    )

    user = credits_col.find_one({"user_id": user_id})
    return {
        "success": True,
        "credits": user["credits"]
    }

@app.post("/api/revoke-credits")
async def revoke_credits(req: Request, authorization: str = Header(None)):
    if not authorized(authorization):
        return JSONResponse({"error": "unauthorized"}, status_code=403)

    data = await req.json()
    user_id = data["user_id"]
    amount = int(data["credits"])

    user = credits_col.find_one({"user_id": user_id})
    if not user:
        return {"success": False, "reason": "no_user"}

    if user.get("credits", 0) < amount:
        return {"success": False, "reason": "not_enough_credits"}

    credits_col.update_one(
        {"user_id": user_id},
        {"$inc": {"credits": -amount}}
    )

    updated = credits_col.find_one({"user_id": user_id})
    if updated["credits"] <= 0:
        credits_col.update_one(
            {"user_id": user_id},
            {"$unset": {"keyprefix": ""}}
        )

    return {
        "success": True,
        "credits": updated["credits"]
    }
