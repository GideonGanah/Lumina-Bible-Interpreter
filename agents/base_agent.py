import asyncio
import json
import os
import re

import httpx
from dotenv import load_dotenv

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL", "qwen3:8b")


class BaseAgent:
    def __init__(self, model_name: str = None):
        self.model = model_name or OLLAMA_MODEL
        self.base_url = OLLAMA_BASE_URL

    async def call_gemini(self, system_prompt: str, user_prompt: str) -> dict:
        """Unified entry-point kept as call_gemini for backward compat; now calls Ollama."""
        return await self._call_ollama(system_prompt, user_prompt)

    async def _call_ollama(self, system_prompt: str, user_prompt: str) -> dict:
        payload = {
            "model": self.model,
            "stream": False,
            "options": {
                "temperature": 0.2,
                "num_predict": 4096,
            },
            "messages": [
                {
                    "role": "system",
                    "content": (
                        system_prompt
                        + "\n\nCRITICAL RULE: Your ENTIRE response must be ONLY a valid JSON object. "
                        "No markdown, no explanation, no text before or after the JSON. "
                        "Start your response with '{' and end with '}'."
                    )
                },
                {
                    "role": "user",
                    "content": user_prompt
                }
            ]
        }

        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(300.0)   # 5 min – local LLM can be slow
            ) as client:
                r = await client.post("/api/chat", json=payload)
                r.raise_for_status()
                data = r.json()

            raw = data.get("message", {}).get("content", "").strip()

            # Strip <think>...</think> blocks (qwen3 chain-of-thought)
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

            # Strip markdown fences if present
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\s*", "", raw)
                raw = re.sub(r"\s*```$", "", raw)
                raw = raw.strip()

            # Extract JSON: find first { and last }
            start = raw.find("{")
            end   = raw.rfind("}")
            if start != -1 and end != -1 and end > start:
                raw = raw[start:end+1]

            return json.loads(raw)

        except json.JSONDecodeError:
            # Try to extract the first JSON object from the response
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except Exception:
                    pass
            return {"error": "JSON parse failed", "raw": raw[:500]}

        except httpx.ConnectError:
            return {
                "error": "OLLAMA_OFFLINE",
                "message": "Cannot connect to Ollama. Make sure it is running: 'ollama serve'"
            }

        except Exception as e:
            return {"error": str(e)[:300]}
