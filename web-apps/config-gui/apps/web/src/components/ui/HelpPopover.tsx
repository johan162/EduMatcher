import * as Popover from "@radix-ui/react-popover";

interface Props {
  /** One-paragraph plain-language explanation. */
  children: React.ReactNode;
  /** Equivalent CLI flag, shown for terminal users (design §10). */
  cliFlag?: string;
  /** Optional deep link into docs/user-guide/. */
  docHref?: string;
}

export function HelpPopover({ children, cliFlag, docHref }: Props) {
  return (
    <Popover.Root>
      <Popover.Trigger
        aria-label="Field help"
        className="ml-1 inline-flex h-4 w-4 items-center justify-center rounded-full border border-border text-[10px] text-fg-subtle hover:text-fg focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
      >
        i
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          sideOffset={6}
          className="z-50 max-w-xs rounded-md border border-border bg-surface-raised p-3 text-xs leading-relaxed text-fg shadow-lg"
        >
          <div>{children}</div>
          {cliFlag && (
            <div className="mt-2 text-fg-subtle">
              CLI: <code className="rounded bg-muted px-1 py-0.5">{cliFlag}</code>
            </div>
          )}
          {docHref && (
            <a
              href={docHref}
              target="_blank"
              rel="noreferrer"
              className="mt-2 inline-block text-linked underline"
            >
              Learn more
            </a>
          )}
          <Popover.Arrow className="fill-[var(--color-border)]" />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
