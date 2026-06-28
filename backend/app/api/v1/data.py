"""Market Data API endpoints."""
from fastapi import APIRouter, Query
from app.core.data.csv_adapter import CSVAdapter

router = APIRouter()
csv = CSVAdapter()


@router.get("/ohlcv")
async def get_ohlcv(symbol: str, start: str | None = None, end: str | None = None):
    df = csv.load_ohlcv(symbol, start, end)
    if df.empty:
        return {"data": [], "symbol": symbol, "message": "No data found. Upload CSV or configure Kite."}
    return {"data": df.tail(500).to_dict(orient="records"), "symbol": symbol, "rows": len(df)}


@router.get("/oi-chain")
async def get_oi_chain(underlying: str, expiry: str):
    chain = csv.load_options_chain(underlying, expiry)
    if chain.empty:
        return {"data": [], "underlying": underlying}
    return {"data": chain.to_dict(orient="records")}
