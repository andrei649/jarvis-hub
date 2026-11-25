import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { encodePhotoshopLayout, renderPhotoshopLayout } from '../photoshop-document';

type Draw = { kind?: 'rect' | 'text' | 'image'; text?: string; x?: number; y?: number; args?: unknown[]; font?: string };
const drawn = new Map<HTMLCanvasElement, Draw[]>();
let originalGetContext: typeof HTMLCanvasElement.prototype.getContext;

beforeEach(() => {
  originalGetContext = HTMLCanvasElement.prototype.getContext;
  drawn.clear();
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(function (this: HTMLCanvasElement) {
    let calls = drawn.get(this);
    if (!calls) { calls = []; drawn.set(this, calls); }
    const context = {
      font: '30px Arial', fillStyle: '', textBaseline: 'alphabetic',
      measureText(text: string) {
        const size = Number(/(\d+)px/u.exec(this.font)?.[1] || 30);
        return { width: Array.from(text).length * size * 0.54 };
      },
      fillRect(...args: unknown[]) { calls!.push({ kind: 'rect', args }); },
      fillText(text: string, x: number, y: number) { calls!.push({ kind: 'text', text, x, y, font: this.font }); },
      drawImage(...args: unknown[]) { calls!.push({ kind: 'image', args }); },
      getImageData(_x: number, _y: number, width: number, height: number) {
        const data = new Uint8ClampedArray(width * height * 4);
        const mark = (x: number, y: number) => {
          const col = Math.max(0, Math.min(width - 1, Math.floor(x)));
          const row = Math.max(0, Math.min(height - 1, Math.floor(y)));
          data[(row * width + col) * 4 + 3] = 255;
        };
        for (const call of calls!) {
          if (call.kind === 'text') { mark(call.x!, call.y!); mark(call.x! + 100, call.y! + 20); }
          else if (call.kind === 'rect') {
            const [x, y, w, h] = call.args as number[];
            mark(x, y); mark(x + w - 1, y + h - 1);
          } else if (call.kind === 'image') {
            const [, x, y, w, h] = call.args!;
            mark(x as number, y as number); mark((x as number) + (w as number) - 1, (y as number) + (h as number) - 1);
          }
        }
        return { width, height, data };
      },
      createImageData(width: number, height: number) {
        return { width, height, data: new Uint8ClampedArray(width * height * 4) };
      },
    };
    return context as unknown as CanvasRenderingContext2D;
  });
});
afterEach(() => { vi.restoreAllMocks(); HTMLCanvasElement.prototype.getContext = originalGetContext; });

function image(width: number, height: number): HTMLImageElement {
  const result = document.createElement('img');
  Object.defineProperties(result, {
    complete: { value: true }, naturalWidth: { value: width }, naturalHeight: { value: height },
  });
  return result;
}

it('renders a fixed high-contrast composition with a contained photo and preserved Unicode lines', () => {
  const photo = image(1600, 900);
  const canvas = renderPhotoshopLayout({ title: 'Știință vizuală', body: 'Bună, lume 🧠.\nAl doilea rând.', image: photo });
  expect([canvas.width, canvas.height]).toEqual([1200, 800]);
  const operations = drawn.get(canvas)!;
  expect(operations.filter(call => call.text !== undefined).map(call => call.text))
    .toEqual(['Știință vizuală', 'Bună, lume 🧠.', 'Al doilea rând.']);
  const photoDraw = operations.find(call => call.args?.[0] === photo)!.args!;
  expect(photoDraw.slice(1)).toEqual([760, 320.5, 368, 207]);
});

it('wraps ordinary words first, preserves every source character, and refuses overflow explicitly', () => {
  const title = 'A short title with several words';
  const canvas = renderPhotoshopLayout({ title, body: '', image: image(800, 600) });
  const lines = drawn.get(canvas)!.filter(call => call.text !== undefined).map(call => call.text!);
  expect(lines.join('')).toBe(title);
  expect(lines).toHaveLength(2);
  expect(lines[0]).toMatch(/\s$/u);
  expect(lines[1]).toMatch(/^several/u);
  expect(() => renderPhotoshopLayout({ title: 'Valid', body: 'Very long body '.repeat(150) }))
    .toThrow(/Body does not fit|Body is too long/u);
  expect(() => renderPhotoshopLayout({ title: ' ', body: '' })).toThrow(/Enter a title/u);
  expect(() => renderPhotoshopLayout({ title: 'Valid', body: '', image: document.createElement('img') }))
    .toThrow(/not finished loading/u);
});

it('lets a trailing space hang when the preceding word fits the paragraph box', () => {
  // Chrome measured “Botanical workshop for” at 622.289px in a 632px box, while
  // its following space made the measured advance 637.848px. The word stays on line one.
  const title = '123456789 1234567890 next';
  const canvas = renderPhotoshopLayout({ title, body: '', image: image(800, 600) });
  const lines = drawn.get(canvas)!.filter(call => call.text !== undefined).map(call => call.text!);
  expect(lines).toEqual(['123456789 1234567890 ', 'next']);
  expect(lines.join('')).toBe(title);
  const trailing = renderPhotoshopLayout({ title: '123456789 1234567890 ', body: '', image: image(800, 600) });
  expect(drawn.get(trailing)!.filter(call => call.text !== undefined).map(call => call.text))
    .toEqual(['123456789 1234567890 ']);
});

it('encodes real PSD layers with native editable title and body text, plus a separate photo', async () => {
  const { readPsd } = await import('ag-psd');
  const input = { title: 'Titlu românesc 🧠', body: 'First paragraph with words.\nAl doilea rând.', image: image(600, 900) };
  const blob = await encodePhotoshopLayout(input);
  expect(blob.type).toBe('image/vnd.adobe.photoshop');
  const bytes = await blob.arrayBuffer();
  expect(new TextDecoder().decode(bytes.slice(0, 4))).toBe('8BPS');
  const psd = readPsd(bytes, { skipLayerImageData: true, skipCompositeImageData: true, skipThumbnail: true });
  expect([psd.width, psd.height]).toEqual([1200, 800]);
  expect(psd.children?.map(layer => layer.name)).toEqual(['Background', 'Photo', 'Title', 'Body']);
  const title = psd.children?.find(layer => layer.name === 'Title')?.text;
  const body = psd.children?.find(layer => layer.name === 'Body')?.text;
  expect(title?.text).toBe(input.title);
  expect(body?.text).toBe(input.body);
  expect(title).toMatchObject({ shapeType: 'box', transform: [1, 0, 0, 1, 72, 95],
    style: { font: { name: 'Arial-BoldMT' }, fontSize: 56, leading: 68, autoLeading: false } });
  expect(body).toMatchObject({ shapeType: 'box', transform: [1, 0, 0, 1, 72, 216],
    style: { font: { name: 'ArialMT' }, fontSize: 30, leading: 42, autoLeading: false } });
  expect(title?.boxBounds?.[2]).toBe(632);
  expect(body?.boxBounds?.[2]).toBe(632);
  const photo = psd.children?.find(layer => layer.name === 'Photo');
  expect([photo?.left, photo?.top, photo?.right, photo?.bottom]).toEqual([760, 148, 1128, 700]);
  expect(psd.children?.find(layer => layer.name === 'Title')?.right).toBeLessThan(1200);
});

it('omits the body and photo layers when neither is supplied', async () => {
  const { readPsd } = await import('ag-psd');
  const blob = await encodePhotoshopLayout({ title: 'Plain title', body: '' });
  const psd = readPsd(await blob.arrayBuffer(), { skipLayerImageData: true, skipCompositeImageData: true, skipThumbnail: true });
  expect(psd.children?.map(layer => layer.name)).toEqual(['Background', 'Title']);
  expect(psd.children?.[1].text?.text).toBe('Plain title');
});
