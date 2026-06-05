/**
 * Brand logos for the Settings → Integrations page tiles.
 *
 * Each logo is a self-contained inline SVG sized at 24x24, designed to sit
 * inside a 44x44 white rounded square. Colors are the brand's primary tone
 * so the integration is recognisable at a glance.
 *
 * These are simplified representations rather than pixel-perfect official
 * logos; they exist to provide visual identity in the operator UI without
 * pulling in an icon library.
 */

type LogoProps = { className?: string };

export function SalesforceLogo({ className = "" }: LogoProps) {
  // Salesforce cloud silhouette in the brand blue.
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true">
      <path
        fill="#00A1E0"
        d="M10 5.4a4.2 4.2 0 0 1 3-1.3c1.6 0 3 .9 3.7 2.2.6-.3 1.3-.5 2.1-.5 2.8 0 5.1 2.3 5.1 5.2 0 1.2-.4 2.3-1 3.1.1.3.2.7.2 1.1 0 1.5-1.2 2.7-2.7 2.7-.3 0-.5 0-.8-.1-.3 1.4-1.6 2.4-3.1 2.4-1 0-2-.5-2.5-1.3-.6.4-1.3.6-2 .6-1.5 0-2.9-.8-3.6-2.1-.5.2-1 .3-1.5.3C4.6 17.7 2.7 15.8 2.7 13.5c0-1.6.9-3 2.2-3.7-.3-.6-.4-1.3-.4-1.9 0-2.7 2.2-4.8 4.8-4.8 1.6 0 3 .8 3.9 1.9"
      />
    </svg>
  );
}

export function ServiceNowLogo({ className = "" }: LogoProps) {
  // ServiceNow green ring with stylised wordmark glyph.
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true">
      <circle cx="12" cy="12" r="11" fill="#62D84E" />
      <path
        fill="#FFFFFF"
        d="M12 5.2A6.8 6.8 0 0 0 5.2 12 6.8 6.8 0 0 0 7 16.7c-.2.4-.3.8-.3 1.2 0 .4.3.7.7.7.4 0 .8-.2 1.2-.4A6.8 6.8 0 0 0 12 18.8a6.8 6.8 0 0 0 4.4-1.6c.4.2.8.4 1.2.4.4 0 .7-.3.7-.7 0-.4-.1-.8-.3-1.2A6.8 6.8 0 0 0 18.8 12 6.8 6.8 0 0 0 12 5.2Zm0 10.6a3.8 3.8 0 1 1 0-7.6 3.8 3.8 0 0 1 0 7.6Z"
      />
    </svg>
  );
}

export function SharePointLogo({ className = "" }: LogoProps) {
  // Microsoft SharePoint three-circle interlock in graded teal.
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true">
      <circle cx="7" cy="8" r="5.5" fill="#036C70" />
      <circle cx="15" cy="11" r="4.5" fill="#1A9BA1" />
      <circle cx="13" cy="17.5" r="3" fill="#37C6D0" />
    </svg>
  );
}

export function OpenAILogo({ className = "" }: LogoProps) {
  // OpenAI hex-knot mark in monochrome.
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true">
      <path
        fill="#0b1220"
        d="M22.3 9.8a6 6 0 0 0-.5-4.9A6 6 0 0 0 15.3 2 6.1 6.1 0 0 0 5 4.2 6 6 0 0 0 1 7.1a6 6 0 0 0 .7 7.1 6 6 0 0 0 .5 4.9 6.1 6.1 0 0 0 6.5 2.9A6 6 0 0 0 13.3 24a6 6 0 0 0 5.8-4.2 6 6 0 0 0 4-2.9 6 6 0 0 0-.7-7.1Zm-9 12.6a4.5 4.5 0 0 1-2.9-1l.1-.1 4.8-2.7a.8.8 0 0 0 .4-.7v-6.7l2 1.1v5.6a4.5 4.5 0 0 1-4.5 4.5Zm-9.7-4.1a4.5 4.5 0 0 1-.5-3l.1.1 4.8 2.7a.8.8 0 0 0 .8 0L14.7 14v2.3l-4.9 2.9a4.5 4.5 0 0 1-6.2-1.7Zm-1.3-10.4A4.5 4.5 0 0 1 4.7 6v5.7a.8.8 0 0 0 .4.7l5.8 3.3-2 1.2a.1.1 0 0 1-.1 0L4 13.8a4.5 4.5 0 0 1-1.7-5.9Zm16.6 3.9-5.8-3.4 2-1.2h.1l4.8 2.8a4.5 4.5 0 0 1-.7 8.1v-5.7a.8.8 0 0 0-.4-.6Zm2-3-.1-.1L16 5.9a.8.8 0 0 0-.8 0L9.4 9.2V6.9a.1.1 0 0 1 0-.1l4.8-2.7a4.5 4.5 0 0 1 6.7 4.7ZM8.3 12.8l-2-1.2v-5.6A4.5 4.5 0 0 1 13.7 2.6h-.1L8.7 5.4a.8.8 0 0 0-.4.7v6.7Zm1.1-2.4 2.6-1.5 2.6 1.5v3l-2.6 1.5-2.6-1.5Z"
      />
    </svg>
  );
}

export function AzureLogo({ className = "" }: LogoProps) {
  // Microsoft Azure wedge. Used for Document Intelligence + Translator.
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true">
      <linearGradient id="azuregrad" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stopColor="#0078D4" />
        <stop offset="1" stopColor="#5EA0EF" />
      </linearGradient>
      <path
        fill="url(#azuregrad)"
        d="M7.4 4.6h6.5L7.4 22 1 19.5Zm6.8.4h6.4L23 22h-9.9L17 13Z"
      />
    </svg>
  );
}

export function EmailLogo({ className = "" }: LogoProps) {
  // Generic envelope. Used for the multi-provider Email tile.
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true">
      <rect x="2" y="5" width="20" height="14" rx="2" fill="#EA4335" />
      <path d="M3 7l9 6.5L21 7" stroke="#FFFFFF" strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function AIOALogo({ className = "" }: LogoProps) {
  // Keysight AIOA mark. Uses the amber accent we use elsewhere in the app.
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true">
      <rect x="2" y="2" width="20" height="20" rx="5" fill="#F59E0B" />
      <path
        fill="#FFFFFF"
        d="M8.2 17V8.6h2l2.2 5.1 2.2-5.1h2V17h-1.6v-5.7L13 17h-1.2L9.8 11.3V17Z"
      />
    </svg>
  );
}

export function ContractsLogo({ className = "" }: LogoProps) {
  // Generic contract / signed-document mark for the Contracts placeholder.
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true">
      <rect x="5" y="3" width="14" height="18" rx="2" fill="#8B5CF6" />
      <path d="M8 8h8M8 11h8M8 14h5" stroke="#FFFFFF" strokeWidth="1.4" strokeLinecap="round" />
      <circle cx="16" cy="17" r="2.4" fill="#FFFFFF" />
      <path d="M14.9 17l.8.8 1.4-1.7" stroke="#8B5CF6" strokeWidth="1.4" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function OracleLogo({ className = "" }: LogoProps) {
  // Oracle ring. Used for Oracle EBS / Jitterbit placeholders if surfaced.
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true">
      <ellipse cx="12" cy="12" rx="9" ry="6" fill="none" stroke="#C74634" strokeWidth="3" />
    </svg>
  );
}
