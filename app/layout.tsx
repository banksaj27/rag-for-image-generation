import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "RAG for Image Generation",
  description: "RAG for Image Generation simulation interface",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="relative min-h-screen font-sans antialiased">
        <div aria-hidden className="pointer-events-none fixed inset-0 -z-10">
          <div className="tech-bg-gradients absolute inset-0" />
          <div className="tech-bg-dots absolute inset-0" />
          <div className="tech-bg-layer absolute inset-0" />
          <div className="tech-noise absolute inset-0" />
          <div className="tech-vignette absolute inset-0" />
        </div>
        {children}
      </body>
    </html>
  );
}
