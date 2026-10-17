import type { Metadata } from "next";
import { Delius, Geist, Geist_Mono, Inter } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

// Hand-lettered labels in the 3D room.
const delius = Delius({
  variable: "--font-delius",
  weight: "400",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Waiting Room Monitor",
  description: "Contactless breathing monitor for a waiting-room chair (Wi-Fi CSI). Screening signal only, not a diagnosis.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} ${inter.variable} ${delius.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
