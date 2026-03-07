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

search = TavilySearchResults(tavily_api_key='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')

model = init_chat_model(
    "gemini-2.5-flash", 
    model_provider="google_genai",
    google_api_key="AIzaSyA9b4ZC41Z5sDGVbsN2-B5xaJ5cMMflR_Y",
    temperature=0
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



# Define tools
@tool
def get_coordinates_tool(place: str) -> str:
    """Get coordinates for a place name, landmark, or venue."""
    return coordinates_extractor(place)


@tool
def street_view_image_tool(coordinates: str, angle: float) -> str:
    """Return a Google Street View Static API image URL for coordinates and heading angle.

    Args:
        coordinates: Comma-separated latitude and longitude, e.g. "37.4275,-122.1697"
        angle: Camera heading in degrees, typically 0-360

    Returns:
        A URL string for the Street View static image.
    """
    # Basic validation
    parts = [p.strip() for p in coordinates.split(",")]
    if len(parts) != 2:
        raise ValueError("coordinates must be a string like '37.4275,-122.1697'")

    try:
        lat = float(parts[0])
        lng = float(parts[1])
    except ValueError as e:
        raise ValueError("coordinates must contain valid numeric latitude and longitude") from e

    if not (-90 <= lat <= 90):
        raise ValueError("latitude must be between -90 and 90")
    if not (-180 <= lng <= 180):
        raise ValueError("longitude must be between -180 and 180")

    # Normalize heading
    heading = angle % 360

    params = {
        "size": "640x640",
        "location": f"{lat},{lng}",
        "heading": heading,
        "fov": 90,
        "pitch": 0,
        "return_error_code": "true",
        "key": "AIzaSyA9b4ZC41Z5sDGVbsN2-B5xaJ5cMMflR_Y",
    }

    base_url = "https://maps.googleapis.com/maps/api/streetview"
    return f"{base_url}?{urlencode(params)}"



tools = [get_coordinates_tool, street_view_image_tool]
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
                    "If the user asks for a location, landmark, venue, or place coordinates, "
                    "use the get_coordinates_tool tool. "
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

messages = [HumanMessage(content=human_input)]
for chunk in agent.stream(messages, stream_mode="updates"):
    print(chunk)
    print("\n")