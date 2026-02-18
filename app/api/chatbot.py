from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from app.core.dependencies import get_db
from app.services.chatbot import ChatbotService
from app.schemas.chatbot import ChatStartResponse, ChatMessageRequest, ChatMessageResponse

router = APIRouter(prefix="/chat", tags=["Chatbot"])

@router.post("/start", response_model=ChatStartResponse, summary="Start a new chat session")
def start_chat(db: Session = Depends(get_db)):
    return ChatbotService.start_chat(db)

@router.post("/message", response_model=ChatMessageResponse, summary="Send a message to the chatbot")
def send_message(request: ChatMessageRequest, db: Session = Depends(get_db)):
    result = ChatbotService.handle_message(db, request.sessionId, request.message)
    if not result:
        raise HTTPException(status_code=404, detail="Session or Lead not found")
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result
