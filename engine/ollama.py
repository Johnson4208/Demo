import requests
from config import OLLAMA_ENABLED, OLLAMA_URL, OLLAMA_MODEL, REQUEST_TIMEOUT


def explain(question, evidence):
    if not OLLAMA_ENABLED:
        return "The evidence-based engine is available; generative explanations are disabled for this deployment."
    prompt = f"""You are a local financial research assistant.

USER QUESTION:
{question}

SUPPLIED EVIDENCE:
{evidence}

Rules:
- Use only the supplied evidence for company-specific facts and numbers.
- Never invent missing financial data.
- Clearly distinguish historical report data, derived ratios, and market-model estimates.
- If the dataset is incomplete, say so plainly.
- Do not promise future returns or certainty.
- For comparisons, explain trade-offs rather than choosing a winner from one metric.
- Keep the answer concise and readable for a normal user.
"""
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json().get("response", "No explanation returned.").strip()
    except Exception:
        # The deterministic engine remains useful when Ollama is not running.
        return "The local quantitative engine is available, but the natural-language Ollama assistant is currently unavailable."
