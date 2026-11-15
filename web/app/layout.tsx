import type { Metadata, Viewport } from "next";
import { IBM_Plex_Mono, Inter } from "next/font/google";
import { AccessGate } from "@/components/AccessGate";
import "./globals.css";

const inter = Inter({ variable: "--font-inter", subsets: ["latin"] });
const plexMono = IBM_Plex_Mono({ variable: "--font-plex-mono", subsets: ["latin"], weight: ["400", "500"] });

export const metadata: Metadata = {
  title: "FirstIn: pre-incident plans",
  description: "Cited NFPA 1660 pre-incident plans from CoStar, Vexcel and Matterport.",
};

export const viewport: Viewport = {
  themeColor: "#f4f5f7",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${inter.variable} ${plexMono.variable} h-full`}>
      <body className="h-full bg-canvas text-fg">
        <AccessGate>{children}</AccessGate>
      </body>
    </html>
  );
}
