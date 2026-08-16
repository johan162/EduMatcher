import * as RadixSwitch from "@radix-ui/react-switch";
import clsx from "clsx";

interface Props {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
  id?: string;
  "aria-label"?: string;
}

export function Switch({ checked, onCheckedChange, disabled, id, ...rest }: Props) {
  return (
    <RadixSwitch.Root
      id={id}
      checked={checked}
      onCheckedChange={onCheckedChange}
      disabled={disabled}
      aria-label={rest["aria-label"]}
      className={clsx(
        "relative h-6 w-11 shrink-0 rounded-full border border-border transition-colors",
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent",
        checked ? "bg-accent" : "bg-muted",
        disabled && "cursor-not-allowed opacity-50",
      )}
    >
      <RadixSwitch.Thumb
        className={clsx(
          "block h-5 w-5 translate-x-0.5 rounded-full bg-white shadow transition-transform",
          "data-[state=checked]:translate-x-[22px]",
        )}
      />
    </RadixSwitch.Root>
  );
}
