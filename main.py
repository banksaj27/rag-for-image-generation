from langchain.tools import tool
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage
from langchain_community.tools.tavily_search import TavilySearchResults

import os
import json
import requests
from typing import Any

from langchain.tools import tool
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage, BaseMessage
from langchain_community.tools.tavily_search import TavilySearchResults
from langgraph.graph import add_messages
from langgraph.func import entrypoint, task
from langgraph.graph import add_messages
from langchain.messages import (
    SystemMessage,
    HumanMessage,
    ToolCall,
)
from langchain_core.messages import BaseMessage
from langgraph.func import entrypoint, task
import base64
from langchain.tools import tool
from urllib.parse import urlencode
from langchain.tools import tool
import os
import json
from typing import List
from urllib.parse import quote_plus

from browserbase import Browserbase
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from langchain.tools import tool
import os
import json
from typing import List
from urllib.parse import quote_plus

from browserbase import Browserbase
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from langchain.tools import tool

import mimetypes


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


TAVILY_API_KEY = _require_env("TAVILY_API_KEY")
BROWSERBASE_API_KEY = _require_env("BROWSERBASE_API_KEY")
GOOGLE_API_KEY = _require_env("GOOGLE_API_KEY")
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", GOOGLE_API_KEY).strip() or GOOGLE_API_KEY

search = TavilySearchResults(tavily_api_key=TAVILY_API_KEY)

model = init_chat_model(
    "gemini-3.1-flash-image-preview",
    model_provider="google_genai",
    google_api_key=GOOGLE_API_KEY,
    temperature=0
)

def _image_url_to_data_url(image_url: str, timeout: int = 20) -> tuple[str, str]:
    """
    Download an image URL and convert it to a data URL for Gemini.
    Returns: (data_url, mime_type)
    """
    headers = {
        "User-Agent": "Mozilla/5.0"
    }
    resp = requests.get(image_url, headers=headers, timeout=timeout)
    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "").split(";")[0].strip()
    if not content_type.startswith("image/"):
        guessed, _ = mimetypes.guess_type(image_url)
        content_type = guessed or "image/jpeg"

    b64 = base64.b64encode(resp.content).decode("utf-8")
    data_url = f"data:{content_type};base64,{b64}"
    return data_url, content_type

def validate_image_url_against_query(image_url: str, query: str) -> dict:
    """
    Uses Gemini vision to determine whether an image URL is relevant to the query.
    """
    try:
        data_url, mime_type = _image_url_to_data_url(image_url)

        prompt = f"""
You are validating whether an image is relevant to a user's request.

User query:
{query}

Your job:
1. Identify what is shown in the image as specifically as possible.
2. Decide whether it is relevant to the query.
3. If this is a place/landmark/building query, only mark relevant=true if the image clearly shows that place or a very likely view of it.
4. If uncertain, return relevant=false.

Return ONLY strict JSON with this schema:
{{
  "relevant": true or false,
  "identified_subject": "short description",
  "confidence": 0.0,
  "reason": "short explanation"
}}
"""

        response = model.invoke([
            HumanMessage(content=[
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ])
        ])

        raw = response.content.strip() if isinstance(response.content, str) else str(response.content)

        # Try to parse JSON robustly
        try:
            parsed = json.loads(raw)
        except Exception:
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end != -1 and end > start:
                parsed = json.loads(raw[start:end+1])
            else:
                parsed = {
                    "relevant": False,
                    "identified_subject": "",
                    "confidence": 0.0,
                    "reason": f"Could not parse model output: {raw[:300]}"
                }

        return {
            "success": True,
            "image_url": image_url,
            "query": query,
            "relevant": bool(parsed.get("relevant", False)),
            "identified_subject": parsed.get("identified_subject", ""),
            "confidence": float(parsed.get("confidence", 0.0) or 0.0),
            "reason": parsed.get("reason", ""),
        }

    except Exception as e:
        return {
            "success": False,
            "image_url": image_url,
            "query": query,
            "relevant": False,
            "identified_subject": "",
            "confidence": 0.0,
            "reason": f"{type(e).__name__}: {str(e)}",
        }

def browserbase_google_image_urls_validated(query: str, n: int = 5, max_candidates: int = 30) -> str:
    """
    Search Google Images, then validate each candidate with Gemini until we collect n relevant images.
    """
    if n <= 0:
        return json.dumps(
            {"success": False, "error": "n must be greater than 0"},
            ensure_ascii=False,
        )

    # Over-fetch candidates so validation has enough to work with
    raw_result = browserbase_google_image_urls(query=query, n=max_candidates)

    try:
        parsed = json.loads(raw_result)
    except Exception:
        return json.dumps(
            {
                "success": False,
                "query": query,
                "error": "Could not parse candidate image search output",
                "raw_result": raw_result[:1000],
            },
            ensure_ascii=False,
        )

    if not parsed.get("success"):
        return json.dumps(parsed, ensure_ascii=False)

    candidates = parsed.get("image_urls", [])
    approved = []
    rejected = []

    for url in candidates:
        if len(approved) >= n:
            break

        verdict = validate_image_url_against_query(image_url=url, query=query)

        if verdict.get("relevant"):
            approved.append({
                "url": url,
                "identified_subject": verdict.get("identified_subject", ""),
                "confidence": verdict.get("confidence", 0.0),
                "reason": verdict.get("reason", ""),
            })
        else:
            rejected.append({
                "url": url,
                "identified_subject": verdict.get("identified_subject", ""),
                "confidence": verdict.get("confidence", 0.0),
                "reason": verdict.get("reason", ""),
            })

    return json.dumps(
        {
            "success": len(approved) > 0,
            "query": query,
            "requested_n": n,
            "returned_n": len(approved),
            "validated_image_urls": [x["url"] for x in approved],
            "approved": approved,
            "rejected_count": len(rejected),
            "session_id": parsed.get("session_id"),
            "debug_url": parsed.get("debug_url"),
        },
        ensure_ascii=False,
    )

def extract_official_location_text(user_input: str) -> str:
    search_query = f"What is the official name and address of {user_input}?"
    results = search.invoke({"query": search_query})
    search_results = json.dumps(results, ensure_ascii=False, indent=2)

    prompt = f"""
You are extracting a real-world place for geocoding.
User input:
{user_input}
Web search results:
{search_results}
Return ONLY one concise geocoding-ready string that is most likely to work in OpenStreetMap Nominatim.
Rules:
- Avoid building numbers, suite numbers, postal codes, and extra address detail unless absolutely necessary
- No explanation
- No markdown
"""
    response = model.invoke(prompt)
    return response.content.strip()

def get_coordinates(location_query: str) -> dict[str, Any]:
    """
    Geocode using OpenStreetMap Nominatim.
    """
    url = "https://nominatim.openstreetmap.org/search"
    headers = {
        "User-Agent": "langchain-coordinate-agent/1.0"
    }
    params = {
        "q": location_query,
        "format": "jsonv2",
        "limit": 1,
        "addressdetails": 1,
    }

    resp = requests.get(url, params=params, headers=headers, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    if not data:
        return {
            "success": False,
            "query": location_query,
            "error": "No coordinates found",
        }

    top = data[0]
    return {
        "success": True,
        "query": location_query,
        "latitude": float(top["lat"]),
        "longitude": float(top["lon"]),
        "display_name": top.get("display_name"),
    }


def coordinates_extractor(place: str) -> str:
    """
    Full pipeline:
    user text -> Tavily search -> Gemini cleanup -> geocoding
    """
    refined_location = extract_official_location_text(place)
    coords = get_coordinates(refined_location)
    return json.dumps(
        {
            "input": place,
            "resolved_location": refined_location,
            **coords,
        },
        ensure_ascii=False,
    )

def _dedupe_keep_order(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def browserbase_google_image_urls(query: str, n: int = 5) -> str:
    if n <= 0:
        return json.dumps(
            {"success": False, "error": "n must be greater than 0"},
            ensure_ascii=False,
        )

    bb = Browserbase(api_key=BROWSERBASE_API_KEY)
    session = bb.sessions.create()

    debug_url = None

    try:
        try:
            debug_links = bb.sessions.debug(session.id)
            debug_url = getattr(debug_links, "debugger_fullscreen_url", None) or getattr(
                debug_links, "debuggerFullscreenUrl", None
            )
        except Exception:
            debug_url = None

        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(session.connect_url, timeout=60000)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            context.set_default_timeout(60000)

            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(60000)

            search_url = f"https://www.google.com/search?tbm=isch&q={quote_plus(query)}"

            print(f"[DEBUG] Navigating to: {search_url}")
            page.goto(search_url, wait_until="domcontentloaded", timeout=60000)

            # Try to dismiss consent dialogs
            consent_selectors = [
                'button:has-text("Accept all")',
                'button:has-text("I agree")',
                'button:has-text("Accept")',
                'button:has-text("Reject all")',
                '[aria-label="Accept all"]',
                '[aria-label="I agree"]',
            ]
            for sel in consent_selectors:
                try:
                    if page.locator(sel).first.is_visible(timeout=2000):
                        page.locator(sel).first.click(timeout=3000)
                        print(f"[DEBUG] Clicked consent button: {sel}")
                        page.wait_for_timeout(2000)
                        break
                except Exception:
                    pass

            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass

            # Scroll to trigger lazy loading
            for i in range(5):
                page.mouse.wheel(0, 3000)
                page.wait_for_timeout(1500)
                print(f"[DEBUG] Scroll pass {i + 1}")

            # Extract candidate URLs from all images in DOM
            candidates = page.evaluate(
                """
                () => {
                    const urls = [];
                    for (const img of Array.from(document.images)) {
                        const src = img.currentSrc || img.src || "";
                        if (!src) continue;
                        if (src.startsWith("http://") || src.startsWith("https://")) {
                            urls.push(src);
                        }
                    }
                    return urls;
                }
                """
            )

            print(f"[DEBUG] Raw candidate count: {len(candidates)}")

            filtered = [
                u for u in candidates
                if not u.endswith(".svg")
            ]

            image_urls = _dedupe_keep_order(filtered)[:n]

            if not image_urls:
                # Return page HTML snippet for debugging
                html_preview = page.content()[:2000]
                return json.dumps(
                    {
                        "success": False,
                        "query": query,
                        "session_id": session.id,
                        "debug_url": debug_url,
                        "error": "No usable image URLs found",
                        "candidate_count": len(candidates),
                        "html_preview": html_preview,
                    },
                    ensure_ascii=False,
                )

            return json.dumps(
                {
                    "success": True,
                    "query": query,
                    "image_count": len(image_urls),
                    "image_urls": image_urls,
                    "session_id": session.id,
                    "debug_url": debug_url,
                },
                ensure_ascii=False,
            )

    except Exception as e:
        return json.dumps(
            {
                "success": False,
                "query": query,
                "session_id": session.id if "session" in locals() else None,
                "debug_url": debug_url,
                "error": f"{type(e).__name__}: {str(e)}",
            },
            ensure_ascii=False,
        )


@tool
def browserbase_google_image_urls_tool(query: str, n: int = 5) -> str:
    """Return the top n Google Images URLs for any query using Browserbase."""
    return browserbase_google_image_urls(query, n)

@tool
def browserbase_google_image_urls_validated_tool(query: str, n: int = 5) -> str:
    """Return the top n Google Image URLs relevant to the query, validated by Gemini vision."""
    return browserbase_google_image_urls_validated(query=query, n=n)

@tool
def get_coordinates_tool(place: str) -> str:
    """Get coordinates for a place name, landmark, or venue."""
    return coordinates_extractor(place)


@tool
def street_view_image_tool(coordinates: str) -> dict:
    """
    Return four Google Street View Static API image URLs, with the camera
    shifted slightly away from the target coordinate in each direction.
    """

    parts = [p.strip() for p in coordinates.split(",")]
    if len(parts) != 2:
        raise ValueError("coordinates must be 'lat,lng'")

    try:
        lat = float(parts[0])
        lng = float(parts[1])
    except ValueError as e:
        raise ValueError("coordinates must contain valid numbers") from e

    base_url = "https://maps.googleapis.com/maps/api/streetview"

    # Roughly ~20 meters-ish
    shift = 0.001

    views = {
        "north_view": {
            "lat": lat - shift,   # move south
            "lng": lng,
            "heading": 0,         # look north
        },
        "east_view": {
            "lat": lat,
            "lng": lng - shift,   # move west
            "heading": 90,        # look east
        },
        "south_view": {
            "lat": lat + shift,   # move north
            "lng": lng,
            "heading": 180,       # look south
        },
        "west_view": {
            "lat": lat,
            "lng": lng + shift,   # move east
            "heading": 270,       # look west
        },
    }

    urls = {}

    for direction, data in views.items():
        params = {
            "size": "640x640",
            "location": f"{data['lat']},{data['lng']}",
            "heading": data["heading"],
            "fov": 90,
            "pitch": 0,
            "return_error_code": "true",
            "key": GOOGLE_MAPS_API_KEY,
        }
        urls[direction] = f"{base_url}?{urlencode(params)}"

    return urls

@tool
def validate_image_url_tool(image_url: str, query: str) -> str:
    """Validate whether an image URL is relevant to a user query using Gemini vision."""
    return json.dumps(
        validate_image_url_against_query(image_url=image_url, query=query),
        ensure_ascii=False,
    )

tools = [get_coordinates_tool, street_view_image_tool, browserbase_google_image_urls_tool, validate_image_url_tool]
tools_by_name = {tool.name: tool for tool in tools}
model_with_tools = model.bind_tools(tools)

@task
def call_llm(messages: list[BaseMessage]):
    """LLM decides whether to call the coordinates tool."""
    return model_with_tools.invoke(
        [
            SystemMessage(
                content=(
                    "You are a helpful assistant. "
                    "If the user asks for coordinates of a place, use get_coordinates_tool. "
                    "If the user asks for street view images and coordinates are provided, use street_view_image_tool. "
                    "If the user asks for photos, images, or image URLs of anything at all "
                    "(real, fictional, place, object, concept, celestial body, etc.), "
                    "use browserbase_google_image_urls_tool. "
                    "Do not apologize for not having images until after trying the tool. "
                    "If no tool is needed, answer normally."
                )
            )
        ] + messages
    )

@task
def call_tool(tool_call: dict):
    """Execute the requested tool call."""
    tool = tools_by_name[tool_call["name"]]
    return tool.invoke(tool_call)

# Step 4: Define agent

@entrypoint()
def agent(messages: list[BaseMessage]):
    model_response = call_llm(messages).result()

    while True:
        if not model_response.tool_calls:
            break

        # Execute tools
        tool_result_futures = [
            call_tool(tool_call) for tool_call in model_response.tool_calls
        ]
        tool_results = [fut.result() for fut in tool_result_futures]
        messages = add_messages(messages, [model_response, *tool_results])
        model_response = call_llm(messages).result()

    messages = add_messages(messages, model_response)
    return messages

# Invoke
human_input = input("What do you want to ask: ")

# messages = [HumanMessage(content=human_input)]

# print("\n--- Agent Stream ---\n")

# for step in agent.stream(messages):
#     print(step)

messages = [HumanMessage(content=human_input)]

final_state = agent.invoke(messages)
last_msg = final_state[-1]

def extract_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if text:
                    parts.append(text)
        return "\n".join(parts).strip()
    return str(content)

final_response = extract_text(last_msg.content)

print("\n--- Assistant Response ---")
print(final_response)
