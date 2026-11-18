const cellSize = 160;
const atlasWidth = 960;

// Indices follow the left-to-right order in crew-portraits.webp.
const portraits = {
  carbon: {tile: '#443325', index: 0},
  astra: {tile: '#153e4e', index: 1},
  dot: {tile: '#37294f', index: 2},
  argon: {tile: '#502d3b', index: 3},
  hydrogen: {tile: '#174536', index: 4},
  codex: {tile: '#253858', index: 5},
};

export function avatar(id) {
  const {tile, index} = Object.hasOwn(portraits, id) ? portraits[id] : portraits.dot;
  const x = index * cellSize;
  return `<span class="avatar" aria-hidden="true" style="--tint:${tile}"><svg viewBox="${x} 0 ${cellSize} ${cellSize}" overflow="hidden" aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg">
    <image href="./crew-portraits.webp" width="${atlasWidth}" height="${cellSize}"/>
  </svg></span>`;
}
