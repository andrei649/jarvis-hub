import type { Metadata } from "next";
// Brand type ramp (spec §1.3): Space Grotesk for UI, JetBrains Mono for data — self-hosted, no CDN.
import "@fontsource/space-grotesk/400.css";
import "@fontsource/space-grotesk/500.css";
import "@fontsource/space-grotesk/600.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
import "@fontsource/jetbrains-mono/700.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "WorldView — 4D OSINT",
  description: "Time-scrubbable 3D globe fusing air / sea / space / cyber OSINT.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
