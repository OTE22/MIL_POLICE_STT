export type Box = { field: string; x: number; y: number; width: number; height: number; font_size: number };
export type Page = { image: string; width_pt: number; height_pt: number; boxes: Box[] };
export type Handle = 'n' | 'ne' | 'e' | 'se' | 's' | 'sw' | 'w' | 'nw';
export type Guides = { x?: number; y?: number };
export const clamp = (n: number, min: number, max: number) => Math.max(min, Math.min(max, n));
export const ptToMm = (pt: number) => pt * 25.4 / 72;
export const mmToFraction = (mm: number, pt: number) => mm / ptToMm(pt);
export const fractionToMm = (fraction: number, pt: number) => fraction * ptToMm(pt);

function snapAxis(value: number, offsets: number[], targets: number[], tolerance: number, step: number, max: number) {
  let result = clamp(value, 0, max), distance = tolerance, guide: number | undefined;
  for (const offset of offsets) for (const target of targets) {
    const candidate = target - offset;
    const delta = Math.abs(candidate - value);
    if (candidate >= 0 && candidate <= max && delta <= distance) {
      result = candidate; distance = delta; guide = target;
    }
  }
  // Existing fields/page guides take precedence over the optional physical grid.
  if (guide === undefined && step > 0) result = clamp(Math.round(value / step) * step, 0, max);
  return { value: result, guide };
}

export function moveBox(box: Box, dx: number, dy: number, page: Page, others: Box[], options: { snap: boolean; gridMm: number; toleranceX: number; toleranceY: number }) {
  const x = box.x + dx, y = box.y + dy;
  if (!options.snap) return { box: { ...box, x: clamp(x,0,1-box.width), y: clamp(y,0,1-box.height) }, guides: {} as Guides };
  const sx = snapAxis(x,[0,box.width/2,box.width],[0,.5,1,...others.flatMap(b => [b.x,b.x+b.width/2,b.x+b.width])],options.toleranceX,mmToFraction(options.gridMm,page.width_pt),1-box.width);
  const sy = snapAxis(y,[0,box.height/2,box.height],[0,.5,1,...others.flatMap(b => [b.y,b.y+b.height/2,b.y+b.height])],options.toleranceY,mmToFraction(options.gridMm,page.height_pt),1-box.height);
  return { box: { ...box,x:sx.value,y:sy.value }, guides: { x:sx.guide,y:sy.guide } };
}

export function resizeBox(box: Box, handle: Handle, dx: number, dy: number, page: Page, others: Box[], options: { snap: boolean; gridMm: number; toleranceX: number; toleranceY: number }) {
  let left=box.x, right=box.x+box.width, top=box.y, bottom=box.y+box.height;
  const minW=Math.min(box.width,mmToFraction(2,page.width_pt)), minH=Math.min(box.height,mmToFraction(2,page.height_pt));
  const guides: Guides = {};
  const edge = (value: number, axis: 'x' | 'y') => {
    if (!options.snap) return value;
    const result = snapAxis(value,[0],axis === 'x' ? [0,.5,1,...others.flatMap(b => [b.x,b.x+b.width])] : [0,.5,1,...others.flatMap(b => [b.y,b.y+b.height])],axis === 'x' ? options.toleranceX : options.toleranceY,mmToFraction(options.gridMm,axis === 'x' ? page.width_pt : page.height_pt),1);
    guides[axis] = result.guide; return result.value;
  };
  if (handle.includes('w')) { left=clamp(edge(left+dx,'x'),0,right-minW); if (guides.x !== left) delete guides.x; }
  if (handle.includes('e')) { right=clamp(edge(right+dx,'x'),left+minW,1); if (guides.x !== right) delete guides.x; }
  if (handle.includes('n')) { top=clamp(edge(top+dy,'y'),0,bottom-minH); if (guides.y !== top) delete guides.y; }
  if (handle.includes('s')) { bottom=clamp(edge(bottom+dy,'y'),top+minH,1); if (guides.y !== bottom) delete guides.y; }
  return { box:{ ...box,x:left,y:top,width:right-left,height:bottom-top },guides };
}

export function setDimensionMm(box: Box, key: 'x'|'y'|'width'|'height', value: number, page: Page): Box {
  if (!Number.isFinite(value)) return box;
  const next = { ...box,[key]:mmToFraction(value,key === 'x' || key === 'width' ? page.width_pt : page.height_pt) };
  next.width=clamp(next.width,Math.min(mmToFraction(2,page.width_pt),1-box.x),1-box.x);
  next.height=clamp(next.height,Math.min(mmToFraction(2,page.height_pt),1-box.y),1-box.y);
  // Changing position preserves dimensions; changing size preserves the origin.
  if (key === 'x' || key === 'y') {
    next.width=box.width; next.height=box.height;
    next.x=clamp(next.x,0,1-box.width); next.y=clamp(next.y,0,1-box.height);
  }
  return next;
}

export function overlappingPairs(boxes: Box[]): [number,number][] {
  const pairs: [number,number][]=[];
  boxes.forEach((a,i) => boxes.slice(i+1).forEach((b,j) => {
    if (Math.min(a.x+a.width,b.x+b.width)-Math.max(a.x,b.x) > .0001 && Math.min(a.y+a.height,b.y+b.height)-Math.max(a.y,b.y) > .0001) pairs.push([i,i+j+1]);
  }));
  return pairs;
}
