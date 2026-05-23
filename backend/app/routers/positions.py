from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Position

router = APIRouter(prefix="/positions", tags=["positions"])


@router.get("/")
def get_positions(db: Session = Depends(get_db)):
    positions = db.query(Position).all()
    return [
        {
            "symbol": p.symbol,
            "shares": p.shares,
            "entry_price": p.entry_price,
            "current_price": p.current_price,
            "stop": p.stop,
            "pnl": p.pnl,
        }
        for p in positions
    ]
