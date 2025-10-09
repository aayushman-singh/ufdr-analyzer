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
        prompt = """You are an intelligent forensic data query assistant. Your job is to understand conversational queries and convert them into structured search parameters for Android device forensic data.

**Available Data Sources:**

1. **messages**: Generic SMS/text messages (sender, receiver, content, timestamp)
2. **calls**: Call logs (caller, receiver, timestamp, duration)
3. **contacts**: Contact list (name, number)
4. **media**: Media files (path, type, size)
5. **aleapp_artifacts**: ANDROID APP-SPECIFIC DATA extracted by ALEAPP
   - WhatsApp messages, calls, media
   - Instagram DMs, stories
   - Snapchat messages
   - Facebook Messenger
   - Chrome browsing history
   - And 100+ other Android app artifacts

**Understanding App-Specific Queries:**

When users ask about specific apps, you MUST search aleapp_artifacts:
- "WhatsApp messages" → search aleapp_artifacts with app_name filter "WhatsApp"
- "Instagram DMs" → search aleapp_artifacts with app_name filter "Instagram"
- "Chrome history" → search aleapp_artifacts with app_name filter "Chrome"
- "all social media" → search aleapp_artifacts with category filter "social_media"

**Query Intents (be smart!):**
- app_specific: Queries about specific apps (WhatsApp, Instagram, etc.) - USE ALEAPP_ARTIFACTS!
- crypto_search: Cryptocurrency mentions (Bitcoin, Ethereum, wallet addresses)
- foreign_numbers: International phone numbers
- keyword_search: Generic keyword searches across multiple tables
- timeline: Time-based queries
- contact_search: Specific contacts
- pattern_match: Regex or pattern-based search
- conversational: General "show me", "find", "list" queries

**Search Strategy:**
- Default to "hybrid" search (combines keyword + semantic) for best results
- Use "semantic" for conceptual queries ("suspicious activity", "planning something")
- Use "keyword" only for exact term matching

**Output JSON Schema:**
{
  "intent": "string - primary intent (use 'app_specific' for app queries!)",
  "search_type": "string - 'keyword', 'semantic', or 'hybrid' (default: hybrid)",
  "target_tables": ["array - ALWAYS include 'aleapp_artifacts' for app queries"],
  "filters": {
    "time_range": {"start": "ISO datetime or null", "end": "ISO datetime or null"},
    "phone_numbers": ["array of numbers"],
    "keywords": ["array of search terms"],
    "app_name": "string - specific app name (WhatsApp, Instagram, Chrome, etc.)",
    "artifact_category": "string - messages, calls, browsing_history, media, etc."
  },
  "entities": [
    {"type": "phone|crypto|email|location|app", "value": "extracted value"}
  ],
  "keywords": ["relevant search terms - extract intelligently"],
  "confidence": 0.0-1.0
}

**CRITICAL: For app-specific queries:**
1. Set intent to "app_specific"
2. MUST include "aleapp_artifacts" in target_tables
3. Add app_name to filters (e.g., "WhatsApp", "Instagram")
4. Set search_type to "hybrid" for best results
5. Extract relevant keywords (e.g., "messages" → artifact_category: "messages")

**Examples:**
Query: "show me whatsapp messages"
→ intent: "app_specific", target_tables: ["aleapp_artifacts"], filters: {app_name: "WhatsApp", artifact_category: "messages"}

Query: "find instagram DMs from last week"
→ intent: "app_specific", target_tables: ["aleapp_artifacts"], filters: {app_name: "Instagram", artifact_category: "messages", time_range: {start: "last week"}}

Query: "all social media activity"
→ intent: "app_specific", target_tables: ["aleapp_artifacts"], keywords: ["social", "media"], artifact_category: "any"

Be conversational, intelligent, and USE ALEAPP ARTIFACTS for app queries!"""

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
        system_prompt = """You are a conversational forensic analyst assistant. Your task:
1. Answer the user's query in NATURAL, CONVERSATIONAL language
2. Provide SPECIFIC details from the data (dates, names, counts, etc.)
3. Highlight patterns, suspicious activities, or important findings
4. Be helpful, clear, and thorough - like a colleague explaining findings

CRITICAL: Be conversational and specific!
- Instead of: "Found 5 results"
- Say: "I found 5 WhatsApp conversations from this device, spanning from Jan 15 to Feb 20, 2024."

- Instead of: "Messages contain keywords"
- Say: "The conversations mention Bitcoin 12 times, with specific wallet addresses discussed on Feb 3rd."

Format your response naturally:
- Start with a direct answer to their question
- Provide key findings with specific details
- Suggest related queries or next steps if useful

CRITICAL: If results are from ALEAPP artifacts:
- Explain what you found (e.g., "WhatsApp messages", "Instagram DMs")
- Mention the artifact type and how many items
- Show sample data if relevant"""

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

                elif result_type == "aleapp_artifact":
                    # ALEAPP artifacts - show filename, category, and row count
                    result_summary += f"{i}. [ALEAPP] {result.get('filename', 'N/A')} | Category: {result.get('category', 'N/A')} | {result.get('row_count', 0)} rows\n"
                    if result.get('sample_data'):
                        result_summary += f"   Sample: {str(result['sample_data'][0])[:100]}...\n"

                elif result_type == "device_info":
                    # Device info - show what type of info and key details
                    info_type = result.get('info_type', 'unknown')
                    if info_type == 'extraction_metadata':
                        result_summary += f"{i}. [DEVICE INFO] Extraction: {result.get('file_name', 'N/A')} | Status: {result.get('status', 'N/A')}\n"
                        if result.get('extraction_metadata'):
                            result_summary += f"   Metadata: {str(result['extraction_metadata'])[:100]}...\n"
                    elif info_type == 'system_file':
                        result_summary += f"{i}. [SYSTEM FILE] {result.get('original_path', 'N/A')}\n"
                    else:
                        result_summary += f"{i}. [DEVICE INFO] {result.get('filename', 'N/A')} | {result.get('category', 'N/A')}\n"

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

    def _generate_no_results_response(self, original_query: str, query_results: Dict[str, Any]) -> str:
        """
        Generate a helpful response when no results are found.
        Analyzes what data IS available and suggests alternatives.
        """
        # Check what data is actually available
        available_data = []
        
        # This would need to be passed from the query executor
        # For now, provide a generic helpful response
        query_lower = original_query.lower()
        
        if 'whatsapp' in query_lower or 'wa' in query_lower:
            return """I searched for WhatsApp messages but didn't find any WhatsApp data in this device extraction. 

This could mean:
• WhatsApp wasn't installed on this device
• WhatsApp data wasn't included in the UFDR extraction
• WhatsApp data is encrypted and not accessible

**What I can help you find instead:**
• SMS messages (if any exist)
• Call logs and contacts
• Other app data that was extracted
• Media files and documents

Try asking: "What communication data is available?" or "Show me all messages and calls" to see what data exists."""
        
        elif 'message' in query_lower or 'chat' in query_lower:
            return """I searched for messages but didn't find any message data in this device extraction.

This could mean:
• No messaging apps were installed
• Message data wasn't included in the UFDR
• Messages are encrypted or protected

**What I can help you find instead:**
• Call logs and contacts
• Media files and documents  
• App installation data
• System files and logs

Try asking: "What data is available?" or "Show me all contacts and calls" to explore what exists."""
        
        elif 'android' in query_lower or 'version' in query_lower or 'device' in query_lower or 'system' in query_lower:
            return """I searched for device information but didn't find specific Android version or system details in this extraction.

This could mean:
• System information wasn't included in the UFDR
• Device details are in encrypted system files
• The extraction focused on app data rather than system info

**What I can help you find instead:**
• Installed apps and their versions
• Media files and documents
• ALEAPP analysis results
• Extraction metadata and file information

Try asking: "What apps were installed?" or "Show me all extracted data" to see what information is available."""
        
        else:
            return f"""I searched for '{original_query}' but didn't find any matching data in this device extraction.

**This could mean:**
• The specific data you're looking for isn't in this UFDR file
• The data might be encrypted or protected
• The extraction didn't capture that type of data

**What I can help you find instead:**
• Available communication data (calls, contacts, messages)
• Media files and documents
• App data and system information
• Any other data that was successfully extracted

Try asking: "What data is available?" or "Show me all extracted data" to see what exists in this device."""
