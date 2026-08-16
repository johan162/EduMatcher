import * as RadixSelect from "@radix-ui/react-select";
import clsx from "clsx";

export interface SelectOption {
  value: string;
  label: string;
}

interface Props {
  value: string;
  onValueChange: (value: string) => void;
  options: SelectOption[];
  disabled?: boolean;
  id?: string;
  className?: string;
  "aria-label"?: string;
}

export function Select({ value, onValueChange, options, disabled, id, className, ...rest }: Props) {
  return (
    <RadixSelect.Root value={value} onValueChange={onValueChange} disabled={disabled}>
      <RadixSelect.Trigger
        id={id}
        aria-label={rest["aria-label"]}
        className={clsx(
          "inline-flex h-9 items-center justify-between gap-2 rounded-md border border-border bg-surface px-3 text-sm",
          "focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent",
          disabled && "cursor-not-allowed opacity-50",
          className,
        )}
      >
        <RadixSelect.Value />
        <RadixSelect.Icon>▾</RadixSelect.Icon>
      </RadixSelect.Trigger>
      <RadixSelect.Portal>
        <RadixSelect.Content
          className="z-50 overflow-hidden rounded-md border border-border bg-surface-raised shadow-lg"
          position="popper"
          sideOffset={4}
        >
          <RadixSelect.Viewport className="p-1">
            {options.map((option) => (
              <RadixSelect.Item
                key={option.value}
                value={option.value}
                className={clsx(
                  "relative flex cursor-pointer select-none items-center rounded px-6 py-1.5 text-sm",
                  "data-[highlighted]:bg-accent data-[highlighted]:text-accent-fg data-[highlighted]:outline-none",
                )}
              >
                <RadixSelect.ItemText>{option.label}</RadixSelect.ItemText>
                <RadixSelect.ItemIndicator className="absolute left-1">✓</RadixSelect.ItemIndicator>
              </RadixSelect.Item>
            ))}
          </RadixSelect.Viewport>
        </RadixSelect.Content>
      </RadixSelect.Portal>
    </RadixSelect.Root>
  );
}
