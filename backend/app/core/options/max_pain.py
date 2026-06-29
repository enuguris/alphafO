"""Max Pain calculator for NSE options expiry."""
import pandas as pd


def compute_max_pain(chain_df: pd.DataFrame) -> dict:
    """
    Compute max pain strike from options chain.

    Args:
        chain_df: DataFrame with columns [strike, ce_oi, pe_oi]

    Returns:
        dict with max_pain_strike, total_oi, pcr, ce_oi_total, pe_oi_total, pain_data
    """
    df = chain_df.copy()
    df = df.dropna(subset=["strike", "ce_oi", "pe_oi"])
    df["strike"] = df["strike"].astype(float)
    df["ce_oi"] = df["ce_oi"].astype(float)
    df["pe_oi"] = df["pe_oi"].astype(float)
    df = df.sort_values("strike").reset_index(drop=True)

    strikes = df["strike"].values
    ce_ois = df["ce_oi"].values
    pe_ois = df["pe_oi"].values

    pain_data = []
    for expiry_price in strikes:
        # CE writer loss: for all CE strikes < expiry_price, writers lose (expiry - strike) * oi
        ce_loss = sum(
            (expiry_price - s) * oi
            for s, oi in zip(strikes, ce_ois)
            if s < expiry_price
        )
        # PE writer loss: for all PE strikes > expiry_price, writers lose (strike - expiry) * oi
        pe_loss = sum(
            (s - expiry_price) * oi
            for s, oi in zip(strikes, pe_ois)
            if s > expiry_price
        )
        pain_data.append({
            "strike": int(expiry_price),
            "total_loss": ce_loss + pe_loss,
            "ce_loss": ce_loss,
            "pe_loss": pe_loss,
        })

    # Max pain = strike with minimum total writer loss
    min_loss_row = min(pain_data, key=lambda x: x["total_loss"])
    max_pain_strike = min_loss_row["strike"]

    ce_oi_total = float(df["ce_oi"].sum())
    pe_oi_total = float(df["pe_oi"].sum())
    total_oi = ce_oi_total + pe_oi_total
    pcr = pe_oi_total / ce_oi_total if ce_oi_total > 0 else 0.0

    return {
        "max_pain_strike": max_pain_strike,
        "total_oi": total_oi,
        "pcr": round(pcr, 3),
        "ce_oi_total": ce_oi_total,
        "pe_oi_total": pe_oi_total,
        "pain_data": pain_data,
    }
