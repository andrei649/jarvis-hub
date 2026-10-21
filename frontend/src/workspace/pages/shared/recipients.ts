/* Recipient lists typed by people: commas, semicolons, spaces or new lines between addresses,
   duplicates folded case-insensitively. The server validates again (spec §6: ≤ 20 recipients,
   valid addresses, optional allowed domains); checking here only spares a round trip. */
export const MAX_RECIPIENTS = 20;
const EMAIL_PATTERN = /^[^\s@,;]+@[^\s@,;]+\.[^\s@,;]+$/;

export interface ParsedRecipients {
  emails: string[];
  /** The first address that is not an email, if any. */
  invalid: string | null;
}

export function parseRecipients(text: string): ParsedRecipients {
  const seen = new Set<string>();
  const emails: string[] = [];
  let invalid: string | null = null;
  for (const raw of text.split(/[\s,;]+/)) {
    const email = raw.trim();
    if (!email) continue;
    if (!EMAIL_PATTERN.test(email) || email.length > 254) {
      invalid = invalid ?? email;
      continue;
    }
    const folded = email.toLowerCase();
    if (seen.has(folded)) continue;
    seen.add(folded);
    emails.push(email);
  }
  return { emails, invalid };
}
