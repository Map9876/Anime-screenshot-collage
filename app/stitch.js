/* 纯 JS 纯平移拼接内核，零依赖，可在浏览器与 Node 中运行。
   流程与 Python 版一致：裁黑边 → 相位相关两两估计 → 最大生成树布局 → 均值/中值融合 → 裁边补洞。 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.Stitch = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const N = 256;

  function fft1d(re, im, inverse) {
    const n = re.length;
    for (let i = 1, j = 0; i < n; i++) {
      let bit = n >> 1;
      for (; j & bit; bit >>= 1) j ^= bit;
      j ^= bit;
      if (i < j) {
        let t = re[i]; re[i] = re[j]; re[j] = t;
        t = im[i]; im[i] = im[j]; im[j] = t;
      }
    }
    for (let len = 2; len <= n; len <<= 1) {
      const ang = (inverse ? 2 : -2) * Math.PI / len;
      const wr = Math.cos(ang), wi = Math.sin(ang);
      const half = len >> 1;
      for (let i = 0; i < n; i += len) {
        let cr = 1, ci = 0;
        for (let k = 0; k < half; k++) {
          const a = i + k, b = a + half;
          const vr = re[b] * cr - im[b] * ci;
          const vi = re[b] * ci + im[b] * cr;
          re[b] = re[a] - vr; im[b] = im[a] - vi;
          re[a] += vr; im[a] += vi;
          const ncr = cr * wr - ci * wi;
          ci = cr * wi + ci * wr; cr = ncr;
        }
      }
    }
    if (inverse) {
      for (let i = 0; i < n; i++) { re[i] /= n; im[i] /= n; }
    }
  }

  function fft2(re, im, n, inverse) {
    const tr = new Float64Array(n), ti = new Float64Array(n);
    for (let y = 0; y < n; y++) {
      const off = y * n;
      for (let x = 0; x < n; x++) { tr[x] = re[off + x]; ti[x] = im[off + x]; }
      fft1d(tr, ti, inverse);
      for (let x = 0; x < n; x++) { re[off + x] = tr[x]; im[off + x] = ti[x]; }
    }
    for (let x = 0; x < n; x++) {
      for (let y = 0; y < n; y++) { tr[y] = re[y * n + x]; ti[y] = im[y * n + x]; }
      fft1d(tr, ti, inverse);
      for (let y = 0; y < n; y++) { re[y * n + x] = tr[y]; im[y * n + x] = ti[y]; }
    }
  }

  const HANN = (function () {
    const w = new Float64Array(N);
    for (let i = 0; i < N; i++) w[i] = 0.5 - 0.5 * Math.cos(2 * Math.PI * i / (N - 1));
    return w;
  })();

  // 把图像压成 N×N 灰度、加汉宁窗、减均值后做 FFT，结果按 pair 复用
  function prepare(im) {
    const { w, h, data } = im;
    const re = new Float64Array(N * N), z = new Float64Array(N * N);
    let mean = 0;
    for (let y = 0; y < N; y++) {
      const sy = Math.min(h - 1, Math.floor(y * h / N));
      for (let x = 0; x < N; x++) {
        const sx = Math.min(w - 1, Math.floor(x * w / N));
        const p = (sy * w + sx) * 4;
        const g = 0.299 * data[p] + 0.587 * data[p + 1] + 0.114 * data[p + 2];
        re[y * N + x] = g;
        mean += g;
      }
    }
    mean /= N * N;
    const gray = new Float64Array(N * N);
    for (let y = 0; y < N; y++) {
      for (let x = 0; x < N; x++) {
        const i = y * N + x;
        gray[i] = re[i];
        re[i] = (re[i] - mean) * HANN[y] * HANN[x];
      }
    }
    fft2(re, z, N, false);
    return { re, im: z, gray, hp: highpass(gray, N), w, h };
  }

  function subpixel(re, px, py) {
    const at = (x, y) => re[((y + N) % N) * N + ((x + N) % N)];
    const c = at(px, py), l = at(px - 1, py), r = at(px + 1, py);
    const u = at(px, py - 1), d = at(px, py + 1);
    const denx = l - 2 * c + r, deny = u - 2 * c + d;
    const ox = Math.abs(denx) > 1e-9 ? (l - r) / (2 * denx) : 0;
    const oy = Math.abs(deny) > 1e-9 ? (u - d) / (2 * deny) : 0;
    return [Math.max(-1, Math.min(1, ox)), Math.max(-1, Math.min(1, oy))];
  }

  // 按候选位移对齐后重叠区的灰度平均绝对差：真位移的 MAD 明显更小
  function overlapMad(a, b, tx, ty) {
    const sx = Math.round(tx * N / a.w), sy = Math.round(ty * N / a.h);
    let sg = 0, sh = 0, cnt = 0;
    for (let y = 0; y < N; y += 2) {
      const yy = y + sy; if (yy < 0 || yy >= N) continue;
      for (let x = 0; x < N; x += 2) {
        const xx = x + sx; if (xx < 0 || xx >= N) continue;
        sg += Math.abs(a.gray[y * N + x] - b.gray[yy * N + xx]);
        sh += Math.abs(a.hp[y * N + x] - b.hp[yy * N + xx]);
        cnt++;
      }
    }
    // 至少 35% 重叠才算有效：否则小重叠区碰巧颜色相近会压过真正对齐的位移
    // 颜色一致性 + 结构一致性一起评分，避免大片平坦背景误导
    return cnt < 5700 ? 255 : 0.55 * (sg / cnt) + 1.35 * (sh / cnt);
  }

  function highpass(g, M) {
    const h = new Float64Array(M * M);
    for (let y = 0; y < M; y++) {
      for (let x = 0; x < M; x++) {
        const i = y * M + x;
        const avg = (g[Math.max(0, y - 1) * M + x] + g[Math.min(M - 1, y + 1) * M + x]
          + g[y * M + Math.max(0, x - 1)] + g[y * M + Math.min(M - 1, x + 1)]) / 4;
        h[i] = g[i] - avg;
      }
    }
    return h;
  }

  // 64×64 高通图上的暴力粗配准：相位相关峰里没有正确位移时（重叠很小的三段截图）兜底
  function coarseCandidates(a, b) {
    const M = 64, S = N / M;
    const ga = new Float64Array(M * M), gb = new Float64Array(M * M);
    for (let y = 0; y < M; y++) {
      for (let x = 0; x < M; x++) {
        let va = 0, vb = 0;
        for (let j = 0; j < S; j++) {
          for (let i = 0; i < S; i++) {
            va += a.gray[(y * S + j) * N + x * S + i];
            vb += b.gray[(y * S + j) * N + x * S + i];
          }
        }
        ga[y * M + x] = va / (S * S); gb[y * M + x] = vb / (S * S);
      }
    }
    const ha = highpass(ga, M), hb = highpass(gb, M);
    const list = [];
    for (let dy = -M / 2; dy <= M / 2; dy += 2) {
      for (let dx = -M / 2; dx <= M / 2; dx += 2) {
        let sum = 0, cnt = 0;
        for (let y = 0; y < M; y += 2) {
          const yy = y + dy; if (yy < 0 || yy >= M) continue;
          for (let x = 0; x < M; x += 2) {
            const xx = x + dx; if (xx < 0 || xx >= M) continue;
            sum += Math.abs(ha[y * M + x] - hb[yy * M + xx]); cnt++;
          }
        }
        if (cnt < 190) continue;
        list.push([sum / cnt, dx, dy]);
      }
    }
    list.sort((p, q) => p[0] - q[0]);
    const out = [];
    for (const [mad, dx, dy] of list) {
      if (out.every(o => Math.abs(o.dx - dx) > 2 || Math.abs(o.dy - dy) > 2)) {
        out.push({ dx, dy, mad });
      }
      if (out.length >= 6) break;
    }
    return out.map(o => ({ tx: o.dx * a.w / M, ty: o.dy * a.h / M, mad: o.mad }));
  }

  // 纯垂直 / 纯水平摇镜的轴对齐扫描候选（三段式截图这类小重叠素材靠它兜底）
  function axisCandidates(a, b) {
    const out = [];
    const spanY = Math.round(a.h * 0.6), spanX = Math.round(a.w * 0.6);
    for (let dy = -spanY; dy <= spanY; dy += 8) out.push({ dx: 0, dy, peak: 0 });
    for (let dx = -spanX; dx <= spanX; dx += 8) {
      if (dx !== 0) out.push({ dx, dy: 0, peak: 0 });
    }
    return out;
  }

  // 相位相关取前 12 个候选峰 + 粗配准 + 轴对齐扫描 → 用重叠区 MAD 选真正正确的位移
  function phaseShift(a, b) {
    const re = new Float64Array(N * N), im = new Float64Array(N * N);
    for (let i = 0; i < N * N; i++) {
      const ar = a.re[i], ai = a.im[i], br = b.re[i], bi = b.im[i];
      const r = ar * br + ai * bi;
      const m = ai * br - ar * bi;
      const mag = Math.sqrt(r * r + m * m) + 1e-9;
      re[i] = r / mag; im[i] = m / mag;
    }
    fft2(re, im, N, true);
    let best = -Infinity;
    for (let i = 0; i < N * N; i++) if (re[i] > best) best = re[i];
    const cand = [];
    const cut = best * 0.12;
    for (let i = 0; i < N * N; i++) if (re[i] >= cut) cand.push([re[i], i]);
    cand.sort((p, q) => q[0] - p[0]);
    const picked = [];
    for (const [v, i] of cand) {
      const px = i % N, py = (i / N) | 0;
      if (picked.every(p => Math.abs(p.px - px) > 3 || Math.abs(p.py - py) > 3)) {
        picked.push({ v, px, py });
      }
      if (picked.length >= 12) break;
    }
    const choices = [];
    for (const p of picked) {
      const [ox, oy] = subpixel(re, p.px, p.py);
      const dxN = (p.px <= N / 2 ? p.px : p.px - N) + ox;
      const dyN = (p.py <= N / 2 ? p.py : p.py - N) + oy;
      // OpenCV phaseCorrelate 的符号与 SIFT「特征点从 a 到 b 的位移」相反，取反对齐 Python 版
      choices.push({ dx: -dxN * a.w / N, dy: -dyN * a.h / N, peak: p.v });
    }
    for (const c of coarseCandidates(a, b)) choices.push({ dx: c.tx, dy: c.ty, peak: 0 });
    for (const c of axisCandidates(a, b)) choices.push(c);
    let chosen = null;
    for (const c of choices) {
      if (Math.abs(c.dx) > a.w * 0.95 || Math.abs(c.dy) > a.h * 0.95) continue;
      const mad = overlapMad(a, b, c.dx, c.dy);
      // 通用先验：相邻帧位移接近半幅时通常是对重复纹理的误匹配
      const odd = (Math.abs(c.dx) > a.w * 0.35 ? 12 : 0)
        + (Math.abs(c.dy) > a.h * 0.60 ? 12 : 0);
      const score = mad + odd - 4 * c.peak;
      if (!chosen || score < chosen.score) {
        chosen = { dx: c.dx, dy: c.dy, mad, peak: c.peak, score };
      }
    }
    if (!chosen) chosen = { dx: 0, dy: 0, mad: 255, peak: 0, score: 0 };
    // 粗配准只有 ±(w/64) 精度，在 ±8px 内按 MAD 细化到 2px
    let refined = chosen;
    for (let oy = -8; oy <= 8; oy += 2) {
      for (let ox = -8; ox <= 8; ox += 2) {
        const tx = chosen.dx + ox, ty = chosen.dy + oy;
        const mad = overlapMad(a, b, tx, ty);
        if (mad < refined.mad - 0.02) refined = { dx: tx, dy: ty, mad, peak: 0, score: mad };
      }
    }
    return { dx: refined.dx, dy: refined.dy, resp: 100 / (1 + refined.mad),
             mad: refined.mad, peak: refined.peak };
  }

  // 只裁四周连续的全黑 letterbox，不碰画面内的暗部（否则各帧裁切尺寸会不一致）
  function cropBlackBorder(im) {
    const { w, h, data } = im;
    const cols = new Int32Array(w), rows = new Int32Array(h);
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const p = (y * w + x) * 4;
        if (data[p] >= 16 || data[p + 1] >= 16 || data[p + 2] >= 16) { cols[x]++; rows[y]++; }
      }
    }
    const isDarkCol = x => cols[x] < h * 0.02;
    const isDarkRow = y => rows[y] < w * 0.02;
    let x0 = 0, x1 = w - 1, y0 = 0, y1 = h - 1;
    while (x0 < x1 && isDarkCol(x0)) x0++;
    while (x1 > x0 && isDarkCol(x1)) x1--;
    while (y0 < y1 && isDarkRow(y0)) y0++;
    while (y1 > y0 && isDarkRow(y1)) y1--;
    const nw = x1 - x0 + 1, nh = y1 - y0 + 1;
    if (nw === w && nh === h || nw < 32 || nh < 32) return im;
    const out = new Uint8ClampedArray(nw * nh * 4);
    for (let y = 0; y < nh; y++) {
      out.set(data.subarray(((y + y0) * w + x0) * 4, ((y + y0) * w + x0 + nw) * 4), y * nw * 4);
    }
    return { w: nw, h: nh, data: out };
  }

  async function estimatePairs(images, onProgress) {
    const preps = [];
    for (let i = 0; i < images.length; i++) {
      preps.push(prepare(images[i]));
      if (onProgress) onProgress('fft', i + 1, images.length);
      await tick();
    }
    const pairs = [];
    for (let i = 0; i < preps.length; i++) {
      for (let j = i + 1; j < preps.length; j++) {
        const s = phaseShift(preps[i], preps[j]);
        pairs.push({ i, j, dx: s.dx, dy: s.dy, resp: s.resp });
      }
      if (onProgress) onProgress('pair', i + 1, preps.length);
      await tick();
    }
    return pairs;
  }

  function tick() {
    return new Promise(r => (typeof setTimeout === 'function' ? setTimeout(r, 0) : r()));
  }

  // Kruskal 最大生成树：锐度高的边优先，BFS 传播全局位置
  function layout(n, pairs) {
    const edges = pairs.slice().sort((a, b) => b.resp - a.resp);
    const parent = Array.from({ length: n }, (_, i) => i);
    const find = x => { while (parent[x] !== x) { parent[x] = parent[parent[x]]; x = parent[x]; } return x; };
    const adj = Array.from({ length: n }, () => []);
    for (const e of edges) {
      const ri = find(e.i), rj = find(e.j);
      if (ri === rj) continue;
      parent[ri] = rj;
      adj[e.i].push([e.j, e.dx, e.dy]);
      adj[e.j].push([e.i, -e.dx, -e.dy]);
    }
    const pos = new Array(n).fill(null);
    const anchor = edges.length ? edges[0].i : 0;
    pos[anchor] = { x: 0, y: 0 };
    const q = [anchor];
    while (q.length) {
      const i = q.shift();
      for (const [j, dx, dy] of adj[i]) {
        if (!pos[j]) { pos[j] = { x: pos[i].x - dx, y: pos[i].y - dy }; q.push(j); }
      }
    }
    for (let i = 0; i < n; i++) if (!pos[i]) pos[i] = { x: 0, y: 0 };
    return pos;
  }

  function insertionSort(a, len) {
    for (let i = 1; i < len; i++) {
      const v = a[i]; let j = i - 1;
      while (j >= 0 && a[j] > v) { a[j + 1] = a[j]; j--; }
      a[j + 1] = v;
    }
    return a[(len - 1) >> 1];
  }

  // 逐行融合，内存 O(n·W)；mean 为加权平均，median 为跨帧中值（自动去掉运动主体/重复水印）
  async function fuse(images, pos, blend, onProgress) {
    const n = images.length;
    const ox = pos.map((p, i) => Math.round(p.x)), oy = pos.map((p, i) => Math.round(p.y));
    const minx = Math.min(...ox), miny = Math.min(...oy);
    const W = Math.ceil(Math.max(...ox.map((x, i) => x + images[i].w)) - minx);
    const H = Math.ceil(Math.max(...oy.map((y, i) => y + images[i].h)) - miny);
    const xs = ox.map(x => x - minx), ys = oy.map(y => y - miny);
    const data = new Uint8ClampedArray(W * H * 4);
    const valid = new Uint8Array(W * H);
    const rb = new Float64Array(n), gb = new Float64Array(n), bb = new Float64Array(n);
    for (let y = 0; y < H; y++) {
      const sy = ys.map(v => y - v);
      for (let x = 0; x < W; x++) {
        let cnt = 0, sr = 0, sg = 0, sb = 0, sw = 0;
        for (let i = 0; i < n; i++) {
          const im = images[i];
          const py = sy[i], px = x - xs[i];
          if (py < 0 || py >= im.h || px < 0 || px >= im.w) continue;
          const p = (py * im.w + px) * 4;
          if (blend === 'median') { rb[cnt] = im.data[p]; gb[cnt] = im.data[p + 1]; bb[cnt] = im.data[p + 2]; }
          else {
            // 边缘羽化：每帧离边界 28px 内渐隐，重叠区平滑过渡，消除矩形硬接缝
            const wgt = Math.max(0.02, Math.min(1, (px + 1) / 28, (im.w - px) / 28,
              (py + 1) / 28, (im.h - py) / 28));
            sr += im.data[p] * wgt; sg += im.data[p + 1] * wgt; sb += im.data[p + 2] * wgt;
            sw += wgt;
          }
          cnt++;
        }
        if (!cnt) continue;
        const o = (y * W + x) * 4;
        if (blend === 'median') {
          data[o] = insertionSort(rb, cnt);
          data[o + 1] = insertionSort(gb, cnt);
          data[o + 2] = insertionSort(bb, cnt);
        } else {
          const inv = 1 / Math.max(sw, 1e-6);
          data[o] = sr * inv; data[o + 1] = sg * inv; data[o + 2] = sb * inv;
        }
        data[o + 3] = 255;
        valid[y * W + x] = 1;
      }
      if (onProgress && y % 120 === 0) { onProgress('fuse', y, H); await tick(); }
    }
    return { w: W, h: H, data, valid };
  }

  // 裁到有效像素外接矩形，再对内部未覆盖黑区做同行线性补洞（不含 LaMa，极简版）
  function finish(fused) {
    const { w: W, h: H, data, valid } = fused;
    let x0 = W, x1 = -1, y0 = H, y1 = -1;
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        if (!valid[y * W + x]) continue;
        if (x < x0) x0 = x; if (x > x1) x1 = x;
        if (y < y0) y0 = y; if (y > y1) y1 = y;
      }
    }
    if (x1 < 0) return { w: 1, h: 1, data: new Uint8ClampedArray(4), diag: {} };
    const nw = x1 - x0 + 1, nh = y1 - y0 + 1;
    const out = new Uint8ClampedArray(nw * nh * 4);
    const mask = new Uint8Array(nw * nh);
    let holes = 0;
    for (let y = 0; y < nh; y++) {
      for (let x = 0; x < nw; x++) {
        const s = ((y + y0) * W + x + x0) * 4, d = (y * nw + x) * 4;
        out[d] = data[s]; out[d + 1] = data[s + 1]; out[d + 2] = data[s + 2]; out[d + 3] = 255;
        const v = valid[(y + y0) * W + x + x0];
        mask[y * nw + x] = v;
        if (!v) holes++;
      }
    }
    const holePct = holes * 100 / (nw * nh);
    for (let y = 0; y < nh; y++) {
      const row = y * nw;
      let first = -1, last = -1;
      for (let x = 0; x < nw; x++) if (mask[row + x]) { if (first < 0) first = x; last = x; }
      if (first < 0) continue;
      for (let x = 0; x < nw; x++) {
        if (mask[row + x]) continue;
        let l = x, r = x;
        while (l >= 0 && !mask[row + l]) l--;
        while (r < nw && !mask[row + r]) r++;
        const a = l >= 0 ? l : first, b = r < nw ? r : last;
        const t = b === a ? 0 : (x - a) / (b - a);
        const pa = (row + a) * 4, pb = (row + b) * 4, pd = (row + x) * 4;
        for (let c = 0; c < 3; c++) out[pd + c] = out[pa + c] * (1 - t) + out[pb + c] * t;
      }
    }
    // 整行都无效时用最近的相邻行填充
    for (let y = 0; y < nh; y++) {
      const row = y * nw;
      let any = false;
      for (let x = 0; x < nw; x++) if (mask[row + x]) { any = true; break; }
      if (any) continue;
      let sy = -1;
      for (let d = 1; d < nh && sy < 0; d++) {
        if (y - d >= 0 && mask[(y - d) * nw]) sy = y - d;
        else if (y + d < nh && mask[(y + d) * nw]) sy = y + d;
      }
      if (sy >= 0) out.set(out.subarray(sy * nw * 4, (sy + 1) * nw * 4), row * nw * 4);
    }
    return { w: nw, h: nh, data: out, diag: { holePct: +holePct.toFixed(2), croppedTo: [nw, nh] } };
  }

  async function process(images, opts) {
    opts = opts || {};
    const t0 = (typeof performance !== 'undefined' ? performance : Date).now();
    const cropped = images.map(im => cropBlackBorder(im));
    const pairs = await estimatePairs(cropped, opts.onProgress);
    const pos = layout(cropped.length, pairs);
    const fused = await fuse(cropped, pos, opts.blend || 'mean', opts.onProgress);
    const result = finish(fused);
    const t1 = (typeof performance !== 'undefined' ? performance : Date).now();
    return {
      image: result,
      diag: {
        frames: images.length,
        inputSizes: images.map(im => [im.w, im.h]),
        croppedSizes: cropped.map(im => [im.w, im.h]),
        pairs: pairs.map(p => ({ ...p, dx: +p.dx.toFixed(1), dy: +p.dy.toFixed(1), resp: +p.resp.toFixed(1) })),
        positions: pos.map(p => [+p.x.toFixed(1), +p.y.toFixed(1)]),
        output: [result.w, result.h],
        blend: opts.blend || 'mean',
        ms: Math.round(t1 - t0),
        ...result.diag
      }
    };
  }

  return { N, fft1d, fft2, prepare, phaseShift, cropBlackBorder, estimatePairs, layout, fuse, finish, process };
});
