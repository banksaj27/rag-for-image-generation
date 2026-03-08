import os
import json
import base64
import mimetypes
import requests
from typing import Any, List
from urllib.parse import urlencode, quote_plus

from browserbase import Browserbase
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from langchain.tools import tool
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage, BaseMessage
from langchain_community.tools.tavily_search import TavilySearchResults
from langgraph.graph import add_messages
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)


search = TavilySearchResults(tavily_api_key='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')
BROWSERBASE_API_KEY = "bb_live_4qYZKqZQMkL6nj2gPtF7alcA6Ak"

model = init_chat_model(
    "gemini-2.5-flash",
    model_provider="google_genai",
    google_api_key="AIzaSyA9b4ZC41Z5sDGVbsN2-B5xaJ5cMMflR_Y",
    temperature=0
)


def _safe_json_loads(text: str, fallback: dict | None = None) -> dict:
    if not isinstance(text, str):
        return fallback or {}
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else (fallback or {})
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(text[start:end+1])
            return parsed if isinstance(parsed, dict) else (fallback or {})
        except Exception:
            pass
    return fallback or {}

def _dedupe_keep_order(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out

def _dedupe_list(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        key = item.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(item.strip())
    return out

def _clean_str(x: Any) -> str:
    if x is None:
        return ""
    return str(x).strip()

def _ensure_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return []
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(v).strip() for v in parsed if str(v).strip()]
        except Exception:
            pass
        parts = []
        for chunk in value.replace("\n", ",").split(","):
            chunk = chunk.strip()
            if chunk:
                parts.append(chunk)
        return parts
    return [str(value).strip()]

def _join_nonempty(items: list[str], sep: str = ", ") -> str:
    return sep.join([x.strip() for x in items if x and x.strip()])


def _image_url_to_data_url(image_url: str, timeout: int = 20) -> tuple[str, str]:
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(image_url, headers=headers, timeout=timeout)
    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "").split(";")[0].strip()
    if not content_type.startswith("image/"):
        guessed, _ = mimetypes.guess_type(image_url)
        content_type = guessed or "image/jpeg"

    b64 = base64.b64encode(resp.content).decode("utf-8")
    return f"data:{content_type};base64,{b64}", content_type

def validate_image_url_against_query(image_url: str, query: str) -> dict:
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
        parsed = _safe_json_loads(raw, fallback={
            "relevant": False,
            "identified_subject": "",
            "confidence": 0.0,
            "reason": f"Could not parse model output: {raw[:300]}"
        })

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

def browserbase_google_image_urls(query: str, n: int = 5) -> str:
    if n <= 0:
        return json.dumps({"success": False, "error": "n must be greater than 0"}, ensure_ascii=False)

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
            page.goto(search_url, wait_until="domcontentloaded", timeout=60000)

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
                        page.wait_for_timeout(2000)
                        break
                except Exception:
                    pass

            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass

            for _ in range(20):
                page.mouse.wheel(0, 3000)
                page.wait_for_timeout(1500)

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

            filtered = [u for u in candidates if not u.endswith(".svg")]
            image_urls = _dedupe_keep_order(filtered)[:n]

            if not image_urls:
                return json.dumps(
                    {
                        "success": False,
                        "query": query,
                        "session_id": session.id,
                        "debug_url": debug_url,
                        "error": "No usable image URLs found",
                        "candidate_count": len(candidates),
                        "html_preview": page.content()[:2000],
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

def browserbase_google_image_urls_validated(query: str, n: int = 5, max_candidates: int = 30) -> str:
    if n <= 0:
        return json.dumps({"success": False, "error": "n must be greater than 0"}, ensure_ascii=False)

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
        entry = {
            "url": url,
            "identified_subject": verdict.get("identified_subject", ""),
            "confidence": verdict.get("confidence", 0.0),
            "reason": verdict.get("reason", ""),
        }
        if verdict.get("relevant"):
            approved.append(entry)
        else:
            rejected.append(entry)

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
    url = "https://nominatim.openstreetmap.org/search"
    headers = {"User-Agent": "langchain-coordinate-agent/1.0"}
    params = {"q": location_query, "format": "jsonv2", "limit": 1, "addressdetails": 1}

    resp = requests.get(url, params=params, headers=headers, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    if not data:
        return {"success": False, "query": location_query, "error": "No coordinates found"}

    top = data[0]
    return {
        "success": True,
        "query": location_query,
        "latitude": float(top["lat"]),
        "longitude": float(top["lon"]),
        "display_name": top.get("display_name"),
    }

def coordinates_extractor(place: str) -> str:
    refined_location = extract_official_location_text(place)
    coords = get_coordinates(refined_location)
    return json.dumps({"input": place, "resolved_location": refined_location, **coords}, ensure_ascii=False)

def optimize_prompt_for_image_retrieval(user_prompt: str) -> dict:
    prompt = f"""
You convert user prompts into highly specific image-search queries.

User prompt:
{user_prompt}

Return ONLY strict JSON with this schema:
{{
  "optimized_image_query": "string",
  "place_candidate": "string",
  "search_intent": "landmark|place|building|venue|object|person|fictional|general",
  "must_include_terms": ["term1", "term2"],
  "avoid_terms": ["term1", "term2"],
  "reason": "short explanation"
}}

Rules:
- Make the query highly specific for finding the correct images online.
- Prefer official names, location qualifiers, architectural/style qualifiers, viewpoint qualifiers, and disambiguators.
- If the prompt seems to refer to a real-world place, landmark, building, venue, or address, set place_candidate.
- If there is no real place, place_candidate should be "".
- Keep optimized_image_query concise but highly targeted.
- No markdown.
"""

    response = model.invoke(prompt)
    raw = response.content if isinstance(response.content, str) else str(response.content)

    parsed = _safe_json_loads(raw, fallback={
        "optimized_image_query": user_prompt,
        "place_candidate": "",
        "search_intent": "general",
        "must_include_terms": [],
        "avoid_terms": [],
        "reason": "fallback parse",
    })

    return {
        "optimized_image_query": parsed.get("optimized_image_query", user_prompt),
        "place_candidate": parsed.get("place_candidate", ""),
        "search_intent": parsed.get("search_intent", "general"),
        "must_include_terms": parsed.get("must_include_terms", []),
        "avoid_terms": parsed.get("avoid_terms", []),
        "reason": parsed.get("reason", ""),
    }

def build_google_maps_urls(lat: float, lng: float, place_label: str = "") -> dict:
    query = quote_plus(place_label) if place_label else f"{lat},{lng}"
    return {
        "google_maps_place_url": f"https://www.google.com/maps/search/?api=1&query={query}",
        "google_maps_pin_url": f"https://www.google.com/maps?q={lat},{lng}",
        "google_maps_satellite_url": f"https://www.google.com/maps?q={lat},{lng}&t=k",
        "google_maps_street_view_url": f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat},{lng}",
    }

def retrieve_images_and_maps_from_prompt(user_prompt: str, n: int = 5, max_candidates: int = 20) -> str:
    optimized = optimize_prompt_for_image_retrieval(user_prompt)
    optimized_query = optimized["optimized_image_query"]
    place_candidate = optimized["place_candidate"]

    image_result_raw = browserbase_google_image_urls_validated(
        query=optimized_query, n=n, max_candidates=max_candidates
    )

    try:
        image_result = json.loads(image_result_raw)
    except Exception:
        image_result = {
            "success": False,
            "validated_image_urls": [],
            "error": "Could not parse image search output",
            "raw": image_result_raw[:1000],
        }

    maps_result = {
        "success": False,
        "place_candidate": place_candidate,
        "resolved_location": "",
        "coordinates": None,
        "maps_urls": {},
    }

    if place_candidate:
        try:
            coords_data = json.loads(coordinates_extractor(place_candidate))
            if coords_data.get("success"):
                lat = coords_data["latitude"]
                lng = coords_data["longitude"]
                resolved_location = coords_data.get("resolved_location") or coords_data.get("display_name") or place_candidate
                maps_result = {
                    "success": True,
                    "place_candidate": place_candidate,
                    "resolved_location": resolved_location,
                    "coordinates": {"latitude": lat, "longitude": lng},
                    "maps_urls": build_google_maps_urls(lat=lat, lng=lng, place_label=resolved_location),
                    "street_view_static_urls": street_view_image_tool.invoke({"coordinates": f"{lat},{lng}"}),
                }
        except Exception as e:
            maps_result = {
                "success": False,
                "place_candidate": place_candidate,
                "resolved_location": "",
                "coordinates": None,
                "maps_urls": {},
                "error": f"{type(e).__name__}: {str(e)}",
            }

    return json.dumps(
        {
            "success": bool(image_result.get("validated_image_urls")),
            "input_prompt": user_prompt,
            "optimized_query": optimized_query,
            "optimization": optimized,
            "image_urls": image_result.get("validated_image_urls", []),
            "approved_images": image_result.get("approved", []),
            "maps": maps_result,
        },
        ensure_ascii=False,
        indent=2,
    )


def _normalize_scene_spec(scene: dict) -> dict:
    spec = {
        "subject": _clean_str(scene.get("subject") or scene.get("landmark") or scene.get("main_subject")),
        "location": _clean_str(scene.get("location") or scene.get("place") or scene.get("real_location")),
        "viewpoint": _clean_str(scene.get("viewpoint") or scene.get("camera_position") or scene.get("viewer_position")),
        "orientation": _clean_str(scene.get("orientation") or scene.get("camera_facing") or scene.get("direction")),
        "composition": _clean_str(scene.get("composition") or scene.get("framing")),
        "foreground": _ensure_list(scene.get("foreground")),
        "midground": _ensure_list(scene.get("midground")),
        "background": _ensure_list(scene.get("background")),
        "architecture": _ensure_list(scene.get("architecture")),
        "materials": _ensure_list(scene.get("materials")),
        "infrastructure": _ensure_list(scene.get("infrastructure")),
        "vegetation": _ensure_list(scene.get("vegetation") or scene.get("landscape")),
        "lighting": _clean_str(scene.get("lighting")),
        "weather": _clean_str(scene.get("weather")),
        "time_of_day": _clean_str(scene.get("time_of_day")),
        "mood": _clean_str(scene.get("mood")),
        "style_goal": _clean_str(scene.get("style_goal") or "photorealistic unedited documentary-style photograph"),
        "camera_height": _clean_str(scene.get("camera_height") or "eye level"),
        "lens": _clean_str(scene.get("lens") or "35mm"),
        "aperture": _clean_str(scene.get("aperture") or "f/5.6"),
        "depth_of_field": _clean_str(scene.get("depth_of_field") or "deep depth of field"),
        "constraints": _ensure_list(scene.get("constraints")),
        "exclusions": _ensure_list(scene.get("exclusions")),
        "realism_cues": _ensure_list(scene.get("realism_cues")),
    }

    if not spec["realism_cues"]:
        spec["realism_cues"] = [
            "natural color balance",
            "realistic contrast",
            "subtle sensor noise",
            "sharp architectural detail",
            "realistic textures",
            "believable spatial layout",
            "accurate proportions",
            "natural lighting behavior",
            "real-world material surfaces",
        ]

    default_exclusions = [
        "no stylization", "no fantasy elements", "no futuristic elements",
        "no exaggerated HDR", "no cinematic glow", "no painterly rendering",
        "no CGI look", "no fisheye effect", "no tilt-shift",
        "no invented landmarks", "no hallucinated architecture", "no extra towers",
        "no fake skyline", "no mountains unless actually present", "no text", "no watermark",
    ]
    spec["exclusions"] = _dedupe_list(spec["exclusions"] + default_exclusions)

    return spec

def _derive_scene_spec_from_text(user_prompt: str) -> dict:
    prompt = f"""
You convert a user's photo-generation request into a strict JSON scene specification for a photorealistic image model.

User request:
{user_prompt}

Return ONLY strict JSON with this schema:
{{
  "subject": "primary landmark / place / object",
  "location": "real-world place if known, otherwise empty string",
  "viewpoint": "where the viewer/camera is standing",
  "orientation": "what direction the camera is facing",
  "composition": "framing and geometric composition",
  "foreground": ["list"],
  "midground": ["list"],
  "background": ["list"],
  "architecture": ["list"],
  "materials": ["list"],
  "infrastructure": ["list"],
  "vegetation": ["list"],
  "lighting": "string",
  "weather": "string",
  "time_of_day": "string",
  "mood": "string",
  "style_goal": "photorealistic unedited documentary-style photograph",
  "camera_height": "eye level or other realistic camera height",
  "lens": "35mm unless a different realistic lens is strongly implied",
  "aperture": "f/5.6 unless otherwise needed",
  "depth_of_field": "deep depth of field unless a different realistic choice is needed",
  "constraints": ["spatial constraints that reduce hallucinations"],
  "exclusions": ["things the image must avoid"],
  "realism_cues": ["specific cues that increase realism"]
}}

Rules:
- Optimize for maximum realism and minimum hallucination.
- If the request refers to a real place, anchor the output to real spatial facts and ordinary infrastructure.
- Prefer eye-level human perspective unless the request clearly implies a different viewpoint.
- Prefer concrete, visible facts over lore or narrative.
- Constraints should be spatial and compositional, not vague.
- Exclusions should target common image-model failure modes.
- No markdown.
"""

    response = model.invoke(prompt)
    raw = response.content if isinstance(response.content, str) else str(response.content)

    parsed = _safe_json_loads(raw, fallback={
        "subject": user_prompt,
        "location": "",
        "viewpoint": "eye-level human perspective",
        "orientation": "",
        "composition": "realistic centered composition",
        "foreground": [], "midground": [], "background": [],
        "architecture": [], "materials": [], "infrastructure": [], "vegetation": [],
        "lighting": "natural daylight",
        "weather": "", "time_of_day": "", "mood": "",
        "style_goal": "photorealistic unedited documentary-style photograph",
        "camera_height": "eye level",
        "lens": "35mm",
        "aperture": "f/5.6",
        "depth_of_field": "deep depth of field",
        "constraints": [], "exclusions": [], "realism_cues": [],
    })
    return _normalize_scene_spec(parsed)

def _build_nanobanana_prompt_from_spec(spec: dict) -> dict:
    subject = spec["subject"]
    location = spec["location"]
    viewpoint = spec["viewpoint"]
    orientation = spec["orientation"]
    composition = spec["composition"]
    foreground = spec["foreground"]
    midground = spec["midground"]
    background = spec["background"]
    architecture = spec["architecture"]
    materials = spec["materials"]
    infrastructure = spec["infrastructure"]
    vegetation = spec["vegetation"]
    lighting = spec["lighting"]
    weather = spec["weather"]
    time_of_day = spec["time_of_day"]
    mood = spec["mood"]
    style_goal = spec["style_goal"]
    camera_height = spec["camera_height"]
    lens = spec["lens"]
    aperture = spec["aperture"]
    depth_of_field = spec["depth_of_field"]
    realism_cues = spec["realism_cues"]
    constraints = spec["constraints"]
    exclusions = spec["exclusions"]

    opening = style_goal
    if subject:
        opening += f" of {subject}"
    if location:
        opening += f" at {location}"
    opening = opening[0].upper() + opening[1:] + "."

    viewpoint_parts = []
    if viewpoint:
        viewpoint_parts.append(f"Viewed from {viewpoint}")
    if camera_height:
        viewpoint_parts.append(f"camera height {camera_height}")
    if orientation:
        viewpoint_parts.append(f"looking {orientation}")
    viewpoint_sentence = (", ".join(viewpoint_parts) + ".") if viewpoint_parts else ""

    composition_bits = []
    if composition:
        composition_bits.append(composition)
    if foreground:
        composition_bits.append(f"foreground includes {_join_nonempty(foreground)}")
    if midground:
        composition_bits.append(f"midground includes {_join_nonempty(midground)}")
    if background:
        composition_bits.append(f"background includes {_join_nonempty(background)}")
    composition_sentence = ("The composition is " + "; ".join(composition_bits) + ".") if composition_bits else ""

    grounding_bits = []
    if architecture:
        grounding_bits.append(f"architecture includes {_join_nonempty(architecture)}")
    if infrastructure:
        grounding_bits.append(f"infrastructure includes {_join_nonempty(infrastructure)}")
    if vegetation:
        grounding_bits.append(f"vegetation includes {_join_nonempty(vegetation)}")
    if materials:
        grounding_bits.append(f"materials include {_join_nonempty(materials)}")
    grounding_sentence = (
        "The environment should feel physically grounded and location-accurate, with "
        + "; ".join(grounding_bits) + "."
    ) if grounding_bits else ""

    atmosphere_bits = [x for x in [lighting, weather, time_of_day, mood] if x]
    atmosphere_sentence = (
        "Lighting and atmosphere should reflect " + ", ".join(atmosphere_bits) + "."
    ) if atmosphere_bits else ""

    camera_sentence = (
        f"Camera and photo behavior: full-frame DSLR look, {lens} lens, {aperture}, "
        f"{depth_of_field}, {_join_nonempty(realism_cues)}."
    )

    constraints_block = (
        "Important spatial constraints:\n" + "\n".join(f"- {item}" for item in constraints)
    ) if constraints else ""

    exclusions_block = (
        "Exclusions:\n" + "\n".join(f"- {item}" for item in exclusions)
    ) if exclusions else ""

    closing = (
        "The final image should feel like a real photograph taken at the actual location, "
        "with maximum realism, accurate landmark placement, believable scale, and minimal hallucination."
    )

    full_prompt = "\n\n".join(
        part for part in [
            opening, viewpoint_sentence, composition_sentence, grounding_sentence,
            atmosphere_sentence, camera_sentence, constraints_block, exclusions_block, closing,
        ]
        if part.strip()
    )

    compact_parts = [
        style_goal,
        f"of {subject}" if subject else "",
        f"at {location}" if location else "",
        viewpoint,
        f"looking {orientation}" if orientation else "",
        composition,
        f"foreground: {_join_nonempty(foreground)}" if foreground else "",
        f"midground: {_join_nonempty(midground)}" if midground else "",
        f"background: {_join_nonempty(background)}" if background else "",
        f"architecture: {_join_nonempty(architecture)}" if architecture else "",
        f"infrastructure: {_join_nonempty(infrastructure)}" if infrastructure else "",
        f"materials: {_join_nonempty(materials)}" if materials else "",
        f"vegetation: {_join_nonempty(vegetation)}" if vegetation else "",
        lighting, weather, time_of_day, mood,
        f"{lens}, {aperture}, {depth_of_field}",
        _join_nonempty(realism_cues),
    ]
    compact_prompt = ", ".join([x.strip() for x in compact_parts if x and x.strip()])

    negative_prompt_items = [
        item.replace("no ", "").strip() if item.lower().startswith("no ") else item.strip()
        for item in exclusions
        if item and item.strip()
    ]
    negative_prompt = ", ".join(_dedupe_list(negative_prompt_items))

    return {"prompt": full_prompt, "compact_prompt": compact_prompt, "negative_prompt": negative_prompt, "data_layer": spec}

def _llm_polish_nanobanana_prompt(prompt_package: dict) -> dict:
    prompt = f"""
You are optimizing a prompt package for NanoBanana 2 image generation.

Goal:
- maximize photorealism
- minimize hallucinations
- preserve real-world spatial facts
- preserve viewpoint and geometry
- preserve all important constraints
- make the prompt dense, visual, and easy for the model to follow

Input JSON:
{json.dumps(prompt_package, ensure_ascii=False, indent=2)}

Return ONLY strict JSON with this exact schema:
{{
  "prompt": "improved full prompt",
  "compact_prompt": "improved compact prompt",
  "negative_prompt": "comma-separated negative prompt",
  "why_this_is_strong": [
    "short bullet 1",
    "short bullet 2",
    "short bullet 3"
  ]
}}

Rules:
- Do not invent new facts.
- Do not remove important location anchors.
- Keep realism-first camera language.
- Keep the prompt suitable for a real-world location reconstruction.
- Make the full prompt read like a production-grade image brief.
- No markdown.
"""

    response = model.invoke(prompt)
    raw = response.content if isinstance(response.content, str) else str(response.content)

    polished = _safe_json_loads(raw, fallback={
        "prompt": prompt_package["prompt"],
        "compact_prompt": prompt_package["compact_prompt"],
        "negative_prompt": prompt_package["negative_prompt"],
        "why_this_is_strong": [
            "Anchors the model to concrete spatial facts.",
            "Uses realism-first camera and lighting language.",
            "Includes explicit anti-hallucination constraints.",
        ],
    })

    return {
        "prompt": polished.get("prompt", prompt_package["prompt"]),
        "compact_prompt": polished.get("compact_prompt", prompt_package["compact_prompt"]),
        "negative_prompt": polished.get("negative_prompt", prompt_package["negative_prompt"]),
        "why_this_is_strong": polished.get("why_this_is_strong", []),
    }


@tool
def build_nanobanana2_prompt_tool(scene_input: str, use_llm_polish: bool = True) -> str:
    """
    Build a NanoBanana 2-optimized realism-first prompt package.

    scene_input can be either:
    1. a plain English scene request
    2. a JSON object string containing a structured scene spec

    Returns JSON with:
    - prompt
    - compact_prompt
    - negative_prompt
    - data_layer
    - why_this_is_strong
    """
    parsed = _safe_json_loads(scene_input, fallback=None)
    spec = _normalize_scene_spec(parsed) if parsed else _derive_scene_spec_from_text(scene_input)
    base_package = _build_nanobanana_prompt_from_spec(spec)

    why_this_is_strong = [
        "Anchors the image to concrete subject, location, viewpoint, and composition facts.",
        "Uses realism-first camera and material language instead of vague style language.",
        "Adds spatial constraints and exclusions that reduce hallucinated architecture and layout errors.",
    ]

    if use_llm_polish:
        polished = _llm_polish_nanobanana_prompt(base_package)
        result = {
            "success": True,
            "prompt": polished["prompt"],
            "compact_prompt": polished["compact_prompt"],
            "negative_prompt": polished["negative_prompt"],
            "data_layer": base_package["data_layer"],
            "why_this_is_strong": polished.get("why_this_is_strong", why_this_is_strong),
        }
    else:
        result = {
            "success": True,
            "prompt": base_package["prompt"],
            "compact_prompt": base_package["compact_prompt"],
            "negative_prompt": base_package["negative_prompt"],
            "data_layer": base_package["data_layer"],
            "why_this_is_strong": why_this_is_strong,
        }

    return json.dumps(result, ensure_ascii=False, indent=2)

@tool
def browserbase_google_image_urls_tool(query: str, n: int = 5) -> str:
    """Return the top n Google Images URLs for any query using Browserbase."""
    return browserbase_google_image_urls(query, n)

@tool
def get_coordinates_tool(place: str) -> str:
    """Get coordinates for a place name, landmark, or venue."""
    return coordinates_extractor(place)

@tool
def optimized_image_and_maps_tool(prompt: str, n: int = 5) -> str:
    """
    Take a user prompt, optimize it for image retrieval, and return:
    - validated image URLs
    - Google Maps URLs
    - Street View static image URLs
    """
    return retrieve_images_and_maps_from_prompt(user_prompt=prompt, n=n)

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
    shift = 0.001

    views = {
        "north_view": {"lat": lat - shift, "lng": lng, "heading": 0},
        "east_view":  {"lat": lat, "lng": lng - shift, "heading": 90},
        "south_view": {"lat": lat + shift, "lng": lng, "heading": 180},
        "west_view":  {"lat": lat, "lng": lng + shift, "heading": 270},
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

@tool
def validate_image_url_tool(image_url: str, query: str) -> str:
    """Validate whether an image URL is relevant to a user query using Gemini vision."""
    return json.dumps(
        validate_image_url_against_query(image_url=image_url, query=query),
        ensure_ascii=False,
    )


tools = [
    get_coordinates_tool,
    street_view_image_tool,
    browserbase_google_image_urls_tool,
    validate_image_url_tool,
    optimized_image_and_maps_tool,
    build_nanobanana2_prompt_tool,
]
tools_by_name = {tool.name: tool for tool in tools}
model_with_tools = model.bind_tools(tools)


SYSTEM_PROMPT = (
    "You are a helpful assistant. "
    "If the user asks for coordinates of a place, use get_coordinates_tool. "
    "If the user asks for street view images and coordinates are provided, use street_view_image_tool. "
    "If the user asks for photos, images, image URLs, or visual references, please take their prompt and optimize it for image retrieval by using optimized_image_and_maps_tool first. "
    "If the user asks for a generation prompt for an image model, especially for a realistic real-world scene or location, use build_nanobanana2_prompt_tool. "
    "That tool returns a NanoBanana 2 optimized full prompt, compact prompt, negative prompt, and structured data layer. "
    "Do not apologize for not having images until after trying the tool. "
    "If no tool is needed, answer normally."
)

human_input = input("What do you want to ask: ")
messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=human_input)]

print("\n--- Assistant Response ---")
while True:
    gathered = None
    for chunk in model_with_tools.stream(messages):
        if chunk.content:
            print(chunk.content, end="", flush=True)
        gathered = chunk if gathered is None else gathered + chunk

    if not gathered.tool_calls:
        print()
        break

    tool_results = [tools_by_name[tc["name"]].invoke(tc) for tc in gathered.tool_calls]
    messages = add_messages(messages, [gathered, *tool_results])
