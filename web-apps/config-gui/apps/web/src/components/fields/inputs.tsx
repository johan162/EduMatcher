import clsx from "clsx";

const baseInput =
  "h-9 rounded-md border border-border bg-surface px-3 text-sm text-fg placeholder:text-optional-default focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent";

interface TextInputProps {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  onBlur?: () => void;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  "aria-label"?: string;
}

export function TextInput({ value, onChange, onBlur, className, ...rest }: TextInputProps) {
  return (
    <input
      type="text"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onBlur={onBlur}
      className={clsx(baseInput, className)}
      {...rest}
    />
  );
}

interface NumberInputProps {
  id?: string;
  value: number | undefined | null;
  onChange: (value: number | undefined) => void;
  placeholder?: string;
  min?: number;
  max?: number;
  step?: number;
  disabled?: boolean;
  className?: string;
  "aria-label"?: string;
}

export function NumberInput({
  value,
  onChange,
  className,
  min,
  max,
  step,
  ...rest
}: NumberInputProps) {
  return (
    <input
      type="number"
      value={value === undefined || value === null ? "" : value}
      min={min}
      max={max}
      step={step}
      onChange={(e) => {
        const raw = e.target.value;
        onChange(raw === "" ? undefined : Number(raw));
      }}
      className={clsx(baseInput, "w-40", className)}
      {...rest}
    />
  );
}

interface TimeInputProps {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  "aria-label"?: string;
}

export function TimeInput({ value, onChange, ...rest }: TimeInputProps) {
  return (
    <input
      type="time"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={clsx(baseInput, "w-36")}
      {...rest}
    />
  );
}
