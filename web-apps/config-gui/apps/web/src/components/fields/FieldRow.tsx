import clsx from "clsx";
import { HelpPopover } from "@/components/ui/HelpPopover";
import { useFieldStatus, useFlashOnHighlight } from "./useField";

export interface FieldHelp {
  text: React.ReactNode;
  cliFlag?: string;
  docHref?: string;
}

interface Props {
  label: string;
  /** Diagnostic/highlight path, e.g. "symbols.AAPL.level". */
  path?: string;
  htmlFor?: string;
  required?: boolean;
  help?: FieldHelp;
  /** Ghost hint shown when an optional field is at its default, e.g. "Default: 0.5". */
  defaultHint?: string;
  /** True when an optional field has been explicitly set (controls accent + reset). */
  isSet?: boolean;
  onReset?: () => void;
  /** "Required before starting the engine" style chip (design §6). */
  requiredBeforeStart?: boolean;
  personaNote?: string;
  children: React.ReactNode;
  className?: string;
}

export function FieldRow({
  label,
  path,
  htmlFor,
  required,
  help,
  defaultHint,
  isSet,
  onReset,
  requiredBeforeStart,
  personaNote,
  children,
  className,
}: Props) {
  const status = useFieldStatus(path);
  const flashRef = useFlashOnHighlight(path);

  const borderColor =
    status.severity === "error"
      ? "border-l-error"
      : status.severity === "warning"
        ? "border-l-warning"
        : required
          ? "border-l-required"
          : isSet
            ? "border-l-optional-set"
            : "border-l-transparent";

  return (
    <div
      ref={flashRef}
      className={clsx(
        "border-l-2 pl-3 py-2",
        borderColor,
        status.linked && "ring-1 ring-linked",
        className,
      )}
    >
      <div className="mb-1 flex items-center gap-1.5">
        <label htmlFor={htmlFor} className="text-sm font-medium">
          {label}
          {required && <span className="ml-0.5 text-required">*</span>}
        </label>
        {help && (
          <HelpPopover cliFlag={help.cliFlag} docHref={help.docHref}>
            {help.text}
          </HelpPopover>
        )}
        {requiredBeforeStart && (
          <span className="rounded bg-warning/20 px-1.5 py-0.5 text-[10px] font-medium text-warning">
            Required before starting the engine
          </span>
        )}
        {isSet && onReset && (
          <button
            type="button"
            onClick={onReset}
            title="Reset to default"
            className="ml-1 text-xs text-fg-subtle hover:text-fg"
          >
            ↺
          </button>
        )}
      </div>

      <div className="flex items-center gap-2">{children}</div>

      {defaultHint && !isSet && (
        <p className="mt-1 text-xs text-optional-default">{defaultHint}</p>
      )}
      {personaNote && <p className="mt-1 text-xs text-linked">{personaNote}</p>}
      {status.messages.map((message, i) => (
        <p
          key={i}
          className={clsx(
            "mt-1 text-xs",
            status.severity === "error" ? "text-error" : "text-warning",
          )}
        >
          {status.severity === "error" ? "✗" : "!"} {message}
        </p>
      ))}
    </div>
  );
}
