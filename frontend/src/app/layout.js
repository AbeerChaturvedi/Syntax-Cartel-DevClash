import { GeistSans } from 'geist/font/sans';
import { GeistMono } from 'geist/font/mono';
import { Inter, JetBrains_Mono } from 'next/font/google';
import "./globals.css";
import "./redesign.css";

const inter = Inter({
  subsets: ['latin'],
  weight: ['300', '400', '500', '600', '700', '800', '900'],
  variable: '--font-inter',
  display: 'swap',
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  weight: ['400', '500', '600'],
  variable: '--font-jetbrains',
  display: 'swap',
});

export const metadata = {
  title: "Velure — Financial Crisis Early Warning System",
  description: "Real time systemic risk detection using an ML ensemble (Isolation Forest, LSTM Autoencoder, CISS, Merton). Built by Team Syntax Cartel.",
  keywords: "financial crisis, early warning system, systemic risk, machine learning, CISS, Merton",
  authors: [{ name: "Syntax Cartel" }],
};

export default function RootLayout({ children }) {
  return (
    <html
      lang="en"
      className={`dark ${GeistSans.variable} ${GeistMono.variable} ${inter.variable} ${jetbrainsMono.variable}`}
    >
      <head>
        <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 120 120'><rect width='120' height='120' rx='26' fill='%233b82f6'/><path d='M26 34 L60 94 L94 34 L72 42 L60 78 L48 42 Z' fill='white'/></svg>" />
      </head>
      <body>
        {children}
      </body>
    </html>
  );
}
