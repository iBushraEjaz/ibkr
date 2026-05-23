from datetime import date, datetime
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Trade

router = APIRouter(prefix="/trades", tags=["trades"])


@router.get("/today")
def get_today_trades(db: Session = Depends(get_db)):
    today_start = datetime.combine(date.today(), datetime.min.time())
    trades = db.query(Trade).filter(Trade.timestamp >= today_start).order_by(Trade.timestamp).all()
    return [
        {
            "id": t.id,
            "symbol": t.symbol,
            "side": t.side,
            "shares": t.shares,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "pnl": t.pnl,
            "timestamp": t.timestamp.isoformat(),
        }
        for t in trades
    ]
