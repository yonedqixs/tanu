from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, engine, get_db
from app.models import RecognitionHistory
from app.schemas import HistoryItem, HistorySaveRequest, RecognitionResponse
from app.services.recognition import RecognitionError, recognize_audio


app = FastAPI(title=settings.app_name)

base_dir = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(base_dir / "templates"))
app.mount("/static", StaticFiles(directory=str(base_dir / "static")), name="static")


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health_check() -> dict:
    return {"status": "ok", "service": settings.app_name}


@app.post("/recognize", response_model=RecognitionResponse)
async def recognize(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> RecognitionResponse:
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio payload")

    try:
        result = await recognize_audio(audio_bytes)
    except RecognitionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Unexpected recognition error: {exc}") from exc

    history_item = RecognitionHistory(
        user_id=1,
        track=result.track,
        artist=result.artist,
        confidence=result.confidence,
        provider=result.provider,
    )
    db.add(history_item)
    db.commit()

    return RecognitionResponse(
        track=result.track,
        artist=result.artist,
        confidence=result.confidence,
    )


@app.post("/history/save", response_model=HistoryItem)
def save_history(payload: HistorySaveRequest, db: Session = Depends(get_db)) -> HistoryItem:
    record = RecognitionHistory(
        user_id=payload.user_id,
        track=payload.track,
        artist=payload.artist,
        confidence=payload.confidence,
        provider=payload.provider,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return HistoryItem.model_validate(record)


@app.get("/history", response_model=list[HistoryItem])
def get_history(db: Session = Depends(get_db)) -> list[HistoryItem]:
    stmt = select(RecognitionHistory).order_by(RecognitionHistory.timestamp.desc(), RecognitionHistory.id.desc())
    rows = db.execute(stmt).scalars().all()
    return [HistoryItem.model_validate(row) for row in rows]


@app.get("/", response_class=HTMLResponse)
def history_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    stmt = select(RecognitionHistory).order_by(RecognitionHistory.timestamp.desc(), RecognitionHistory.id.desc())
    rows = db.execute(stmt).scalars().all()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"items": rows, "app_name": settings.app_name},
    )
