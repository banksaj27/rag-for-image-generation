import { NextRequest, NextResponse } from "next/server";
import { generateTextToImage } from "@/lib/gemini";

const MAX_RAG_CONTEXT_CHARS = 6000;

export async function POST(request: NextRequest) {
  let body: { prompt?: string; ragContext?: string };
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
    const ragContext = typeof body?.ragContext === "string" ? body.ragContext.trim() : "";

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

    let ragImageUrl: string | null = null;
    let ragError: string | null = null;
    if (ragContext) {
      const trimmedContext = ragContext.slice(0, MAX_RAG_CONTEXT_CHARS);
      try {
        ragImageUrl = await generateTextToImage(
          [
            "Generate an image based on the user prompt and retrieved context.",
            "Prioritize factual layout and landmark accuracy.",
            "",
            `User prompt:\n${prompt}`,
            "",
            `Retrieved context:\n${trimmedContext}`,
          ].join("\n")
        );
      } catch (ragErr) {
        ragError = ragErr instanceof Error ? ragErr.message : "RAG image generation failed";
        console.error("[api/render][rag]", ragErr);
      }
    }

    return NextResponse.json({
      nativeImageUrl,
      ragImageUrl,
      ragError,
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
