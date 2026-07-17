import type { Metadata } from "next";
import localFont from "next/font/local";
import "@/styles/globals.css";
import { ToastProvider } from "@/hooks/useToast";
import { Toaster } from "@/components/ui/Toaster";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";

// Self-hosted (src/app/fonts/) so `next build` never fetches from Google —
// production hosts can't reach fonts.gstatic.com at image-build time.
// dm-sans/fraunces/jetbrains-mono are variable fonts: one file per family.
const dmSans = localFont({
  src: "./fonts/dm-sans.woff2",
  weight: "400 500",
  variable: "--font-dm-sans",
});

const fraunces = localFont({
  src: "./fonts/fraunces.woff2",
  weight: "400 600",
  variable: "--font-fraunces",
});

const instrumentSerif = localFont({
  src: [
    { path: "./fonts/instrument-serif-400.woff2", weight: "400", style: "normal" },
    { path: "./fonts/instrument-serif-400-italic.woff2", weight: "400", style: "italic" },
  ],
  variable: "--font-instrument",
});

const jetbrainsMono = localFont({
  src: "./fonts/jetbrains-mono.woff2",
  weight: "400 600",
  variable: "--font-jetbrains",
});

export const metadata: Metadata = {
  title: "IrrigAI — Herdade do Esporão",
  description: "Sistema de recomendação de rega com inteligência artificial",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt">
      <body className={`${dmSans.variable} ${fraunces.variable} ${instrumentSerif.variable} ${jetbrainsMono.variable} font-sans`}>
        <ErrorBoundary>
          <ToastProvider>
            {children}
            <Toaster />
          </ToastProvider>
        </ErrorBoundary>
      </body>
    </html>
  );
}
