"""
NSE F&O Options — brokerage and statutory charges calculator.

All rates as per Zerodha fee schedule and SEBI/exchange circulars (2025-26).
Every paper and live trade must pass through this before booking P&L.
"""
from dataclasses import dataclass


@dataclass
class ChargeBreakdown:
    brokerage:       float   # Zerodha flat ₹20 per order, capped at 0.03% of premium
    stt:             float   # Securities Transaction Tax — sell side only
    exchange_txn:    float   # NSE transaction charge (0.053% of premium turnover)
    gst:             float   # 18% on (brokerage + exchange_txn)
    sebi:            float   # ₹10 per crore of turnover
    stamp_duty:      float   # 0.003% on buy side only
    total:           float   # sum of all charges
    net_pnl: float = 0.0     # gross P&L minus total charges (set by caller)

    def as_dict(self) -> dict:
        return {
            "brokerage":    round(self.brokerage, 2),
            "stt":          round(self.stt, 2),
            "exchange_txn": round(self.exchange_txn, 2),
            "gst":          round(self.gst, 2),
            "sebi":         round(self.sebi, 2),
            "stamp_duty":   round(self.stamp_duty, 2),
            "total":        round(self.total, 2),
            "net_pnl":      round(self.net_pnl, 2),
        }


def calculate_charges(
    entry_premium: float,
    exit_premium: float,
    quantity: int,           # total units = lots × lot_size
    action: str,             # "BUY" | "SELL" (opening direction)
) -> ChargeBreakdown:
    """
    Compute full charge breakdown for one round-trip options trade.

    Args:
        entry_premium: premium paid/received per unit at entry
        exit_premium:  premium paid/received per unit at exit
        quantity:      total units (lot_size × number_of_lots)
        action:        "BUY" to open (buy CE/PE), "SELL" to open (sell CE/PE)

    NSE F&O options rates (Zerodha, 2025-26):
        Brokerage:          ₹20 per order or 0.03% of premium (lower), each leg
        STT:                0.1% on sell side premium (rate effective Oct 2024)
        Exchange txn charge:0.053% of total premium turnover (both legs)
        GST:                18% on (brokerage + exchange txn charge)
        SEBI charges:       ₹10 per crore of turnover
        Stamp duty:         0.003% on buy side premium only
    """
    entry_turnover = entry_premium * quantity
    exit_turnover  = exit_premium  * quantity
    total_turnover = entry_turnover + exit_turnover

    # ── Brokerage ──────────────────────────────────────────────────────────────
    # ₹20 per order OR 0.03% of premium, whichever is lower — applied per leg
    brokerage_entry = min(20.0, entry_turnover * 0.0003)
    brokerage_exit  = min(20.0, exit_turnover  * 0.0003)
    brokerage = brokerage_entry + brokerage_exit

    # ── STT ────────────────────────────────────────────────────────────────────
    # 0.1% on sell-side premium (raised from 0.0625% effective 1 Oct 2024).
    # For BUY-to-open: sell happens at exit
    # For SELL-to-open: sell happens at entry
    if action.upper() == "BUY":
        stt_turnover = exit_turnover      # sell to close
    else:
        stt_turnover = entry_turnover     # sell to open

    stt = stt_turnover * 0.001

    # ── Exchange transaction charge ────────────────────────────────────────────
    exchange_txn = total_turnover * 0.00053

    # ── GST ───────────────────────────────────────────────────────────────────
    gst = (brokerage + exchange_txn) * 0.18

    # ── SEBI charges ──────────────────────────────────────────────────────────
    sebi = (total_turnover / 1_00_00_000) * 10.0     # ₹10 per crore

    # ── Stamp duty ────────────────────────────────────────────────────────────
    # 0.003% on buy-side only
    if action.upper() == "BUY":
        stamp_turnover = entry_turnover
    else:
        stamp_turnover = exit_turnover    # buy-to-close leg

    stamp_duty = stamp_turnover * 0.00003

    total = brokerage + stt + exchange_txn + gst + sebi + stamp_duty

    return ChargeBreakdown(
        brokerage=brokerage,
        stt=stt,
        exchange_txn=exchange_txn,
        gst=gst,
        sebi=sebi,
        stamp_duty=stamp_duty,
        total=total,
    )


def charges_for_entry_only(
    premium: float,
    quantity: int,
    action: str,
) -> float:
    """
    Charges deducted at trade entry (brokerage + stamp duty on buy, STT on sell).
    Used to reduce available capital at time of order.
    """
    turnover = premium * quantity
    brokerage  = min(20.0, turnover * 0.0003)
    stamp_duty = turnover * 0.00003 if action.upper() == "BUY" else 0.0
    stt_entry  = turnover * 0.000125 if action.upper() == "SELL" else 0.0
    gst        = (brokerage + turnover * 0.00053) * 0.18
    return round(brokerage + stamp_duty + stt_entry + gst, 2)
