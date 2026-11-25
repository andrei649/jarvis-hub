const invalidPart = /[\\/:*?"<>|#^%\u0000-\u001f\u007f]/;

function validPart(part) {
  return part.length > 0 && part === part.trim() && !part.startsWith('.') &&
    !part.endsWith('.') && !invalidPart.test(part);
}

/** Only the native open action is supported. The vault and file are separate URI values. */
export function obsidianOpenUri(source) {
  if (typeof source?.vault !== 'string' || typeof source.file !== 'string' ||
      typeof source.readable !== 'boolean' || source.vault.length > 255 ||
      !validPart(source.vault) || source.file.length > 4096 ||
      !source.file.toLowerCase().endsWith('.md') || !source.file.split('/').every(validPart)) return null;
  try {
    return 'obsidian://open?vault=' + encodeURIComponent(source.vault) + '&file=' + encodeURIComponent(source.file);
  } catch {
    return null; // Invalid UTF-16 has no URI representation.
  }
}
