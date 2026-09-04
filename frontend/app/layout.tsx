import type {Metadata} from 'next';
import './globals.css';
import {AppShell} from '../components/AppShell';
import {EngagementProvider} from '../lib/engagement-context';
import {AuthProvider} from '../lib/auth-context';
import {SignInGate} from '../components/SignInGate';

export const metadata: Metadata = {
  title: 'EliteInteliA Intelligence Factory',
  description: 'Enterprise Data & AI Delivery Platform — from Intake to Intelligence at Scale',
  // The browser tab carries the brand too. Next serves these from /public;
  // when a file is absent the browser simply shows its default, so a missing
  // asset degrades quietly rather than rendering a broken icon.
  icons: {
    icon: [
      {url: '/icon.svg', type: 'image/svg+xml'},
      {url: '/icon.png', type: 'image/png', sizes: '512x512'},
      {url: '/favicon.ico', sizes: 'any'},
    ],
    apple: '/apple-touch-icon.png',
  },
};

export default function RootLayout({children}: {children: React.ReactNode}) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>
          <SignInGate>
            <EngagementProvider>
              <AppShell>{children}</AppShell>
            </EngagementProvider>
          </SignInGate>
        </AuthProvider>
      </body>
    </html>
  );
}
