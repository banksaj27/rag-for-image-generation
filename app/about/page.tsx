"use client";

import { motion } from "framer-motion";
import Link from "next/link";

export default function AboutPage() {
  return (
    <main className="relative min-h-screen overflow-hidden text-white">
      <motion.div
        className="pointer-events-none absolute inset-0 z-0"
        initial={{ opacity: 0.9 }}
        animate={{ opacity: 0 }}
        transition={{ duration: 0.2, ease: "easeOut" }}
      >
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_56%,rgba(139,61,255,0.34)_0%,rgba(139,61,255,0.2)_36%,rgba(139,61,255,0.1)_62%,transparent_82%)] blur-[2px]" />
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_56%,rgba(139,61,255,0.24)_0%,transparent_54%)] blur-[9px]" />
      </motion.div>

      <motion.section
        className="relative z-10 mx-auto flex min-h-screen w-full max-w-3xl flex-col justify-center px-6 py-14"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
      >
        <div className="rounded border border-white/16 bg-black/35 p-6 shadow-[0_0_0_1px_rgba(139,61,255,0.08)_inset,0_0_26px_rgba(139,61,255,0.14)] sm:p-8">
          <h1 className="text-lg font-semibold tracking-[0.08em] text-white sm:text-xl">About Our Project</h1>
          <p className="mt-4 text-[15px] leading-relaxed text-white/80">
            In NLP, retrieval-augmented generation (RAG) is a method where a model retrieves
            relevant external information first, then uses that context to produce a more accurate
            response.
          </p>
          <p className="mt-3 text-[15px] leading-relaxed text-white/72">
            We observed that image generation can be semantically correct overall, but when it
            renders real-world places it often gets key details wrong, such as hallucinating roads,
            layouts, or structural elements that are not actually present.
          </p>
          <p className="mt-3 text-[15px] leading-relaxed text-white/72">
            To reduce this, we implement a variant of RAG for image generation: the system finds
            relevant reference images online and uses them as grounding context for the generation
            pipeline to avoid hallucination and improve factual visual details.
          </p>
          <p className="mt-3 text-[15px] leading-relaxed text-white/70">
            Built for the YC x Google DeepMind Frontier Multimodal Hackathon by Adam Banks and
            Justin Sato.
          </p>

          <div className="mt-6">
            <Link
              href="/"
              className="inline-flex items-center rounded border border-white/22 bg-white/6 px-3 py-2 text-xs font-medium tracking-[0.06em] text-white/85 transition hover:bg-white/12 hover:text-white"
            >
              Back To Home
            </Link>
          </div>
        </div>
      </motion.section>
    </main>
  );
}
