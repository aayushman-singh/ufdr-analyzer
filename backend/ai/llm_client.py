"""
 LLM Client - Unified interface for OpenAI/OpenRouter/Anthropic APIs

 Converts natural language queries into structured search parameters      
 using LLM's JSON mode for consistent parsing.
"""

from typing import Dict, List, Any, Optional
import logging
import os
import json

logger = logging.getLogger(__name__)


class LLMClient:
    """
    Unified LLM client supporting OpenAI, OpenRouter, and Anthropic.
    Handles query understanding and converts NL → structured parameters.
    """

    def __init__(self, provider: str = "openai", model: Optional[str] = None):
        """
        Initialize LLM client.

        Args:
            provider: "openai", "openrouter", or "anthropic" (default is openai)
            model: Model name (uses defaults if not specified) (default is gpt-4o-mini)
        """
        self.provider = provider.lower()
        self.logger = logging.getLogger(__name__)

        # Set default models
        if model:
            self.model = model
        elif self.provider == "openai":
            self.model = "gpt-4o-mini"  # Fast, cheap, good for structured output (default is openai)
        elif self.provider == "openrouter":
            self.model = "deepseek/deepseek-chat-v3.1"  # Default OpenRouter model
        elif self.provider == "anthropic":
            self.model = "claude-3-5-sonnet-20241022"
        else:
            raise ValueError(f"Unsupported provider: {provider}")

        # Get API keys
        self.api_key = self._get_api_key()

        # Initialize provider-specific client
        self.client = self._initialize_client()

    def _get_api_key(self) -> str:
        """Fetch API key from environment."""
        if self.provider == "openai" or self.provider == "openrouter":
            key = os.getenv("OPENAI_API_KEY")
            if not key:
                raise ValueError("OPENAI_API_KEY environment variable not set")
            return key
        elif self.provider == "anthropic":
            key = os.getenv("ANTHROPIC_API_KEY")
            if not key:
                raise ValueError("ANTHROPIC_API_KEY environment variable not set")
            return key

        raise ValueError(f"No API key configured for provider: {self.provider}")

    def _initialize_client(self):
        """Initialize provider-specific SDK client."""
        try:
            if self.provider == "openai":
                from openai import OpenAI
                return OpenAI(api_key=self.api_key)
            elif self.provider == "openrouter":
                from openai import OpenAI
                return OpenAI(
                    base_url="https://openrouter.ai/api/v1",
                    api_key=self.api_key
                )
            elif self.provider == "anthropic":
                from anthropic import Anthropic
                return Anthropic(api_key=self.api_key)
        except ImportError as e:
            self.logger.error(f"Failed to import {self.provider} SDK: {e}")
            raise ImportError(
                f"Please install the {self.provider} SDK: "
                f"pip install {'openai' if self.provider in ['openai', 'openrouter'] else 'anthropic'}"
            )

    def parse_query(self, query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Convert natural language query to structured search parameters.

        Args:
            query: User's natural language query
            context: Optional context about the UFDR data (stats, available fields, etc.)

        Returns:
            Structured query parameters with intent, filters, entities
        """
        system_prompt = self._build_system_prompt(context)
        user_message = self._build_user_message(query)

        try:
            if self.provider == "openai" or self.provider == "openrouter":
                return self._query_openai(system_prompt, user_message)
            elif self.provider == "anthropic":
                return self._query_anthropic(system_prompt, user_message)
        except Exception as e:
            self.logger.error(f"LLM query failed: {e}")
            # Return fallback structure
            return {
                "intent": "unknown",
                "search_type": "keyword",
                "target_tables": ["messages"],
                "filters": {},
                "keywords": [query],
                "entities": [],
                "confidence": 0.0,
                "error": str(e)
            }
    def _build_system_prompt(self, context: Optional[Dict[str, Any]]) -> str:
        """Build system prompt explaining UFDR schema and task."""
        prompt = """You are a forensic data query assistant. Convert natural language queries into structured search parameters for UFDR (Universal Forensic Data 
Report) data.

**Available Data Tables:**
- messages: Text messages (sender, receiver, content, timestamp)
- calls: Call logs (caller, receiver, timestamp, duration)
- contacts: Contact list (name, number)
- media: Media files (path, type)
- aleapp_artifacts: Android forensic artifacts

**Query Intents:**
- crypto_search: Find cryptocurrency mentions (Bitcoin, Ethereum, wallet addresses)
- foreign_numbers: Find international phone numbers
- keyword_search: Search for specific keywords/phrases
- timeline: Time-based queries
- contact_search: Find specific contacts
- pattern_match: Regex or pattern-based search

**Output JSON Schema:**
{
  "intent": "string - primary intent",
  "search_type": "string - 'keyword', 'semantic', 'pattern', 'structured'",
  "target_tables": ["array of table names to search"],
  "filters": {
    "time_range": {"start": "ISO datetime", "end": "ISO datetime"},
    "phone_numbers": ["array of numbers to filter"],
    "keywords": ["array of search terms"]
  },
  "entities": [
    {"type": "phone|crypto|email|location", "value": "extracted value"}
  ],
  "keywords": ["array of search keywords"],
  "confidence": 0.0-1.0
}

Extract entities, classify intent, and generate search parameters."""

        # Add context if provided
        if context:
            prompt += f"\n\n**Current Run Context:**\n{json.dumps(context, indent=2)}"

        return prompt

    def _build_user_message(self, query: str) -> str:
        """Format user query message."""
        return f"Convert this query to structured search parameters:\n\n\"{query}\""

    def _query_openai(self, system_prompt: str, user_message: str) -> Dict[str, Any]:
        """Execute query using OpenAI API with JSON mode."""
        # Build base request params
        request_params = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            "response_format": {"type": "json_object"},  # Force JSON output
            "temperature": 0.1,  # Low temp for consistent structured output
            "max_tokens": 1000
        }

        # Add OpenRouter-specific headers if using OpenRouter
        if self.provider == "openrouter":
            request_params["extra_headers"] = {
                "HTTP-Referer": "https://github.com/aayushman-singh/ufdr-analyzer",
                "X-Title": "UFDR Analyzer"
            }

        response = self.client.chat.completions.create(**request_params)

        # Parse JSON response
        content = response.choices[0].message.content
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse OpenAI JSON response: {e}")
            self.logger.error(f"Raw response: {content}")
            raise

    def _query_anthropic(self, system_prompt: str, user_message: str) -> Dict[str, Any]:
        """Execute query using Anthropic API."""
        response = self.client.messages.create(
            model=self.model,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_message}
            ],
            temperature=0.1,
            max_tokens=1000
        )

        # Extract text content and parse JSON
        content = response.content[0].text
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse Anthropic JSON response: {e}")
            self.logger.error(f"Raw response: {content}")
            raise

    def generate_insights(self, query_results: Dict[str, Any], original_query: str, max_results: int = 50) -> str:
        """
        Generate natural language insights from query results.
        Token-efficient: No conversation history, only current results.

        Args:
            query_results: Structured results from query execution
            original_query: Original user query
            max_results: Maximum number of results to include in analysis (default 50)

        Returns:
            Natural language summary/insights with key findings
        """
        system_prompt = """You are a forensic analyst assistant. Your task:
1. Analyze query results and identify KEY PATTERNS and INSIGHTS
2. Highlight suspicious activities, important contacts, or critical evidence
3. Provide actionable intelligence for investigators
4. Be concise but thorough - focus on what matters

Format your response with:
- Executive Summary (2-3 sentences)
- Key Findings (bullet points of important patterns/entities)
- Recommended Next Steps (if applicable)"""

        # Build efficient result summary (limit data sent to LLM)
        result_count = query_results.get("total_results", 0)
        results = query_results.get("results", [])[:max_results]

        # Build compact summary instead of full JSON dumps
        result_summary = f"Query: '{original_query}'\n"
        result_summary += f"Total Results: {result_count}\n"
        result_summary += f"Analyzing: {len(results)} results\n\n"

        # Add results in compact format (not full JSON to save tokens)
        if results:
            result_summary += "Results:\n"
            for i, result in enumerate(results, 1):
                # Extract key fields based on result type
                result_type = result.get("type", "unknown")

                if result_type == "message":
                    result_summary += f"{i}. [MESSAGE] {result.get('sender', 'unknown')} → {result.get('receiver', 'unknown')}: {result.get('content', '')[:100]}... (at {result.get('timestamp', 'N/A')})\n"

                elif result_type == "call":
                    result_summary += f"{i}. [CALL] {result.get('caller', 'unknown')} ↔ {result.get('receiver', 'unknown')} - {result.get('duration', 'N/A')}s (at {result.get('timestamp', 'N/A')})\n"

                elif result_type == "contact":
                    result_summary += f"{i}. [CONTACT] {result.get('name', 'unknown')} - {result.get('phone_number', 'N/A')}\n"

                elif result_type == "media":
                    result_summary += f"{i}. [MEDIA] {result.get('file_path', 'N/A')} ({result.get('media_type', 'unknown')}) - {result.get('size', 'N/A')} bytes\n"

                else:
                    # Generic format for unknown types
                    result_summary += f"{i}. {json.dumps(result, indent=2)[:150]}...\n"

        user_message = f"Analyze these forensic query results and provide key insights:\n\n{result_summary}"

        try:
            if self.provider == "openai" or self.provider == "openrouter":
                # Build base request params
                request_params = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message}
                    ],
                    "temperature": 0.3,
                    "max_tokens": 800  # Increased for more detailed insights
                }

                # Add OpenRouter-specific headers if using OpenRouter
                if self.provider == "openrouter":
                    request_params["extra_headers"] = {
                        "HTTP-Referer": "https://github.com/aayushman-singh/ufdr-analyzer",
                        "X-Title": "UFDR Analyzer"
                    }

                response = self.client.chat.completions.create(**request_params)
                return response.choices[0].message.content

            elif self.provider == "anthropic":
                response = self.client.messages.create(
                    model=self.model,
                    system=system_prompt,
                    messages=[
                        {"role": "user", "content": user_message}
                    ],
                    temperature=0.3,
                    max_tokens=800
                )
                return response.content[0].text

        except Exception as e:
            self.logger.error(f"Failed to generate insights: {e}")
            return f"Found {result_count} results matching your query."
