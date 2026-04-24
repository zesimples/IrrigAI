import * as Sentry from "@sentry/nextjs";

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;

if (dsn) {
  Sentry.init({
    dsn,
    environment: process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT ?? "production",
    tracesSampleRate: 0.1,
    replaysSessionSampleRate: 0.02,
    replaysOnErrorSampleRate: 1.0,
    integrations: [Sentry.replayIntegration()],
    sendDefaultPii: false,
  });
}
