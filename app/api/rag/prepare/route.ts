import { spawn } from "node:child_process";
import path from "node:path";
import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";

const MARKER = "--- Assistant Response ---";

function extractAssistantOutput(stdout: string): string {
  const markerIndex = stdout.lastIndexOf(MARKER);
  if (markerIndex === -1) {
    return stdout.trim();
  }
  return stdout.slice(markerIndex + MARKER.length).trim();
}

function runMainRag(prompt: string): Promise<{ output: string }> {
  return new Promise((resolve, reject) => {
    const scriptPath = path.join(process.cwd(), "main-rag.py");
    const pythonBin =
      process.env.RAG_PYTHON_BIN ?? path.join(process.cwd(), ".venv312", "bin", "python");
    const child = spawn(pythonBin, [scriptPath], {
      cwd: process.cwd(),
      env: { ...process.env, RAG_INPUT: prompt },
    });
    let stdout = "";
    let stderr = "";
    let finished = false;
    const startedAt = Date.now();

    console.log(`[rag/prepare] spawned main-rag.py pid=${child.pid} python=${pythonBin}`);

    child.stdout.on("data", (chunk) => {
      const text = chunk.toString();
      stdout += text;
      console.log(`[rag/prepare][stdout] ${text.trimEnd()}`);
    });

    child.stderr.on("data", (chunk) => {
      const text = chunk.toString();
      stderr += text;
      console.error(`[rag/prepare][stderr] ${text.trimEnd()}`);
    });

    child.on("error", (error) => {
      if (finished) return;
      finished = true;
      console.error(`[rag/prepare] process error pid=${child.pid}:`, error);
      reject(error);
    });

    child.on("close", (code) => {
      if (finished) return;
      finished = true;
      const elapsedMs = Date.now() - startedAt;
      console.log(`[rag/prepare] process exited pid=${child.pid} code=${code} elapsed_ms=${elapsedMs}`);
      if (code !== 0) {
        const details = stderr.trim() || stdout.trim() || `exit code ${code}`;
        reject(new Error(`main-rag.py failed: ${details}`));
        return;
      }
      resolve({ output: extractAssistantOutput(stdout) });
    });

    child.stdin.end();
  });
}

export async function POST(request: NextRequest) {
  let body: { prompt?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const prompt = typeof body?.prompt === "string" ? body.prompt.trim() : "";
  if (!prompt) {
    return NextResponse.json({ error: "prompt is required" }, { status: 400 });
  }

  try {
    console.log(`[rag/prepare] request received prompt_len=${prompt.length}`);
    const result = await runMainRag(prompt);
    console.log(`[rag/prepare] success output_len=${result.output.length}`);
    return NextResponse.json({
      success: true,
      ragOutput: result.output,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown RAG preparation error";
    // Do not block the native image generation phase if RAG prep fails.
    console.error(`[rag/prepare] failed: ${message}`);
    return NextResponse.json({
      success: false,
      error: message,
    });
  }
}
