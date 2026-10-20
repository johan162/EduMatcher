/**
 * Time range and refresh interval (design §12.2, D1.3).
 *
 * Choosing a range writes `?from=now-<range>` into the URL, and only that:
 * AppShell copies the URL into the store, so a pasted link, the back button
 * and a choice here all take the same path.
 */

import { Clock, RefreshCw } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { PickerMenu } from "../shared/PickerMenu.js";
import {
  RANGE_LABEL,
  RANGE_NAMES,
  rangeParam,
  REFRESH_LABEL,
  REFRESH_NAMES,
  type RangeName,
} from "../../lib/range.js";
import { useDashStore } from "../../store/useDashStore.js";

export function TimePicker() {
  const range = useDashStore((s) => s.range);
  const [, setSearchParams] = useSearchParams();

  const choose = (next: RangeName) =>
    setSearchParams((params) => {
      params.set("from", rangeParam(next));
      return params;
    });

  return (
    <PickerMenu
      name="Time range"
      icon={<Clock size={14} />}
      value={range}
      options={RANGE_NAMES}
      optionLabel={(r) => RANGE_LABEL[r]}
      valueLabel={(r) => `Last ${r}`}
      onSelect={choose}
    />
  );
}

export function RefreshPicker() {
  const refresh = useDashStore((s) => s.refresh);
  const setRefresh = useDashStore((s) => s.setRefresh);

  return (
    <PickerMenu
      name="Refresh history"
      icon={<RefreshCw size={14} />}
      value={refresh}
      options={REFRESH_NAMES}
      optionLabel={(r) => REFRESH_LABEL[r]}
      valueLabel={(r) => REFRESH_LABEL[r]}
      onSelect={setRefresh}
    />
  );
}
