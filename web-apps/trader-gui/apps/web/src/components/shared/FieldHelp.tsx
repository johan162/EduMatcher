import { fieldHelp, type HelpForm } from "@/lib/fieldHelp.js";
import { FieldInfo } from "./FieldInfo.js";

/** The "i" for a form field, from the shared field help; nothing for a field without any. */
export function FieldHelp({ form, field }: { form: HelpForm; field: string }) {
  const lines = fieldHelp(form, field);
  return lines ? <FieldInfo label={field} lines={lines} /> : null;
}
