import React from 'react';

export function godotDownload(language: string, source: string, index: number, lang?: string): React.ReactNode {
  const label = language.toLowerCase();
  const scene = label === 'tscn' || label === 'gdscene';
  if (scene ? !/^\[gd_scene\s+[^\]\r\n]*\bformat=\d+\b[^\]\r\n]*\]$/.test(source.split(/\r\n|\r|\n/, 1)[0].trim())
    : !['gdscript', 'gd'].includes(label) || !source.split(/\r\n|\r|\n/).some(line => line.trim() && !line.trim().startsWith('#'))) return null;
  const name = `${scene ? 'scene' : 'script'}-${index}.${scene ? 'tscn' : 'gd'}`;
  const title = scene
    ? (lang === 'ro' ? 'Descarcă scena Godot' : 'Download Godot scene')
    : (lang === 'ro' ? 'Descarcă scriptul Godot' : 'Download Godot script');
  const download = () => {
    const url = URL.createObjectURL(new Blob([source], { type: 'text/plain;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = name;
    document.body.appendChild(link);
    try {
      link.click();
    } finally {
      link.remove();
      // A browser may cancel a download if its URL is revoked in the click task.
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
  };
  return <button type="button" className="tool-btn" aria-label={`${title} (${name})`} onClick={download}>{title}</button>;
}
