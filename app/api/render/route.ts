import { NextRequest, NextResponse } from "next/server";
import { generateTextToImage } from "@/lib/gemini";

export async function POST(request: NextRequest) {
  let body: { prompt?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { error: "Invalid JSON body" },
      { status: 400 }
    );
  }
  try {
    const prompt = typeof body?.prompt === "string" ? body.prompt.trim() : "";

    if (!prompt) {
      return NextResponse.json(
        { error: "prompt is required" },
        { status: 400 }
      );
    }

    const apiKey = process.env.GOOGLE_API_KEY;
    if (!apiKey || apiKey.trim() === "") {
      return NextResponse.json(
        { error: "GOOGLE_API_KEY is not configured" },
        { status: 401 }
      );
    }

    const nativeImageUrl = await generateTextToImage(prompt);

    return NextResponse.json({
      nativeImageUrl,
      ragImageUrl: null,
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";

    if (message.includes("GOOGLE_API_KEY") || message.toLowerCase().includes("api key")) {
      return NextResponse.json(
        { error: message },
        { status: 401 }
      );
    }

    console.error("[api/render]", err);
    return NextResponse.json(
      { error: message || "Image generation failed" },
      { status: 500 }
    );
  }
}
