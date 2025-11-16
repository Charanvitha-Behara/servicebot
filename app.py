# app.py
import os
import json
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from pydantic import BaseModel
from pymongo import MongoClient
from dotenv import load_dotenv
import requests
import wikipedia

from groq import Groq   # Correct SDK

load_dotenv()

# -------------------------------
# STATIC + TEMPLATE SERVING
# -------------------------------
app = FastAPI(title="ServiceBot API")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# -------------------------------
# ENV + DB CONFIG
# -------------------------------
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME", "servicebot_db")
GROQ_KEY = os.getenv("GROQ_API_KEY")
SEARCH_API_KEY = os.getenv("SEARCH_API_KEY")
SEARCH_ENGINE_ID = os.getenv("SEARCH_ENGINE_ID")

if not MONGO_URI:
    raise RuntimeError("MONGO_URI not set in .env")

if not GROQ_KEY:
    raise RuntimeError("GROQ_API_KEY not set in .env")

mongo_client = MongoClient(MONGO_URI)
db = mongo_client[DB_NAME]
knowledge_store = db["knowledge_store"]
chatlog = db["chatlog"]

groq = Groq(api_key=GROQ_KEY)


# -------------------------------
# MODELS
# -------------------------------
class Ask(BaseModel):
    question: str
    ask_forceshort: Optional[bool] = False


# -------------------------------
# HELPERS
# -------------------------------
def normalize_question(q: str) -> str:
    return " ".join(q.strip().lower().split())


def safe_search_online(query: str) -> str:
    """Google CSE → Wikipedia fallback."""
    if SEARCH_API_KEY and SEARCH_ENGINE_ID:
        try:
            url = (
                "https://www.googleapis.com/customsearch/v1?"
                f"key={SEARCH_API_KEY}&cx={SEARCH_ENGINE_ID}&q={requests.utils.requote_uri(query)}"
            )
            resp = requests.get(url, timeout=8)
            data = resp.json()
            if "items" in data:
                snippets = [item.get("snippet", "") for item in data["items"][:5]]
                return "\n".join(f"- {s}" for s in snippets if s)
        except:
            pass

    try:
        return wikipedia.summary(query, sentences=2)
    except:
        return ""


# --------------------------------------------------
# FIXED GROQ CHAT WRAPPER
# --------------------------------------------------
def groq_chat(system: str, user: str, model: str = "llama-3.1-8b-instant", max_tokens: int = 300):
    resp = groq.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
        temperature=0.2,
    )
    return resp.choices[0].message.content   # FIXED


def call_gpt_classify(question: str) -> dict:
    """Classify SHORT vs LONG."""
    prompt = (
        "Return ONLY JSON.\n"
        "Decide if the user wants a SHORT answer (1–3 sentences) or LONG answer.\n"
        f"Question: {question}\n\n"
        '{"answer_type":"short","confidence":0.8}'
    )

    raw = groq_chat(
        system="You ONLY return JSON.",
        user=prompt,
        max_tokens=40
    )

    try:
        data = json.loads(raw)
        return {
            "answer_type": data.get("answer_type", "short"),
            "confidence": float(data.get("confidence", 0.8))
        }
    except:
        return {"answer_type": "short", "confidence": 0.8}


def generate_answer(question: str, context: str, answer_type: str) -> str:
    if answer_type == "short":
        system = "Give a short, clear answer in 1–3 sentences."
        max_t = 200
    else:
        system = "Give a long, structured answer with headings and bullet points."
        max_t = 600

    prompt = f"Question: {question}\n\nContext:\n{context}\n\nAnswer:"
    return groq_chat(system, prompt, max_tokens=max_t)


def summarize_answer(answer: str) -> str:
    prompt = f"Summarize this in 1–3 sentences:\n\n{answer}"
    return groq_chat(
        system="Summarize clearly.",
        user=prompt,
        max_tokens=120
    ).strip()


def moderation_check(text: str) -> dict:
    banned = ["kill", "attack", "bomb", "suicide"]
    for w in banned:
        if w in text.lower():
            return {"safe": False, "reason": w}
    return {"safe": True, "reason": None}


def save_memory(question_norm: str, doc: dict):
    existing = knowledge_store.find_one({"question": question_norm})
    if existing:
        if existing.get("answer") == doc.get("answer"):
            return existing
        doc["variant_of"] = existing["_id"]

    inserted = knowledge_store.insert_one(doc)
    return knowledge_store.find_one({"_id": inserted.inserted_id})


def log_chat_entry(entry: dict):
    try:
        chatlog.insert_one(entry)
    except:
        pass


# -------------------------------
# MAIN ENDPOINT
# -------------------------------
@app.post("/ask")
def ask_bot(payload: Ask):
    question_raw = payload.question.strip()
    question_norm = normalize_question(question_raw)

    # Moderation
    mod = moderation_check(question_raw)
    if not mod["safe"]:
        raise HTTPException(400, "Blocked by moderation filter.")

    # Memory lookup
    existing = knowledge_store.find_one({"question": question_norm})
    if existing:
        log_chat_entry({"timestamp": datetime.utcnow(), "question": question_raw, "source": "memory"})
        return {
            "answer": existing["answer"],
            "answer_type": existing.get("answer_type", "short"),
            "source": "memory",
            "confidence": existing.get("confidence", 0.8),
        }

    # Online search
    context = safe_search_online(question_raw)

    # Classify short/long
    cls = call_gpt_classify(question_raw)
    if payload.ask_forceshort:
        cls["answer_type"] = "short"

    # Generate answer
    answer = generate_answer(question_raw, context, cls["answer_type"])

    # Summary if long
    summary = summarize_answer(answer) if cls["answer_type"] == "long" else answer

    # Save memory
    doc = {
        "question": question_norm,
        "question_raw": question_raw,
        "answer": answer,
        "summary": summary,
        "answer_type": cls["answer_type"],
        "confidence": cls["confidence"],
        "context": context,
        "source": "online+groq",
        "timestamp": datetime.utcnow(),
    }

    save_memory(question_norm, doc)
    log_chat_entry({"timestamp": datetime.utcnow(), "question": question_raw, "source": "online+groq"})

    return {
        "answer": answer,
        "answer_type": cls["answer_type"],
        "source": "online+groq",
        "confidence": cls["confidence"],
    }
