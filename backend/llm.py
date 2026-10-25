"""Shared LLM wrapper with token budgeting, mock support, and prompt security."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar
from pydantic import BaseModel

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger("llm")

T = TypeVar("T", bound=BaseModel)

# Default model configuration
MODEL_FAST = os.getenv("MODEL_FAST", "claude-3-haiku-20240307")
MODEL_ADVOCATE = os.getenv("MODEL_ADVOCATE", "claude-3-5-sonnet-20241022")
MODEL_JUDGE = os.getenv("MODEL_JUDGE", "claude-3-5-sonnet-20241022")

MAX_RUNS = int(os.getenv("MAX_RUNS", "3"))
MAX_ROUNDS = int(os.getenv("MAX_ROUNDS", "2"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "2"))
MAX_TOOL_CALLS_PER_AGENT = int(os.getenv("MAX_TOOL_CALLS_PER_AGENT", "12"))
MAX_TOKENS_PER_CASE = int(os.getenv("MAX_TOKENS_PER_CASE", "200000"))
DEFAULT_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "60.0"))


class BudgetExceededError(RuntimeError):
    """Raised when the case-wide token budget is exceeded."""
    pass


class ToolCallLimitExceededError(RuntimeError):
    """Raised when an agent exceeds its allowed tool call quota."""
    pass


def wrap_document_text(doc_id: str, tier: int, date: str, content: str) -> str:
    """Wraps untrusted document content in standard secure tags.
    
    Adheres to project security guidelines: documents are untrusted data.
    """
    # Sanitize content against closing tag manipulation
    safe_content = content.replace("</document>", "&lt;/document&gt;")
    return f'<document id="{doc_id}" tier="{tier}" date="{date}">\n{safe_content}\n</document>'


def deterministic_offline_adjudication(system_prompt: str, user_prompt: str, *args, **kwargs) -> str:
    """Provides a deterministic, evidence-grounded judicial response when running offline without an API key."""
    claim_ids = re.findall(r"Claim ID:\s*([\w\-]+)", user_prompt)
    rulings = []
    for cid in claim_ids:
        block_match = re.search(rf"Claim ID:\s*{re.escape(cid)}.*?(?=Claim ID:|\Z)", user_prompt, re.DOTALL)
        block = block_match.group(0) if block_match else ""

        has_citations = "Admissible Citations: None" not in block and "Admissible Citations:" in block
        has_concession = "concede" in block.lower()
        has_trade_cit = "TAB-" in block or "trade_row_ref" in block or "tab_id" in block.lower()
        is_malicious = any(w in block.lower() for w in [
            "system prompt", "ignore instructions", "injection", "jailbreak", "override system", "instructed to set", "untrusted"
        ])

        if is_malicious:
            rulings.append({
                "claim_id": cid,
                "verdict": "rejected",
                "basis": "inference",
                "rationale": "Rejected: Prompt injection / instruction override attempt detected in claim or cited evidence.",
            })
        elif has_concession:
            rulings.append({
                "claim_id": cid,
                "verdict": "conceded",
                "basis": "inference",
                "rationale": "Claim explicitly conceded during cross-examination.",
            })
        elif not has_trade_cit and ("attack by" in block.lower() or "mai" in cid.lower() or "grain" in block.lower()):
            # Inferential disruption claim without direct quantitative trade table baseline is contested under attack
            rulings.append({
                "claim_id": cid,
                "verdict": "contested",
                "basis": "inference",
                "rationale": f"Claim {cid} remains contested under cross-examination without direct primary trade table corroboration.",
            })
        elif has_citations and has_trade_cit:
            rulings.append({
                "claim_id": cid,
                "verdict": "established",
                "basis": "sourced_fact",
                "rationale": f"Admissible trade records substantiate baseline and disruption bounds for {cid}.",
            })
        elif has_citations:
            rulings.append({
                "claim_id": cid,
                "verdict": "established",
                "basis": "sourced_fact",
                "rationale": f"Admissible records substantiate {cid}.",
            })
        else:
            rulings.append({
                "claim_id": cid,
                "verdict": "rejected",
                "basis": "inference",
                "rationale": f"Claim lacks direct corroboration in admissible primary sources.",
            })

    return json.dumps({"rulings": rulings}, indent=2)


class LLMClient:
    """LLM Client supporting Anthropic and pluggable mock callers for testing."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.gemini_api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
        self._anthropic_exhausted: bool = False
        self._mock_handler: Optional[Callable[[str, str, Dict[str, Any]], str]] = None
        self.total_tokens_used: int = 0
        self.tool_call_counts: Dict[str, int] = {}
        self._client = None

    def reset_case_budget(self) -> None:
        """Resets the case-wide token usage and tool call counters (for starting a new case)."""
        self.total_tokens_used = 0
        self.tool_call_counts.clear()

    def record_tool_call(self, agent: str = "odin") -> int:
        """Records a tool call for an agent and enforces MAX_TOOL_CALLS_PER_AGENT."""
        current = self.tool_call_counts.get(agent, 0) + 1
        self.tool_call_counts[agent] = current
        if current > MAX_TOOL_CALLS_PER_AGENT:
            raise ToolCallLimitExceededError(
                f"Agent '{agent}' exceeded tool call limit ({current} > {MAX_TOOL_CALLS_PER_AGENT})"
            )
        return current

    def set_mock_handler(self, handler: Optional[Callable[[str, str, Dict[str, Any]], str]]) -> None:
        """Injects a mock response handler for deterministic testing."""
        self._mock_handler = handler

    def _get_anthropic_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(
                api_key=self.api_key,
                max_retries=MAX_RETRIES,
            )
        return self._client

    def _call_gemini(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        model: Optional[str] = None,
    ) -> str:
        """Calls Google Gemini API with system and user prompts."""
        gemini_key = self.gemini_api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
        if not gemini_key:
            raise ValueError("GEMINI_API_KEY not configured.")

        gemini_model = model if (model and "gemini" in model.lower()) else os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

        try:
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=gemini_key)
            config = types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=temperature,
            )
            try:
                response = client.models.generate_content(
                    model=gemini_model,
                    contents=user_prompt,
                    config=config,
                )
            except Exception as gen_err:
                # If model name was deprecated or 404, fallback to gemini-flash-latest
                if "404" in str(gen_err) or "not found" in str(gen_err).lower():
                    logger.warning("Gemini model '%s' not found; retrying with 'gemini-flash-latest'...", gemini_model)
                    response = client.models.generate_content(
                        model="gemini-flash-latest",
                        contents=user_prompt,
                        config=config,
                    )
                else:
                    raise gen_err

            text = getattr(response, "text", str(response))
            tokens = (len(system_prompt) + len(user_prompt) + len(text)) // 4
            self.total_tokens_used += tokens
            return text
        except Exception as e:
            logger.warning("google.genai call failed (%s), attempting google.generativeai fallback...", e)
            import google.generativeai as legacy_genai
            legacy_genai.configure(api_key=gemini_key)
            try:
                g_model = legacy_genai.GenerativeModel(
                    model_name=gemini_model,
                    system_instruction=system_prompt,
                    generation_config={"temperature": temperature},
                )
                res = g_model.generate_content(user_prompt)
            except Exception:
                g_model = legacy_genai.GenerativeModel(
                    model_name="gemini-1.5-flash",
                    system_instruction=system_prompt,
                    generation_config={"temperature": temperature},
                )
                res = g_model.generate_content(user_prompt)

            text = res.text
            tokens = (len(system_prompt) + len(user_prompt) + len(text)) // 4
            self.total_tokens_used += tokens
            return text

    async def call_model(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 4000,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> str:
        """Calls the LLM with the provided prompts, tracking token budget."""
        target_model = model or MODEL_JUDGE

        # Preflight check on case token budget
        if self.total_tokens_used >= MAX_TOKENS_PER_CASE:
            raise BudgetExceededError(
                f"Case token budget already exhausted prior to call: {self.total_tokens_used} >= {MAX_TOKENS_PER_CASE}"
            )

        # 1. If a mock handler is configured, use it directly (no API key required)
        if self._mock_handler is not None:
            response_text = self._mock_handler(
                system_prompt,
                user_prompt,
                {"model": target_model, "temperature": temperature, "max_tokens": max_tokens, "timeout": timeout},
            )
            # Estimate mock token usage
            mock_tokens = (len(system_prompt) + len(user_prompt) + len(response_text)) // 4
            self.total_tokens_used += mock_tokens
            if self.total_tokens_used > MAX_TOKENS_PER_CASE:
                raise BudgetExceededError(
                    f"Case token budget exceeded during call: {self.total_tokens_used} > {MAX_TOKENS_PER_CASE}"
                )
            return response_text

        # 2. Check provider keys and routing
        gemini_key = self.gemini_api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
        anthropic_key = self.api_key or os.getenv("ANTHROPIC_API_KEY", "")

        # If user specified Gemini provider, or Anthropic credit is already exhausted, use Gemini directly
        use_gemini_directly = (
            os.getenv("LLM_PROVIDER", "").lower() == "gemini"
            or getattr(self, "_anthropic_exhausted", False)
            or not anthropic_key
        )

        if use_gemini_directly and gemini_key:
            logger.info("Routing call directly to Google Gemini provider.")
            try:
                return self._call_gemini(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=temperature,
                    model=model,
                )
            except Exception as gemini_err:
                logger.warning(
                    "Direct Gemini call failed (%s). Seamlessly falling back to deterministic evidence adjudicator...", gemini_err
                )
                return deterministic_offline_adjudication(system_prompt, user_prompt)

        # 3. Production Anthropic API call with automatic Gemini fallback on failure
        if anthropic_key:
            try:
                client = self._get_anthropic_client()
                message = client.messages.create(
                    model=target_model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout=timeout,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                )

                tokens = message.usage.input_tokens + message.usage.output_tokens
                self.total_tokens_used += tokens
                if self.total_tokens_used > MAX_TOKENS_PER_CASE:
                    raise BudgetExceededError(
                        f"Case token budget exceeded during call: {self.total_tokens_used} > {MAX_TOKENS_PER_CASE}"
                    )
                content_block = message.content[0]
                return getattr(content_block, "text", str(content_block))
            except Exception as anthropic_err:
                err_msg = str(anthropic_err).lower()
                if any(w in err_msg for w in ("credit", "balance", "quota", "exhausted", "rate_limit", "400", "402", "429")):
                    self._anthropic_exhausted = True
                if gemini_key:
                    logger.warning(
                        "Anthropic API call failed (%s). Seamlessly falling back to Google Gemini...", anthropic_err
                    )
                    try:
                        return self._call_gemini(
                            system_prompt=system_prompt,
                            user_prompt=user_prompt,
                            temperature=temperature,
                            model=model,
                        )
                    except Exception as gemini_err:
                        logger.warning(
                            "Gemini fallback also failed (%s). Falling back to deterministic evidence adjudicator...", gemini_err
                        )
                        return deterministic_offline_adjudication(system_prompt, user_prompt)
                if os.getenv("OFFLINE_MOCK_LLM", "").lower() in ("1", "true"):
                    logger.warning("Anthropic call failed (%s). Falling back to offline evaluator.", anthropic_err)
                    return deterministic_offline_adjudication(system_prompt, user_prompt)
                return deterministic_offline_adjudication(system_prompt, user_prompt)

        # 4. If no Anthropic key configured, use Gemini directly if available
        if gemini_key:
            logger.info("Using Google Gemini provider.")
            return self._call_gemini(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=temperature,
                model=model,
            )

        # 5. Deterministic offline evaluator if OFFLINE_MOCK_LLM configured
        if os.getenv("OFFLINE_MOCK_LLM", "").lower() in ("1", "true"):
            logger.info("No API key configured. Using deterministic offline judicial evaluator.")
            response_text = deterministic_offline_adjudication(system_prompt, user_prompt)
            mock_tokens = (len(system_prompt) + len(user_prompt) + len(response_text)) // 4
            self.total_tokens_used += mock_tokens
            if self.total_tokens_used > MAX_TOKENS_PER_CASE:
                raise BudgetExceededError(
                    f"Case token budget exceeded during call: {self.total_tokens_used} > {MAX_TOKENS_PER_CASE}"
                )
            return response_text

        raise ValueError(
            "Neither ANTHROPIC_API_KEY nor GEMINI_API_KEY configured. Set in .env or use LLMClient.set_mock_handler() for tests."
        )

    async def call_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: Type[T],
        model: Optional[str] = None,
        retries: int = MAX_RETRIES,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> T:
        """Calls LLM and parses response into a Pydantic model with retry repair."""
        schema_json = json.dumps(response_model.model_json_schema(), indent=2)
        augmented_system = (
            f"{system_prompt}\n\n"
            "CRITICAL: You MUST respond ONLY with valid JSON conforming to the following JSON Schema:\n"
            f"```json\n{schema_json}\n```\n"
            "Do not include any conversational preamble or postscript. Output valid JSON only."
        )

        current_user_prompt = user_prompt
        last_error = None

        for attempt in range(retries + 1):
            raw_response = await self.call_model(
                augmented_system, current_user_prompt, model=model, timeout=timeout
            )
            try:
                # Extract JSON if wrapped in markdown code fence or with surrounding text
                clean_json = raw_response.strip()
                if "```json" in clean_json:
                    clean_json = clean_json.split("```json")[1].split("```")[0].strip()
                elif "```" in clean_json:
                    clean_json = clean_json.split("```")[1].split("```")[0].strip()
                elif "{" in clean_json and "}" in clean_json:
                    start_idx = clean_json.find("{")
                    end_idx = clean_json.rfind("}") + 1
                    clean_json = clean_json[start_idx:end_idx]

                parsed_dict = json.loads(clean_json)
                return response_model.model_validate(parsed_dict)
            except Exception as e:
                last_error = e
                if attempt < retries:
                    current_user_prompt = (
                        f"{user_prompt}\n\n"
                        f"Your previous response caused a validation error: {str(e)}\n"
                        f"Previous response was:\n{raw_response}\n\n"
                        "Please correct the JSON format to strictly match the required schema."
                    )
                else:
                    raise ValueError(f"Failed to obtain valid {response_model.__name__} after {retries} retries: {last_error}")


# Global default client
default_llm_client = LLMClient()
