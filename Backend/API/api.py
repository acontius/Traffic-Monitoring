from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI
import asyncpg
import json

DB_DSN = "postgresql://acontius:1234@localhost:5432/traffic_monitoring"

app = FastAPI()
pool: asyncpg.pool.Pool = None

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# CORS middleware configuration
origins = [
    "http://localhost:5500",  # Add the port where your index.html is served
    "http://127.0.0.1:5500",
    "http://0.0.0.0:5500",
    # Add any other origins where your frontend might be served
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"], # Allows all methods (GET, POST, etc.)
    allow_headers=["*"], # Allows all headers
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    global pool
    pool = await asyncpg.create_pool(DB_DSN)
    print("API connected to database.")


@app.get("/latest")
async def get_latest_all():
    """
    آخرین داده برای هر device
    """
    query = """
        SELECT DISTINCT ON (device_id)
        device_id, timestamp, payload
        FROM traffic_data
        ORDER BY device_id, timestamp DESC
    """
    async with pool.acquire() as con:
        rows = await con.fetch(query)

    return [
        {
            "device_id": r["device_id"],
            "timestamp": r["timestamp"],
            "payload": r["payload"],
        }
        for r in rows
    ]


@app.get("/device/{device_id}")
async def get_latest_device(device_id: str):
    """
    آخرین داده مربوط به یک device
    """
    query = """
        SELECT device_id, timestamp, payload
        FROM traffic_data
        WHERE device_id = $1
        ORDER BY timestamp DESC
        LIMIT 1
    """
    async with pool.acquire() as con:
        row = await con.fetchrow(query, device_id)

    if not row:
        return {"error": "device not found"}

    return {
        "device_id": row["device_id"],
        "timestamp": row["timestamp"],
        "payload": row["payload"],
    }

