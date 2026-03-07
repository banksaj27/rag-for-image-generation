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
      <body className="font-sans antialiased">
        {children}
      </body>
    </html>
  );
}
