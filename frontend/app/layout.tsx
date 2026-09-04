import type {Metadata} from 'next';
import './globals.css';
import {AppShell} from '../components/AppShell';
import {EngagementProvider} from '../lib/engagement-context';
import {AuthProvider} from '../lib/auth-context';
import {SignInGate} from '../components/SignInGate';

export const metadata: Metadata = {
  title: 'EliteInteliA AI Data Automation Factory',
  description: 'Enterprise AI Data Automation Factory — from RFP and requirements to governed engineering, AI, validation and release.',
  icons: {
    icon: [
      {url: '/icon.svg', type: 'image/svg+xml'},
      {url: '/logo.svg', type: 'image/svg+xml'},
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
