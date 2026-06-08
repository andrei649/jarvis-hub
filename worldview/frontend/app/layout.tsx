import type { Metadata } from "next";
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
