import httpx
from config import BACKEND_URL, HEADERS

async def upsert_user(telegram_id: int):
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BACKEND_URL}/api/users/upsert",
            json={"telegram_id": telegram_id},
            headers=HEADERS
        )
        return resp.json()

async def start_exam(mode: str, telegram_id: int, course_id: int = None, topic_id: int = None):
    params = {"mode": mode}
    if course_id:
        params["course_id"] = course_id
    if topic_id:
        params["topic_id"] = topic_id

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BACKEND_URL}/api/exam/start",
            params=params,
            headers=HEADERS
        )
        return resp.json()

async def get_next_question(session_id: str):
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BACKEND_URL}/api/exam/next/{session_id}",
            headers=HEADERS
        )
        return resp.json()

async def submit_answer(session_id: str, question_id: int, answer: str):
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BACKEND_URL}/api/exam/answer",
            json={
                "session_id": session_id,
                "question_id": question_id,
                "answer": answer
            },
            headers=HEADERS
        )
        return resp.json()

async def get_ai_explanation(telegram_id: int, question_id: int, user_answer: str = None):
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BACKEND_URL}/api/ai/explain",
            json={
                "telegram_id": telegram_id,
                "question_id": question_id,
                "user_answer": user_answer
            },
            headers=HEADERS
        )
        return resp.json()