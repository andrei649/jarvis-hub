/** A small, fixed canvas whose PSD keeps the photo and both captions editable. */
export type PhotoshopLayoutInput = { title: string; body: string; image?: HTMLImageElement };

export class PhotoshopLayoutError extends Error {
  constructor(message: string, readonly romanian: string) { super(message); }
}

const WIDTH = 1200;
const HEIGHT = 800;
const LEFT = 72;
const TOP = 92;
const BOTTOM = 728;
const PHOTO = { left: 760, top: 144, width: 368, height: 560 };
const COLOR = { background: '#162029', panel: '#23323c', title: '#f6f3e9', body: '#e1e7e8', accent: '#89c7c1' };
const TITLE = { size: 56, leading: 68, family: 'Arial', maxLines: 3 };
const BODY = { size: 30, leading: 42, family: 'Arial' };

type Prepared = {
  rawTitle: string; rawBody: string; title: string[]; body: string[]; bodyTop: number; textWidth: number;
  image: HTMLImageElement | undefined; photoFit: { x: number; y: number; width: number; height: number } | null;
};
type Psd = import('ag-psd').Psd;

function canvas(): HTMLCanvasElement {
  const result = document.createElement('canvas');
  result.width = WIDTH;
  result.height = HEIGHT;
  return result;
}

function context(target: HTMLCanvasElement): CanvasRenderingContext2D {
  const ctx = target.getContext('2d');
  if (!ctx) throw new PhotoshopLayoutError('Canvas rendering is unavailable on this device.', 'Acest dispozitiv nu poate afișa previzualizarea.');
  return ctx;
}

function normalize(value: string, label: string, max: number): string {
  const field = label === 'Title' ? 'Titlul' : 'Textul răspunsului';
  if (typeof value !== 'string') throw new PhotoshopLayoutError(`${label} must be text.`, `${field} trebuie introdus ca text.`);
  const normalized = value.replace(/\r\n?/g, '\n');
  if (Array.from(normalized).length > max) throw new PhotoshopLayoutError(`${label} is too long (maximum ${max} characters).`, `${field} depășește limita de ${max} de caractere.`);
  if (/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/u.test(normalized))
    throw new PhotoshopLayoutError(`${label} contains an unsupported control character.`, `${field} conține un caracter de control neacceptat.`);
  if (normalized.includes('\t')) throw new PhotoshopLayoutError(`${label} contains a tab; use spaces instead.`, `${field} conține tabulatori. Înlocuiește-i cu spații.`);
  return normalized;
}

function graphemes(value: string): string[] {
  const Segmenter = (Intl as unknown as { Segmenter?: new (locale: string | undefined, options: { granularity: 'grapheme' }) =>
    { segment: (text: string) => Iterable<{ segment: string }> } }).Segmenter;
  if (Segmenter) return Array.from(new Segmenter(undefined, { granularity: 'grapheme' }).segment(value), part => part.segment);
  return Array.from(value);
}

function wrap(ctx: CanvasRenderingContext2D, value: string, width: number): string[] {
  const lines: string[] = [];
  for (const paragraph of value.split('\n')) {
    let line = '';
    for (const character of graphemes(paragraph)) {
      line += character;
      while (ctx.measureText(line).width > width) {
        // A trailing space has no ink. Let it end the line when the word itself fits,
        // matching Photoshop's paragraph wrap without moving that word to the next line.
        if (character === ' ' && line.trimEnd() && ctx.measureText(line.trimEnd()).width <= width) {
          break;
        }
        const units = graphemes(line);
        if (units.length === 1) throw new PhotoshopLayoutError('A character is too wide for the Photoshop layout.', 'Un caracter este prea lat pentru această machetă.');
        let whitespace = -1;
        for (let index = 0; index < units.length - 1; index++) if (/\s/u.test(units[index])) whitespace = index;
        if (whitespace >= 0 && whitespace < units.length - 1) {
          lines.push(units.slice(0, whitespace + 1).join(''));
          line = units.slice(whitespace + 1).join('');
        } else { lines.push(units.slice(0, -1).join('')); line = units[units.length - 1]; }
      }
    }
    lines.push(line);
  }
  return lines;
}

function prepare(input: PhotoshopLayoutInput, ctx: CanvasRenderingContext2D): Prepared {
  const rawTitle = normalize(input.title, 'Title', 180);
  const rawBody = normalize(input.body, 'Body', 4000);
  if (!rawTitle.trim()) throw new PhotoshopLayoutError('Enter a title for the Photoshop document.', 'Introdu un titlu pentru document.');
  const image = input.image;
  if (image && (!image.complete || image.naturalWidth <= 0 || image.naturalHeight <= 0))
    throw new PhotoshopLayoutError('The selected image has not finished loading.', 'Imaginea selectată încă se încarcă.');
  const textWidth = image ? 632 : WIDTH - LEFT * 2;
  ctx.font = `bold ${TITLE.size}px ${TITLE.family}`;
  const title = wrap(ctx, rawTitle, textWidth);
  if (title.length > TITLE.maxLines) throw new PhotoshopLayoutError('Title does not fit in the Photoshop layout.', 'Scurtează titlul ca să încapă în machetă.');
  const bodyTop = TOP + title.length * TITLE.leading + 54;
  ctx.font = `${BODY.size}px ${BODY.family}`;
  const body = rawBody ? wrap(ctx, rawBody, textWidth) : [];
  if (bodyTop + body.length * BODY.leading > BOTTOM)
    throw new PhotoshopLayoutError('Body does not fit in the Photoshop layout. Shorten it before exporting.', 'Scurtează textul răspunsului ca să încapă în machetă.');
  const photoFit = image ? (() => {
    const scale = Math.min(PHOTO.width / image.naturalWidth, PHOTO.height / image.naturalHeight);
    const width = image.naturalWidth * scale;
    const height = image.naturalHeight * scale;
    return { x: PHOTO.left + (PHOTO.width - width) / 2, y: PHOTO.top + (PHOTO.height - height) / 2, width, height };
  })() : null;
  return { rawTitle, rawBody, title, body, bodyTop, textWidth, image, photoFit };
}

function drawBackground(ctx: CanvasRenderingContext2D, withImage: boolean): void {
  ctx.fillStyle = COLOR.background;
  ctx.fillRect(0, 0, WIDTH, HEIGHT);
  ctx.fillStyle = COLOR.accent;
  ctx.fillRect(LEFT, 62, withImage ? 632 : WIDTH - LEFT * 2, 5);
  if (withImage) { ctx.fillStyle = COLOR.panel; ctx.fillRect(PHOTO.left, PHOTO.top, PHOTO.width, PHOTO.height); }
}

function drawTitle(ctx: CanvasRenderingContext2D, prepared: Prepared): void {
  ctx.textBaseline = 'top';
  ctx.font = `bold ${TITLE.size}px ${TITLE.family}`;
  ctx.fillStyle = COLOR.title;
  prepared.title.forEach((line, index) => ctx.fillText(line, LEFT, TOP + index * TITLE.leading));
}

function drawBody(ctx: CanvasRenderingContext2D, prepared: Prepared): void {
  ctx.textBaseline = 'top';
  ctx.font = `${BODY.size}px ${BODY.family}`;
  ctx.fillStyle = COLOR.body;
  prepared.body.forEach((line, index) => ctx.fillText(line, LEFT, prepared.bodyTop + index * BODY.leading));
}

function paintPhoto(ctx: CanvasRenderingContext2D, prepared: Prepared): void {
  if (prepared.image && prepared.photoFit) {
    const fit = prepared.photoFit;
    try { ctx.drawImage(prepared.image, fit.x, fit.y, fit.width, fit.height); }
    catch { throw new PhotoshopLayoutError('The selected image could not be drawn. Choose another image.', 'Imaginea nu poate fi afișată. Alege o altă imagine.'); }
  }
}

export function renderPhotoshopLayout(input: PhotoshopLayoutInput): HTMLCanvasElement {
  const target = canvas();
  const ctx = context(target);
  const prepared = prepare(input, ctx);
  drawBackground(ctx, !!prepared.image);
  paintPhoto(ctx, prepared);
  drawTitle(ctx, prepared);
  drawBody(ctx, prepared);
  return target;
}

export async function encodePhotoshopLayout(input: PhotoshopLayoutInput): Promise<Blob> {
  const composite = renderPhotoshopLayout(input);
  const prepared = prepare(input, context(composite));
  const background = canvas();
  drawBackground(context(background), !!prepared.image);
  const title = canvas();
  drawTitle(context(title), prepared);
  const body = prepared.body.length ? canvas() : null;
  if (body) drawBody(context(body), prepared);
  const photo = prepared.image ? canvas() : null;
  if (photo) paintPhoto(context(photo), prepared);
  const { writePsd } = await import('ag-psd');
  const titleHeight = prepared.title.length * TITLE.leading;
  const textLayer = (name: string, text: string, image: HTMLCanvasElement, top: number, height: number,
    size: number, leading: number, color: { r: number; g: number; b: number }, bold = false): NonNullable<Psd['children']>[number] => ({
    name, canvas: image,
    text: {
      // Photoshop 27.8 redraw measured 3 px high for Arial Bold and 2 px high for Arial; the raster preview stays fixed.
      text, transform: [1, 0, 0, 1, LEFT, top + (bold ? 3 : 2)], shapeType: 'box',
      boxBounds: [0, 0, prepared.textWidth, height],
      top, left: LEFT, right: LEFT + prepared.textWidth, bottom: top + height,
      style: { font: { name: bold ? 'Arial-BoldMT' : 'ArialMT' }, fontSize: size, leading,
        autoLeading: false, fauxBold: false, fillColor: color },
      paragraphStyle: { justification: 'left', autoHyphenate: false, everyLineComposer: false },
    },
  });
  const children: NonNullable<Psd['children']> = [
    { name: 'Background', canvas: background },
    ...(photo ? [{ name: 'Photo', canvas: photo }] : []),
    textLayer('Title', prepared.rawTitle, title, TOP, titleHeight, TITLE.size, TITLE.leading,
      { r: 246, g: 243, b: 233 }, true),
    ...(body ? [textLayer('Body', prepared.rawBody, body, prepared.bodyTop,
      prepared.body.length * BODY.leading, BODY.size, BODY.leading, { r: 225, g: 231, b: 232 })] : []),
  ];
  // The supplied composite and text bitmaps keep previews usable until Photoshop refreshes type layers.
  const psd: Psd = { width: WIDTH, height: HEIGHT, canvas: composite, children };
  let bytes: ArrayBuffer;
  try { bytes = writePsd(psd, { trimImageData: true }); }
  catch { throw new PhotoshopLayoutError('Could not create the editable Photoshop document.', 'Documentul Photoshop nu a putut fi creat.'); }
  return new Blob([bytes], { type: 'image/vnd.adobe.photoshop' });
}
