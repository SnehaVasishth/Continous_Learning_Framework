from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import kb
from ..db import Base, SessionLocal, engine, get_db
from ..synthetic.generate import seed_all

router = APIRouter()


@router.post("/reset")
def reset():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        kb_counts = kb.seed_defaults(db)
        counts = seed_all(db, wipe=True)
    finally:
        db.close()
    return {"ok": True, "counts": counts, "kb_counts": kb_counts}


@router.post("/topup")
def topup(db: Session = Depends(get_db)):
    kb_counts = kb.seed_defaults(db)
    counts = seed_all(db, wipe=False)
    return {"ok": True, "counts": counts, "kb_counts": kb_counts}
