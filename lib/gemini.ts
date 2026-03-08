import { GoogleGenAI, Modality } from "@google/genai";

const PROJECT_ID = "144906959675";
const LOCATION = "us-central1";

function getClient(): GoogleGenAI {
  return new GoogleGenAI({
    vertexai: true,
    project: PROJECT_ID,
    location: LOCATION,
    apiVersion: "v1beta",
  });
}

/**
 * Generates an image from a text prompt using Vertex AI Gemini.
 * Uses Application Default Credentials (ADC) - run `gcloud auth application-default login`.
 * Returns a base64 data URL (data:image/png;base64,...).
 */
export async function generateTextToImage(prompt: string): Promise<string> {
  const client = getClient();
  const candidateModels = ["gemini-3.1-flash-image-preview", "gemini-3.1-flash-image"];
  const promptAttempts = [
    prompt,
    [
      "Generate one image only.",
      "Do not return text in the response body.",
      "",
      prompt,
    ].join("\n"),
  ];

  let lastError: unknown = null;

  for (const model of candidateModels) {
    for (const attemptedPrompt of promptAttempts) {
      try {
        const response = await client.models.generateContent({
          model,
          contents: attemptedPrompt,
          config: {
            responseModalities: [Modality.TEXT, Modality.IMAGE],
          },
        });

        const dataUrl = extractImageDataUrl(response);
        if (dataUrl) {
          return dataUrl;
        }
      } catch (error) {
        lastError = error;
        const message = error instanceof Error ? error.message.toLowerCase() : "";
        if (
          message.includes("not found") ||
          message.includes("not supported") ||
          message.includes("404")
        ) {
          continue;
        }
        throw error;
      }
    }
  }

  if (lastError instanceof Error) {
    throw new Error(
      `No Gemini image generation model is available for this project/region. Last error: ${lastError.message}`
    );
  }
  throw new Error("No image data returned by any available Gemini model");
}

function extractImageDataUrl(response: unknown): string | null {
  const r = response as {
    candidates?: Array<{
      content?: {
        parts?: Array<{
          inlineData?: { data?: string; mimeType?: string };
          inline_data?: { data?: string; mime_type?: string };
          inlineDataBase64?: string;
          mimeType?: string;
        }>;
      };
    }>;
  };

  const candidates = r.candidates ?? [];
  for (const candidate of candidates) {
    const parts = candidate.content?.parts ?? [];
    for (const part of parts) {
      const inline = part.inlineData ?? part.inline_data;
      if (inline?.data) {
        const m = inline as Record<string, string | undefined>;
        const mimeType = m["mimeType"] ?? m["mime_type"] ?? "image/png";
        return `data:${mimeType};base64,${inline.data}`;
      }
      if (part.inlineDataBase64) {
        const mimeType = part.mimeType ?? "image/png";
        return `data:${mimeType};base64,${part.inlineDataBase64}`;
      }
    }
  }
  return null;
}
