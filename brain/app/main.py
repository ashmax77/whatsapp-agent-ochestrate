from fastapi import FastAPI, HTTPException
from app.schemas import ChatRequest, ChatResponse
from app.state.session import session_manager
from app.agents.orchestrator import orchestrator
from app.config import settings

app = FastAPI(title=settings.PROJECT_NAME, version="0.1.0")

@app.get("/")
def health_check():
    return {"status": "ok", "service": settings.PROJECT_NAME}

@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    try:
        session = session_manager.get_or_create(request.senderId)
        reply = await orchestrator.handle_message(session, request.message)
        return ChatResponse(reply=reply, metadata={"senderId": request.senderId})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)

