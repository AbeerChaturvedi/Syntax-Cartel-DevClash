import "./globals.css";

export const metadata = {
  title: "Velure — Financial Crisis Early Warning System",
  description: "Real-time systemic risk detection using ML ensemble (Isolation Forest + LSTM Autoencoder + CISS + Merton). Built for DevClash 2026 by Syntax Cartel.",
  keywords: "financial crisis, early warning system, systemic risk, machine learning, CISS, Merton, hackathon",
  authors: [{ name: "Syntax Cartel" }],
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <head>
        <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🛡️</text></svg>" />
      </head>
      <body>
        {children}
      </body>
    </html>
  );
}
