import time
import logging
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from app.config import settings

log = logging.getLogger("brain.llm")


class LLMUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMResponse(BaseModel):
    text: str = ""
    tool_calls: List[Dict[str, Any]] = []
    usage: LLMUsage = LLMUsage()
    latency_ms: float = 0.0
    model: str = ""


class LLMClient:
    """
    Configurable LLM client wrapper designed for seamless model & provider switching.
    Supports OpenAI, Anthropic, and compatible proxies.
    """

    def __init__(self):
        self._openai_client = None

    def _get_openai_client(self):
        if self._openai_client is None:
            import openai
            api_key = settings.OPENAI_API_KEY or settings.CODECRAFT_KEY
            base_url = settings.OPENAI_BASE_URL or None
            self._openai_client = openai.OpenAI(
                api_key=api_key or "sk-dummy",
                base_url=base_url,
                max_retries=1,
                timeout=25.0
            )
        return self._openai_client

    def complete(
        self,
        system: str,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        max_tokens: int = 800,
        temperature: float = 0.2,
        tools: Optional[List[Dict[str, Any]]] = None,
        retries: int = 0
    ) -> LLMResponse:
        """
        Executes a completion with automated retries, latency timing, and token accounting.
        """
        chosen_model = model or settings.SUBAGENT_MODEL
        start_time = time.perf_counter()

        api_key = settings.OPENAI_API_KEY or settings.CODECRAFT_KEY
        if not api_key:
            raise RuntimeError("No LLM API key configured in environment.")

        formatted_messages = []
        if system:
            formatted_messages.append({"role": "system", "content": system})
        formatted_messages.extend(messages)

        last_error = None
        for attempt in range(retries + 1):
            try:
                client = self._get_openai_client()
                kwargs: Dict[str, Any] = {
                    "model": chosen_model,
                    "messages": formatted_messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                }
                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = "auto"

                resp = client.chat.completions.create(**kwargs)
                latency = (time.perf_counter() - start_time) * 1000

                choice = resp.choices[0]
                text_content = choice.message.content or ""
                extracted_tool_calls = []

                if choice.message.tool_calls:
                    for tc in choice.message.tool_calls:
                        extracted_tool_calls.append({
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments
                            }
                        })

                usage = LLMUsage()
                if resp.usage:
                    usage = LLMUsage(
                        prompt_tokens=resp.usage.prompt_tokens,
                        completion_tokens=resp.usage.completion_tokens,
                        total_tokens=resp.usage.total_tokens
                    )

                log.info(
                    "LLM complete model=%s latency_ms=%.1f tokens=%d",
                    chosen_model,
                    latency,
                    usage.total_tokens
                )

                return LLMResponse(
                    text=text_content,
                    tool_calls=extracted_tool_calls,
                    usage=usage,
                    latency_ms=round(latency, 2),
                    model=chosen_model
                )
            except Exception as e:
                last_error = e
                log.warning("LLM complete attempt %d failed: %s", attempt + 1, e)
                if attempt < retries:
                    time.sleep(1.0 * (attempt + 1))

        latency = (time.perf_counter() - start_time) * 1000
        log.error("LLM complete failed after %d attempts: %s", retries + 1, last_error)
        raise RuntimeError(f"LLM call failed: {last_error}") from last_error

    def embed(self, text: str, model: Optional[str] = None) -> List[float]:
        """
        Generates text embedding vector.
        """
        chosen_model = model or settings.EMBEDDING_MODEL
        client = self._get_openai_client()
        resp = client.embeddings.create(input=[text], model=chosen_model)
        return resp.data[0].embedding


llm_client = LLMClient()
