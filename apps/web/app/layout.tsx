import type { Metadata } from "next";
import { SiteFooterCredits } from "@/components/Credits";
import type { ReactNode } from "react";
import { Nav } from "@/components/Nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "GridMind — DE-LU electricity load intelligence",
  description:
    "Point-in-time day-ahead load forecasts for Germany–Luxembourg, benchmarked against the TSOs' official forecast, built on open data.",
};

const themeBoot = `try{var t=localStorage.getItem('gm-theme');if(t&&t!=='system')document.documentElement.setAttribute('data-theme',t)}catch(e){}`;

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeBoot }} />
      </head>
      <body className="min-h-screen antialiased">
        <Nav />
        <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
        <footer className="mx-auto max-w-7xl px-4 pb-10 pt-4 text-[12px] text-muted">
          <SiteFooterCredits />
        </footer>
      </body>
    </html>
  );
}
