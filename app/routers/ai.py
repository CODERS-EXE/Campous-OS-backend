from typing import Annotated, List, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.deps import get_current_user, resolve_tenant
from app.models.college import College
from app.models.user import User
from app.services.ai import AiService

router = APIRouter(prefix="/ai", tags=["ai"])


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


class ChatResponse(BaseModel):
    reply: str
    suggested_questions: List[str]


class ChatMessageResponse(BaseModel):
    id: str
    sender: str
    content: str
    created_at: str


class SuggestionsResponse(BaseModel):
    suggestions: List[str]


@router.post("/chat", response_model=ChatResponse)
async def chat_with_ai(
    body: ChatRequest,
    user: Annotated[User, Depends(get_current_user)],
    college: Annotated[Optional[College], Depends(resolve_tenant)] = None,
):
    try:
        res = await AiService.process_chat(
            user=user,
            college=college,
            user_message=body.message
        )
        return ChatResponse(
            reply=res["reply"],
            suggested_questions=res["suggested_questions"]
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"AI processing failed: {str(exc)}"
        ) from exc


@router.get("/history", response_model=List[ChatMessageResponse])
async def get_ai_history(
    user: Annotated[User, Depends(get_current_user)],
):
    history = await AiService.get_chat_history(user_id=user.id)
    return [
        ChatMessageResponse(
            id=str(msg.id),
            sender=msg.sender,
            content=msg.content,
            created_at=msg.created_at.isoformat()
        )
        for msg in history
    ]


@router.delete("/history")
async def clear_ai_history(
    user: Annotated[User, Depends(get_current_user)],
):
    await AiService.clear_chat_history(user_id=user.id)
    return {"ok": True}


@router.get("/suggestions", response_model=SuggestionsResponse)
async def get_ai_suggestions(
    user: Annotated[User, Depends(get_current_user)],
):
    suggestions = AiService.get_role_suggestions(role=user.role)
    return SuggestionsResponse(suggestions=suggestions)
