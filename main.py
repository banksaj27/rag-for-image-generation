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
            "key": "AIzaSyA9b4ZC41Z5sDGVbsN2-B5xaJ5cMMflR_Y",
        }
        urls[direction] = f"{base_url}?{urlencode(params)}"

    return urls



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
                    "If the user asks for an image of a place, and has already given coordinates, use the street_view_image_tool tool. "
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
final_state = agent.invoke(messages)

# The last message in the list is the assistant's final response
final_response = final_state[-1].content

print("\n--- Assistant Response ---")
print(final_response)




