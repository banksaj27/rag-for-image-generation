"use client";

import confetti from "canvas-confetti";
import { AnimatePresence, motion } from "framer-motion";
import { FormEvent, useEffect, useRef, useState } from "react";

type Phase = "idle" | "routing" | "rendering" | "complete";

const phaseText: Record<Exclude<Phase, "idle" | "complete">, string> = {
  routing: "Agents retrieving reference data",
  rendering: "Generating image",
};

const beamColorByPhase: Record<Phase, string> = {
  idle: "#8B3DFF",
  routing: "#34d399",
  rendering: "#F59E0B",
  complete: "#8B3DFF",
};

function hexToRgb(hex: string) {
  const clean = hex.replace("#", "");
  const bigint = Number.parseInt(clean, 16);
  return {
    r: (bigint >> 16) & 255,
    g: (bigint >> 8) & 255,
    b: bigint & 255,
  };
}

function GlowLayer({
  rgb,
  phase,
  targetPhase,
  opacityIdle,
}: {
  rgb: { r: number; g: number; b: number };
  phase: Phase;
  targetPhase: Phase;
  opacityIdle: number;
}) {
  const isActive = phase === targetPhase || (targetPhase === "idle" && phase === "complete");
  const glowA = `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${targetPhase === "idle" ? 0.34 : 0.26})`;
  const glowB = `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${targetPhase === "idle" ? 0.2 : 0.14})`;
  const glowC = `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${targetPhase === "idle" ? 0.1 : 0.07})`;

  const pulseOpacity = isActive && targetPhase === "idle" ? [0.64, 1, 0.64] : opacityIdle;

  return (
    <motion.div
      className="absolute inset-0 mix-blend-screen"
      style={{ transform: "translateZ(0)", backfaceVisibility: "hidden" }}
      initial={false}
      animate={{
        opacity: isActive && targetPhase === "idle"
          ? pulseOpacity
          : isActive
            ? opacityIdle
            : 0,
      }}
      transition={
        isActive && targetPhase === "idle"
          ? { duration: 8.2, repeat: Infinity, ease: [0.4, 0, 0.6, 1], times: [0, 0.5, 1] }
          : { duration: 1.4, ease: [0.22, 1, 0.36, 1] }
      }
    >
      <motion.div
        className="absolute inset-0"
        style={{
          background: `radial-gradient(circle at 50% 56%, ${glowA} 0%, ${glowB} 36%, ${glowC} 62%, transparent 82%)`,
          filter: "blur(2px) saturate(1.18)",
          transform: "translateZ(0)",
        }}
        animate={{
          scale: isActive && targetPhase === "idle" ? [1, 1.035, 1.075, 1.035, 1] : 1.02,
        }}
        transition={{
          duration: 9,
          repeat: Infinity,
          ease: [0.4, 0, 0.6, 1],
          times: [0, 0.25, 0.5, 0.75, 1],
        }}
      />
      <motion.div
        className="absolute inset-0"
        style={{
          background: `radial-gradient(circle at 50% 56%, rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, 0.24) 0%, transparent 54%)`,
          filter: "blur(9px)",
          transform: "translateZ(0)",
        }}
        animate={{
          opacity:
            isActive && targetPhase === "idle"
              ? [0.24, 0.5, 0.68, 0.5, 0.24]
              : isActive
                ? 0.4
                : 0,
        }}
        transition={
          isActive && targetPhase === "idle"
            ? { duration: 7.6, repeat: Infinity, ease: [0.4, 0, 0.6, 1], times: [0, 0.25, 0.5, 0.75, 1] }
            : { duration: 1.4, ease: [0.22, 1, 0.36, 1] }
        }
      />
    </motion.div>
  );
}

function AmbientGlow({ phase }: { phase: Phase }) {
  const purple = hexToRgb(beamColorByPhase.idle);
  const green = hexToRgb(beamColorByPhase.routing);
  const orange = hexToRgb(beamColorByPhase.rendering);

  return (
    <div className="absolute inset-0 z-10">
      <GlowLayer rgb={purple} phase={phase} targetPhase="idle" opacityIdle={0.85} />
      <GlowLayer rgb={green} phase={phase} targetPhase="routing" opacityIdle={0.82} />
      <GlowLayer rgb={orange} phase={phase} targetPhase="rendering" opacityIdle={0.82} />
    </div>
  );
}

const LOADING_TEXT_DELAY_MS = 550;

const ROUTING_DURATION_MS = 4000;

export default function Home() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [prompt, setPrompt] = useState("");
  const [showLoadingText, setShowLoadingText] = useState(false);
  const [isResetting, setIsResetting] = useState(false);
  const [nativeImageUrl, setNativeImageUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const confettiFired = useRef(false);
  const confettiTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const resetTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const currentPromptRef = useRef<string>("");

  useEffect(() => {
    if (phase === "routing") {
      const toRendering = setTimeout(() => setPhase("rendering"), ROUTING_DURATION_MS);
      return () => clearTimeout(toRendering);
    }

    if (phase === "rendering") {
      const controller = new AbortController();
      (async () => {
        const p = currentPromptRef.current;
        setError(null);
        try {
          const res = await fetch("/api/render", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ prompt: p }),
            signal: controller.signal,
          });
          const data = await res.json();
          if (!res.ok) {
            setError(data?.error ?? `Error ${res.status}`);
            setNativeImageUrl(null);
          } else {
            const nextImageUrl = data.nativeImageUrl ?? null;
            // Decode image before phase swap to avoid jank when the complete view mounts.
            if (nextImageUrl) {
              const img = new Image();
              img.src = nextImageUrl;
              if (typeof img.decode === "function") {
                await img.decode().catch(() => undefined);
              } else {
                await new Promise<void>((resolve) => {
                  img.onload = () => resolve();
                  img.onerror = () => resolve();
                });
              }
            }
            setNativeImageUrl(nextImageUrl);
          }
        } catch (e) {
          if ((e as Error).name === "AbortError") return;
          setError(e instanceof Error ? e.message : "Request failed");
          setNativeImageUrl(null);
        } finally {
          setPhase("complete");
        }
      })();
      return () => controller.abort();
    }
  }, [phase]);

  useEffect(() => {
    if (phase === "routing" || phase === "rendering") {
      const timer = setTimeout(() => setShowLoadingText(true), LOADING_TEXT_DELAY_MS);
      return () => clearTimeout(timer);
    }
    const timer = setTimeout(() => setShowLoadingText(false), 0);
    return () => clearTimeout(timer);
  }, [phase]);

  const isProcessing = phase === "routing" || phase === "rendering";
  const showStatusText = isProcessing && showLoadingText;

  useEffect(() => {
    if (phase === "complete" && !confettiFired.current) {
      confettiFired.current = true;
      const opts = {
        particleCount: 60,
        spread: 70,
        origin: { y: 0.65 },
        colors: ["#8B3DFF", "#34d399", "#F59E0B", "#fff"],
      };
      confettiTimer.current = setTimeout(() => {
        confetti({ ...opts, origin: { x: 0.2, y: 0.65 }, angle: 60 });
        confetti({ ...opts, origin: { x: 0.8, y: 0.65 }, angle: 120 });
        confettiTimer.current = setTimeout(
          () => confetti({ ...opts, origin: { x: 0.5, y: 0.7 } }),
          150
        );
      }, 220);
    }
    if (phase !== "complete") {
      confettiFired.current = false;
      if (confettiTimer.current) {
        clearTimeout(confettiTimer.current);
        confettiTimer.current = null;
      }
    }
    return () => {
      if (confettiTimer.current) {
        clearTimeout(confettiTimer.current);
        confettiTimer.current = null;
      }
    };
  }, [phase]);

  const doSubmit = () => {
    if (!prompt.trim() || phase !== "idle") return;
    currentPromptRef.current = prompt.trim();
    setNativeImageUrl(null);
    setError(null);
    setPhase("routing");
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    doSubmit();
  };

  const openImageInNewTab = (url: string, _label: string) => {
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.target = "_blank";
    anchor.rel = "noopener noreferrer";
    anchor.click();
  };

  const openDataUrlImageInNewTab = (dataUrl: string) => {
    const [meta, base64] = dataUrl.split(",", 2);
    const mimeMatch = meta.match(/^data:(.*?);base64$/);
    const mimeType = mimeMatch?.[1] ?? "image/png";
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) {
      bytes[i] = binary.charCodeAt(i);
    }
    const blobUrl = URL.createObjectURL(new Blob([bytes], { type: mimeType }));
    openImageInNewTab(blobUrl, "image");
    setTimeout(() => URL.revokeObjectURL(blobUrl), 30000);
  };

  const openPlaceholderInNewTab = (label: string) => {
    const canvas = document.createElement("canvas");
    canvas.width = 800;
    canvas.height = 600;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    ctx.fillStyle = "#1a1a24";
    ctx.fillRect(0, 0, 800, 600);
    ctx.strokeStyle = "rgba(255,255,255,0.2)";
    ctx.strokeRect(20, 20, 760, 560);
    ctx.fillStyle = "rgba(255,255,255,0.5)";
    ctx.font = "24px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(label, 400, 300);

    const dataUrl = canvas.toDataURL("image/png");
    openDataUrlImageInNewTab(dataUrl);
  };

  const resetFlow = () => {
    if (confettiTimer.current) {
      clearTimeout(confettiTimer.current);
      confettiTimer.current = null;
    }
    if (resetTimer.current) {
      clearTimeout(resetTimer.current);
      resetTimer.current = null;
    }
    setIsResetting(true);
    resetTimer.current = setTimeout(() => {
      setPrompt("");
      setPhase("idle");
      setNativeImageUrl(null);
      setError(null);
      setIsResetting(false);
      resetTimer.current = null;
    }, 560);
  };

  return (
    <main className="relative h-screen w-screen overflow-hidden text-white">
      <div className="tech-bg-gradients absolute inset-0 z-0" />
      <div className="tech-bg-dots absolute inset-0 z-0" />
      <div className="tech-bg-layer absolute inset-0 z-0" />
      <div className="tech-noise absolute inset-0 z-0" />
      <div className="tech-vignette absolute inset-0 z-0" />

      <AmbientGlow phase={phase} />

      <motion.div
        className="absolute inset-x-0 top-[12%] z-20 text-center"
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
      >
        <h1 className="text-[15px] font-semibold tracking-[0.1em] text-white [text-shadow:0_0_10px_rgba(255,255,255,0.18)] sm:text-[17px]">
          RAG for Image Generation
        </h1>
      </motion.div>

      <section className="relative z-20 flex h-full w-full flex-col items-center justify-center px-6">
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35 }}
          className="flex w-full max-w-3xl flex-col items-center gap-6"
        >
          <AnimatePresence mode="wait">
            {phase === "idle" && (
              <motion.form
                key="prompt-form"
                className="w-full max-w-[680px]"
                onSubmit={handleSubmit}
                initial={{ opacity: 0, y: 18 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -24 }}
                transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
              >
                <div className="relative min-h-[120px] overflow-hidden rounded-[3px] border border-white/12 bg-[#1e1f24d9] shadow-[0_0_0_1px_rgba(139,61,255,0.1)_inset,0_0_20px_rgba(139,61,255,0.16)]">
                <textarea
                  value={prompt}
                  onChange={(event) => setPrompt(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      doSubmit();
                    }
                  }}
                  className="font-editor min-h-[120px] w-full resize-none border-none bg-transparent px-5 pb-8 pt-4 pr-10 text-[15px] leading-relaxed text-white antialiased [text-shadow:none] outline-none placeholder:text-white/40"
                  placeholder="Describe what you want to render..."
                  aria-label="Prompt"
                  style={{ caretColor: "rgba(255,255,255,0.9)" }}
                  rows={4}
                />
                <div
                  className={`pointer-events-none absolute bottom-3 right-3 flex items-center gap-1.5 text-[13px] transition-colors duration-200 ${
                    prompt.trim() ? "text-white/72" : "text-white/40"
                  }`}
                  aria-hidden
                >
                  <span>Enter</span>
                  <span
                    className={`text-[15px] font-medium transition-colors duration-200 ${
                      prompt.trim() ? "text-white/90" : "text-white/50"
                    }`}
                  >
                    &gt;
                  </span>
                </div>
              </div>
            </motion.form>
            )}
          </AnimatePresence>

          <AnimatePresence mode="wait">
            {showStatusText && (
              <motion.p
                key={phase}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                transition={{ duration: 0.25 }}
                className="text-center text-sm font-medium tracking-[0.08em] sm:text-base"
              >
                <span className="thinking-pulse" data-text={phaseText[phase]}>
                  {phaseText[phase]}
                </span>
              </motion.p>
            )}
          </AnimatePresence>

          <AnimatePresence mode="wait">
            {phase === "complete" && !isResetting && (
              <motion.div
                key="complete-view"
                initial={{ opacity: 0, y: 14 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }}
                transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
                className="flex w-full max-w-6xl flex-col items-center gap-6"
              >
                {error && (
                  <p className="text-center text-sm font-medium text-red-400">{error}</p>
                )}
                <div className="grid w-full grid-cols-1 gap-6 sm:grid-cols-2">
                  <div className="space-y-2">
                    <div className="text-center text-sm font-medium tracking-[0.06em] text-amber-400">Native</div>
                    <div className="relative flex aspect-square w-full min-h-[340px] max-h-[26rem] items-center justify-center overflow-hidden rounded border border-white/14 bg-black/28 text-sm tracking-[0.08em] text-white/65 shadow-[0_0_20px_rgba(139,61,255,0.2)]">
                      {nativeImageUrl ? (
                        <img
                          src={nativeImageUrl}
                          alt="Generated image"
                          className="h-full w-full object-contain"
                        />
                      ) : (
                        <span>IMAGE PLACEHOLDER A</span>
                      )}
                      <button
                        type="button"
                        onClick={() =>
                          nativeImageUrl
                            ? nativeImageUrl.startsWith("data:")
                              ? openDataUrlImageInNewTab(nativeImageUrl)
                              : openImageInNewTab(nativeImageUrl, "Native")
                            : openPlaceholderInNewTab("IMAGE PLACEHOLDER A")
                        }
                        className="absolute right-[3px] top-2 h-8 w-8 bg-transparent text-white/75 transition hover:text-white"
                        aria-label="Open image in new tab"
                        title="Open image in new tab"
                      >
                        <svg
                          viewBox="0 0 24 24"
                          className="h-5 w-5"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="1.6"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          aria-hidden="true"
                        >
                          <path d="M14 3h7v7" />
                          <path d="M10 14L21 3" />
                          <path d="M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5" />
                        </svg>
                      </button>
                    </div>
                  </div>
                  <div className="space-y-2">
                    <div className="text-center text-sm font-semibold tracking-[0.06em] text-white/85">With RAG</div>
                    <div className="relative flex aspect-square w-full min-h-[340px] max-h-[26rem] items-center justify-center rounded border border-white/14 bg-black/28 text-sm tracking-[0.08em] text-white/65 shadow-[0_0_20px_rgba(139,61,255,0.2)]">
                      IMAGE PLACEHOLDER B
                    <button
                      type="button"
                      onClick={() => openPlaceholderInNewTab("IMAGE PLACEHOLDER B")}
                      className="absolute right-[3px] top-2 h-8 w-8 bg-transparent text-white/75 transition hover:text-white"
                      aria-label="Open image B in new tab"
                      title="Open image B in new tab"
                    >
                      <svg
                        viewBox="0 0 24 24"
                        className="h-5 w-5"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.6"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        aria-hidden="true"
                      >
                        <path d="M14 3h7v7" />
                        <path d="M10 14L21 3" />
                        <path d="M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5" />
                      </svg>
                    </button>
                    </div>
                  </div>
                </div>
                <div className="flex flex-wrap items-center justify-center gap-3">
                  <button
                    type="button"
                    onClick={resetFlow}
                    className="h-10 rounded-md border border-white/18 bg-white/5 px-5 text-sm font-medium tracking-[0.02em] text-white/85 transition hover:bg-white/10"
                  >
                    Start Over
                  </button>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </motion.div>
      </section>
    </main>
  );
}
