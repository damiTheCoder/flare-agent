/** Auth gate: landing page for visitors, ERP/chat for signed-in users. */

import { useEffect, useState } from "react";
import DshApp from "./dsh/DshApp";
import { Landing } from "./dsh/Landing";

type Session = {
  authenticated: boolean;
  user: { name?: string; email?: string } | null;
  googleConfigured: boolean;
  localAllowed: boolean;
  authRequired: boolean;
};

export default function App() {
  const [session, setSession] = useState<Session | null>(null);

  useEffect(() => {
    let alive = true;
    fetch("/api/auth/session")
      .then((response) => (response.ok ? response.json() : null))
      .then((data: Session | null) => {
        if (!alive) return;
        setSession(
          data ?? {
            authenticated: false,
            user: null,
            googleConfigured: false,
            localAllowed: false,
            authRequired: false,
          },
        );
      })
      .catch(() => {
        if (alive) {
          setSession({
            authenticated: false,
            user: null,
            googleConfigured: false,
            localAllowed: false,
            authRequired: false,
          });
        }
      });
    return () => {
      alive = false;
    };
  }, []);

  if (session === null) {
    return <div className="grid min-h-screen place-items-center bg-white" />;
  }

  // Auth disabled on this deployment: no gate, straight to the app.
  if (!session.authRequired && !session.authenticated) {
    return <DshApp />;
  }

  if (!session.authenticated) {
    return <Landing session={session} />;
  }

  return <DshApp />;
}
