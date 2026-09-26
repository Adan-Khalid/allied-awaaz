from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db as dbmod
from .api import console, device, sim
from .config import settings
from .notify import get_notifier

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pilot: replace create_all with Alembic migrations.
    dbmod.Base.metadata.create_all(dbmod.engine)
    if settings.seed_demo_data:
        from .seed import seed
        with dbmod.SessionLocal() as s:
            if seed(s):
                logging.getLogger(__name__).info("seeded demo data")
    get_notifier()
    yield


app = FastAPI(title="Allied Awaaz", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
                   allow_methods=["GET", "POST"],
                   allow_headers=["*"])
app.include_router(device.router)
app.include_router(console.router)
app.include_router(sim.router)


@app.get("/healthz")
def healthz():
    return {"ok": True}
