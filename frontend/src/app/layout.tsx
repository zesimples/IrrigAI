import type { Metadata } from "next";
import { DM_Sans, Fraunces, Instrument_Serif, JetBrains_Mono } from "next/font/google";
import "@/styles/globals.css";
import { ToastProvider } from "@/hooks/useToast";
import { Toaster } from "@/components/ui/Toaster";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";

const dmSans = DM_Sans({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-dm-sans",
});

const fraunces = Fraunces({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-fraunces",
});

const instrumentSerif = Instrument_Serif({
  subsets: ["latin"],
  weight: "400",
  style: ["normal", "italic"],
  variable: "--font-instrument",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
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
