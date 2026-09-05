"""
FastAPI server -- the entry point for the whole backend.
Exposes endpoints for chatting with the agent, viewing the catalog,
and viewing the audit trail.
"""
import uuid
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import agent
import catalog
import audit
from dotenv import load_dotenv
load_dotenv()

app = FastAPI(title="TeeStore AI Shopping Agent")

# Allow a frontend running on a different port (e.g. localhost:3000) to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory store of conversation history per session.
# Fine for a hackathon demo -- resets if the server restarts.
_sessions: dict[str, list] = {}


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str


class ChatResponse(BaseModel):
    session_id: str
    reply: str


@app.post("/chat", response_model=ChatResponse)
def chat_endpoint(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())[:8]
    history = _sessions.get(session_id, [])

    reply_text, updated_history = agent.chat(session_id, history, req.message)
    _sessions[session_id] = updated_history

    return ChatResponse(session_id=session_id, reply=reply_text)


@app.get("/products")
def list_products():
    return catalog.get_all_products()


@app.get("/logs")
def list_logs():
    """The audit trail -- this is what you show judges as proof of explainability."""
    return audit.get_logs()


@app.get("/")
def root():
    return {"status": "TeeStore AI Shopping Agent is running"}