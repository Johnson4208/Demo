import requests
from config import OLLAMA_ENABLED, OLLAMA_MODEL, OLLAMA_URL, REQUEST_TIMEOUT


def explain(question, forecast):
    if not OLLAMA_ENABLED:
        return ""
    prompt=("You are an evidence-bound forecasting assistant. Do not invent facts. Summarize the supplied research, distinguish evidence from inference, and explain why the ranked probabilities differ. Return concise prose.\n\n"
            f"Question: {question}\nForecast data:\n{forecast}")
    r=requests.post(f"{OLLAMA_URL}/api/generate",json={"model":OLLAMA_MODEL,"prompt":prompt,"stream":False},timeout=REQUEST_TIMEOUT)
    r.raise_for_status(); return (r.json().get("response") or "").strip()
