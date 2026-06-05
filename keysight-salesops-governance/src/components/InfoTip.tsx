/**
 * InfoTip: compact "i" icon that reveals a short explanation on hover or
 * keyboard focus. Used to collapse paragraph-style intros into a single label
 * plus a discoverable tooltip.
 *
 * Accessibility:
 *   - The trigger is a real <button>, so it is reachable by Tab.
 *   - The popover content is rendered into the DOM at all times and linked
 *     via aria-describedby; assistive tech reads it whenever the button has
 *     focus, regardless of hover state.
 *   - Visibility is driven by either :hover on the wrapper or :focus-visible
 *     on the button, so the popover appears under both pointer and keyboard
 *     interaction without JavaScript state.
 *
 * Sizing follows the surrounding text: the icon is 14px and inherits its
 * baseline from the parent inline-flex, so it sits cleanly next to a label.
 */
import { useId } from "react";

type InfoTipProps = {
  /** The explanation shown inside the popover. Keep to 1-2 short sentences. */
  text: string;
  /** Which edge the popover anchors to. Defaults to "left". */
  position?: "left" | "right";
  /** Visually hidden label announced before the explanation. */
  ariaLabel?: string;
  className?: string;
};

export function InfoTip({
  text,
  position = "left",
  ariaLabel = "More information",
  className = "",
}: InfoTipProps) {
  const tooltipId = useId();
  return (
    <span className={`relative group inline-flex items-center align-middle ${className}`}>
      <button
        type="button"
        aria-label={ariaLabel}
        aria-describedby={tooltipId}
        className="peer w-3.5 h-3.5 rounded-full border border-zbrain-muted/70 text-zbrain-muted
                   flex items-center justify-center text-[9px] font-bold leading-none
                   hover:border-zbrain hover:text-zbrain
                   focus:outline-none focus-visible:border-zbrain focus-visible:text-zbrain
                   focus-visible:ring-2 focus-visible:ring-zbrain/30 transition-colors"
      >
        i
      </button>
      <span
        id={tooltipId}
        role="tooltip"
        className={`pointer-events-none absolute top-5 z-40 w-72 rounded-lg bg-zbrain-ink
                    text-white text-[11px] leading-relaxed p-3 shadow-2xl whitespace-pre-line
                    opacity-0 group-hover:opacity-100 peer-focus-visible:opacity-100
                    transition-opacity duration-100
                    ${position === "right" ? "right-0" : "left-0"}`}
      >
        {text}
      </span>
    </span>
  );
}

export default InfoTip;
