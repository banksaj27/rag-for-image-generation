import { GoogleGenAI, Modality } from "@google/genai";

const apiKey = process.env.GOOGLE_API_KEY;

function getClient() {
  if (!apiKey || apiKey.trim() === "") {
    throw new Error("GOOGLE_API_KEY is missing or empty");
  }
  return new GoogleGenAI({ apiKey, apiVersion: "v1beta" });
}

/**
 * Generates an image from a text prompt using Gemini 2.0 Flash experimental.
 * Returns a base64 data URL (data:image/png;base64,...).
 */
export async function generateTextToImage(prompt: string): Promise<string> {
  const client = getClient();
  const candidateModels = [
    "gemini-2.5-flash-image",
    "gemini-3.1-flash-image-preview",
    "gemini-3-pro-image-preview",
    "gemini-2.0-flash-exp-image-generation",
  ];

  let lastError: unknown = null;

  for (const model of candidateModels) {
    try {
      const response = await client.models.generateContent({
        model,
        contents: prompt,
        config: {
          responseModalities: [Modality.TEXT, Modality.IMAGE],
        },
      });

      const parts = response.candidates?.[0]?.content?.parts;
      if (!parts?.length) {
        continue;
      }

      for (const part of parts) {
        const p = part as {
          inlineData?: { data?: string; mimeType?: string };
          inline_data?: { data?: string; mime_type?: string };
        };
        const inline = p.inlineData ?? p.inline_data;
        if (inline?.data) {
          const m = inline as { mimeType?: string; mime_type?: string };
          const mimeType = m.mimeType ?? m.mime_type ?? "image/png";
          return `data:${mimeType};base64,${inline.data}`;
        }
      }
    } catch (error) {
      lastError = error;
      const message = error instanceof Error ? error.message.toLowerCase() : "";
      // Keep trying when a model is unavailable for this account/region/version.
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

  if (lastError instanceof Error) {
    throw new Error(
      `No Gemini image generation model is available for this API key/region. Last error: ${lastError.message}`
    );
  }
  throw new Error("No image data returned by any available Gemini model");
}
