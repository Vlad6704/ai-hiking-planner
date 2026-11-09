import argparse
import sqlite3
import logging
from contextlib import asynccontextmanager

from app.observability.runtime_logging import configure_logging, log_context
from app.observability.asyncio_logging import capture_asyncio_errors

if __name__ == '__main__':
    configure_logging('operator-demo')

import uvicorn
from fastapi import FastAPI, Response

from app.models.contracts import BookingRequest, GuideQuery, InventoryQuery
from app.route_catalog.store import CatalogStore, database_path
from app.tools.operator import MockOperator, confirmation

@asynccontextmanager
async def lifespan(app):
    with log_context(component='operator_demo'), capture_asyncio_errors('operator_demo'):
        logging.getLogger('app.operator').info('operator.started')
        try:
            yield
        finally:
            logging.getLogger('app.operator').info('operator.stopped')


app = FastAPI(lifespan=lifespan)


@app.get('/health')
async def health():
    return {'service': 'picos-operator-demo'}


@app.post("/guides")
async def guides(query: GuideQuery, response: Response):
    response.headers["X-Reservation-Idempotency"] = "request-id"
    supported = query.route_id == "PR-PNPE-2"
    if not supported and database_path().exists():
        try:
            CatalogStore(database_path()).details(query.route_id)
            supported = True
        except (ValueError, sqlite3.Error):
            pass
    provider = MockOperator({str(query.date): ["ines", "luis"]}, {}, [query.route_id] if supported else [])
    return await provider.guides(query)


@app.post("/inventory")
async def inventory(query: InventoryQuery):
    provider = MockOperator(
        {},
        dict.fromkeys(
            ["boots", "water", "rain jacket", "first aid kit", "warm layer", "poles"], 4
        ),
        [],
    )
    return await provider.inventory(query)


@app.post("/reservations")
async def reservations(query: BookingRequest):
    return confirmation(query)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run the stateless hiking operator demo"
    )
    parser.add_argument("--port", type=int, default=8765)
    uvicorn.run(app, host="127.0.0.1", port=parser.parse_args().port, log_config=None)
