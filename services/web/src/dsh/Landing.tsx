/** Landing page shown to signed-out visitors. */

type Session = {
  authenticated: boolean;
  user: { name?: string; email?: string } | null;
  googleConfigured: boolean;
  localAllowed: boolean;
  authRequired: boolean;
};

export function Landing({ session }: { session: Session }) {
  const signInLocally = async () => {
    await fetch("/auth/local", { method: "POST" });
    window.location.assign("/");
  };

  return (
    <div className="flex min-h-screen flex-col bg-white">
      <header className="flex h-16 items-center gap-2.5 px-6 sm:px-10">
        <img src="/logo.png" alt="" aria-hidden="true" className="h-7 w-10 object-cover" />
        <span className="text-[15px] font-semibold tracking-tight text-neutral-900">
          MicroBalance
        </span>
      </header>

      <main className="mx-auto flex w-full max-w-[980px] flex-1 items-center px-6 py-10 sm:px-10">
        <div className="grid w-full gap-12 lg:grid-cols-[1.15fr_0.85fr] lg:items-center">
          <section>
            <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-neutral-400">
              Agentic finance
            </p>
            <h1 className="mt-3 text-[34px] font-bold leading-[1.12] tracking-[-0.02em] text-neutral-900 sm:text-[44px]">
              Run your books by asking.
            </h1>
            <p className="mt-4 max-w-[46ch] text-[14.5px] leading-6 text-neutral-500">
              Invoices, bills, payroll, VAT and the ledger live in one place. Ask in plain
              English and MicroBalance proposes the entries, checks them, and files the
              paperwork.
            </p>

            <div className="mt-8 flex flex-col items-start gap-2.5">
              {session.googleConfigured ? (
                <a
                  href="/auth/google/start"
                  className="inline-flex h-11 items-center gap-2.5 rounded-lg bg-neutral-900 px-5 text-[13.5px] font-medium text-white transition-colors hover:bg-neutral-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900/30 focus-visible:ring-offset-2"
                >
                  <GoogleMark />
                  Continue with Google
                </a>
              ) : (
                <div className="inline-flex h-11 items-center gap-2.5 rounded-lg bg-neutral-100 px-5 text-[13.5px] font-medium text-neutral-400">
                  <GoogleMark />
                  Google sign-in needs credentials
                </div>
              )}

              {session.localAllowed ? (
                <button
                  type="button"
                  onClick={() => void signInLocally()}
                  className="h-11 rounded-lg px-5 text-[13.5px] font-medium text-neutral-600 transition-colors hover:bg-neutral-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900/15"
                >
                  Continue locally as Damian
                </button>
              ) : null}

              {!session.googleConfigured && !session.localAllowed ? (
                <p className="max-w-[44ch] text-[12px] leading-5 text-neutral-400">
                  Set FLARE_GOOGLE_CLIENT_ID and FLARE_GOOGLE_CLIENT_SECRET to enable Google
                  sign-in, or FLARE_AUTH_ALLOW_LOCAL=true for a local demo session.
                </p>
              ) : null}
            </div>

            <p className="mt-8 text-[11.5px] text-neutral-400">
              Sessions are signed cookies. Your books stay in PostgreSQL.
            </p>
          </section>

          <aside className="rounded-2xl border border-neutral-200 bg-neutral-50/60 p-6">
            <p className="text-[11px] font-medium uppercase tracking-[0.08em] text-neutral-400">
              What you can ask
            </p>
            <ul className="mt-4 space-y-3 text-[13.5px] leading-6 text-neutral-700">
              <li>“Invoice Adeshina for two Ankara fabrics and show me the aged receivable.”</li>
              <li>“What is my VAT payable this quarter?”</li>
              <li>“Draft October payroll and list the approvals it needs.”</li>
              <li>“Show the trial balance and flag anything unusual.”</li>
            </ul>
            <div className="mt-6 border-t border-neutral-200 pt-4 text-[11.5px] leading-5 text-neutral-400">
              Every write becomes a pending journal until it is approved.
            </div>
          </aside>
        </div>
      </main>

      <footer className="px-6 pb-6 text-[11px] text-neutral-400 sm:px-10">
        MicroBalance · double-entry accounting with an agent
      </footer>
    </div>
  );
}

function GoogleMark() {
  return (
    <span
      aria-hidden="true"
      className="grid h-4 w-4 place-items-center rounded-full bg-white text-[10px] font-bold text-neutral-900"
    >
      G
    </span>
  );
}
