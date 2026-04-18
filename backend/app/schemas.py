from datetime import datetime

from pydantic import BaseModel, Field


class RecognitionResponse(BaseModel):
    track: str
    artist: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class HistorySaveRequest(BaseModel):
    user_id: int = 1
    track: str
    artist: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    provider: str = "manual"


class HistoryItem(BaseModel):
    id: int
    user_id: int
    track: str
    artist: str
    confidence: float
    timestamp: datetime
    provider: str

    class Config:
        from_attributes = True
