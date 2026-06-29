"""Instrument universe API."""
from fastapi import APIRouter
from app.core.instruments import ALL_INSTRUMENTS, SECTOR_MAP, INSTRUMENT_MAP, all_symbols, priority_scan_list

router = APIRouter()


@router.get("/")
async def list_instruments(sector: str | None = None):
    """List all F&O instruments, optionally filtered by sector."""
    items = list(SECTOR_MAP.get(sector, {}).values()) if sector else ALL_INSTRUMENTS
    return {"instruments": ALL_INSTRUMENTS if not sector else SECTOR_MAP.get(sector, []), "count": len(ALL_INSTRUMENTS)}


@router.get("/sectors")
async def list_sectors():
    return {"sectors": sorted(SECTOR_MAP.keys()), "count": len(SECTOR_MAP)}


@router.get("/priority")
async def list_priority():
    return {"symbols": priority_scan_list()}


@router.get("/{sym}")
async def get_instrument(sym: str):
    inst = INSTRUMENT_MAP.get(sym.upper())
    if not inst:
        from fastapi import HTTPException
        raise HTTPException(404, f"Instrument {sym} not found")
    return inst
