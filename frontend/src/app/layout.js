import { Inter, JetBrains_Mono } from 'next/font/google';
import "./globals.css";

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
  description: "Real-time systemic risk detection using ML ensemble (Isolation Forest + LSTM Autoencoder + CISS + Merton). Built for DevClash 2026 by Syntax Cartel.",
  keywords: "financial crisis, early warning system, systemic risk, machine learning, CISS, Merton, hackathon",
  authors: [{ name: "Syntax Cartel" }],
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" className={`${inter.variable} ${jetbrainsMono.variable}`}>
      <head>
        <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><rect width='100' height='100' rx='20' fill='%23818cf8'/><text x='50' y='72' font-size='60' font-weight='700' fill='white' text-anchor='middle' font-family='system-ui'>V</text></svg>" />
      </head>
      <body>
        {children}
      </body>
    </html>
  );
}
