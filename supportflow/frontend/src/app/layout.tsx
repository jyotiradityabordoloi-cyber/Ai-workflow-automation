import type { Metadata } from "next";
import { Epilogue, JetBrains_Mono } from "next/font/google";
import { AppShell } from "@/components/shell";
import "./globals.css";

// The same pairing as the landing page (supportflow/site): Epilogue for text and headings, JetBrains Mono for IDs and figures.
const epilogue = Epilogue({ variable: "--font-epilogue", subsets: ["latin"], weight: ["400", "500", "600"] });
const jetbrains = JetBrains_Mono({ variable: "--font-jetbrains", subsets: ["latin"], weight: ["400", "500"] });

export const metadata: Metadata = {
  title: "SupportFlow AI",
  description: "AI-assisted support operations workspace: classification, grounded drafting and human-approved escalation.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className={`${epilogue.variable} ${jetbrains.variable} font-sans antialiased`}>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
