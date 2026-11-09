/* Python 完整版 translate_stitch.py 的浏览器移植。
   流程：裁黑边 → 局部特征 + 纯平移 RANSAC 两两配准（原图/局部增强自适应）
   → 内点数最大生成树布局 → 同帧去重 → 重叠树曝光补偿
   → 图割式接缝归属（每像素只取一帧）→ 外接矩形裁剪 + 邻域补洞。
   相位相关内核（stitch.js）保留为低纹理画面的回退。 */
(function (root, factory) {
  const base = (typeof module === 'object' && module.exports)
    ? require('./stitch.js') : root.Stitch;
  const api = factory(base);
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.Stitch = api;
})(typeof self !== 'undefined' ? self : this, function (base) {
  'use strict';

  const FW = 384;        // 配准工作宽度
  const KP_MAX = 420;    // 每帧关键点上限
  const D = 64;          // 描述子维度：4×4 cell × 4 方向 bin
  const RATIO2 = 0.64;   // ratio test 0.8 的平方
  const TOL = 2.6;       // RANSAC 内点容差（工作尺度像素）
  const MIN_INLIERS = 6;

  const clamp = (v, a, b) => v < a ? a : (v > b ? b : v);
  const tick = () => new Promise(r => (typeof setTimeout === 'function' ? setTimeout(r, 0) : r()));

  function medianOf(arr) {
    if (!arr.length) return 0;
    arr.sort((a, b) => a - b);
    return arr.length & 1 ? arr[arr.length >> 1]
      : (arr[arr.length / 2 - 1] + arr[arr.length / 2]) / 2;
  }

  // ---------- 局部特征：下采样灰度 → 梯度 → 关键点 → 4×4×4 方向直方图 ----------
  function buildFeatures(im, enhanced) {
    const iw = im.w, ih = im.h, src = im.data;
    const w = Math.max(64, Math.round(Math.min(1, FW / iw) * iw));
    const h = Math.max(64, Math.round(ih * w / iw));
    const acc = new Float64Array(w * h), cnt = new Uint32Array(w * h);
    for (let y = 0; y < ih; y++) {
      const ty = Math.min(h - 1, (y * h / ih) | 0), row = ty * w;
      for (let x = 0; x < iw; x++) {
        const p = (y * iw + x) * 4;
        acc[row + Math.min(w - 1, (x * w / iw) | 0)] +=
          0.299 * src[p] + 0.587 * src[p + 1] + 0.114 * src[p + 2];
        cnt[row + Math.min(w - 1, (x * w / iw) | 0)]++;
      }
    }
    const g = new Float32Array(w * h);
    for (let i = 0; i < g.length; i++) g[i] = acc[i] / Math.max(1, cnt[i]);
    if (enhanced) {
      // 局部对比度增强（CLAHE 的轻量等价）：减去 13×13 局部均值，突出纹理
      const blur = new Float32Array(w * h), R = 6;
      for (let y = 0; y < h; y++) {
        for (let x = 0; x < w; x++) {
          let s = 0, n = 0;
          for (let dy = -R; dy <= R; dy += 3) {
            const yy = clamp(y + dy, 0, h - 1);
            for (let dx = -R; dx <= R; dx += 3) { s += g[yy * w + clamp(x + dx, 0, w - 1)]; n++; }
          }
          blur[y * w + x] = s / n;
        }
      }
      for (let i = 0; i < g.length; i++) g[i] = clamp(128 + (g[i] - blur[i]) * 2.0, 0, 255);
    }

    const gx = new Float32Array(w * h), gy = new Float32Array(w * h), mag = new Float32Array(w * h);
    for (let y = 1; y < h - 1; y++) {
      for (let x = 1; x < w - 1; x++) {
        const i = y * w + x;
        const ax = g[i + 1] - g[i - 1], ay = g[i + w] - g[i - w];
        gx[i] = ax; gy[i] = ay; mag[i] = Math.sqrt(ax * ax + ay * ay);
      }
    }
    const cand = [];
    for (let y = 8; y < h - 8; y += 2) {
      for (let x = 8; x < w - 8; x += 2) {
        const m = mag[y * w + x];
        if (m < 16) continue;
        if (m < mag[y * w + x - 2] || m < mag[y * w + x + 2] ||
            m < mag[(y - 2) * w + x] || m < mag[(y + 2) * w + x]) continue;
        cand.push({ x, y, m });
      }
    }
    cand.sort((a, b) => b.m - a.m);
    const gw = ((w / 10) | 0) + 1, grid = new Uint8Array(gw * (((h / 10) | 0) + 1));
    const kp = [];
    for (const c of cand) {
      if (kp.length >= KP_MAX) break;
      const key = ((c.y / 10) | 0) * gw + ((c.x / 10) | 0);
      if (grid[key]) continue;
      grid[key] = 1; kp.push(c);
    }
    const desc = new Float32Array(kp.length * D);
    for (let k = 0; k < kp.length; k++) {
      const off = k * D;
      for (let dy = -8; dy < 8; dy++) {
        const cy = ((dy + 8) >> 2);
        for (let dx = -8; dx < 8; dx++) {
          const x = kp[k].x + dx, y = kp[k].y + dy;
          if (x < 1 || y < 1 || x >= w - 1 || y >= h - 1) continue;
          const i = y * w + x, m = mag[i];
          if (m < 1) continue;
          let ang = Math.atan2(gy[i], gx[i]);
          if (ang < 0) ang += Math.PI;
          const bin = Math.min(3, (ang / (Math.PI / 4)) | 0);
          const cell = (cy << 2) + ((dx + 8) >> 2);
          const wgt = m * Math.max(0, 1 - (dx * dx + dy * dy) / 200);
          desc[off + cell * 4 + bin] += wgt;
        }
      }
      let norm = 0;
      for (let j = 0; j < D; j++) norm += desc[off + j] * desc[off + j];
      norm = Math.sqrt(norm) + 1e-9;
      for (let j = 0; j < D; j++) desc[off + j] = Math.min(0.2, desc[off + j] / norm);
      let n2 = 0;
      for (let j = 0; j < D; j++) n2 += desc[off + j] * desc[off + j];
      n2 = Math.sqrt(n2) + 1e-9;
      for (let j = 0; j < D; j++) desc[off + j] /= n2;
    }
    return { w, h, kp, desc, sx: iw / w, sy: ih / h };
  }

  // ---------- 描述子最近邻 + ratio test + 纯平移 RANSAC ----------
  function matchFeatures(A, B) {
    const good = [];
    for (let i = 0; i < A.kp.length; i++) {
      const da = i * D;
      let b1 = Infinity, b2 = Infinity, j1 = -1;
      for (let j = 0; j < B.kp.length; j++) {
        const db = j * D;
        let s = 0;
        for (let k = 0; k < D; k++) {
          const t = A.desc[da + k] - B.desc[db + k];
          s += t * t;
          if (s >= b2) break;
        }
        if (s < b1) { b2 = b1; b1 = s; j1 = j; }
        else if (s < b2) b2 = s;
      }
      if (j1 >= 0 && b1 < RATIO2 * b2) {
        good.push({ dx: B.kp[j1].x - A.kp[i].x, dy: B.kp[j1].y - A.kp[i].y });
      }
    }
    if (good.length < MIN_INLIERS) return null;
    let best = { n: 0, dx: 0, dy: 0 };
    const lim = Math.min(good.length, 320);
    for (let k = 0; k < lim; k++) {
      const q = good[k];
      let n = 0;
      for (const g of good) if (Math.abs(g.dx - q.dx) + Math.abs(g.dy - q.dy) <= TOL) n++;
      if (n > best.n) best = { n, dx: q.dx, dy: q.dy };
    }
    const inl = good.filter(g => Math.abs(g.dx - best.dx) + Math.abs(g.dy - best.dy) <= TOL);
    const dx = medianOf(inl.map(g => g.dx)), dy = medianOf(inl.map(g => g.dy));
    let ninl = 0;
    for (const g of good) if (Math.abs(g.dx - dx) + Math.abs(g.dy - dy) <= TOL) ninl++;
    return { dx, dy, ninl, ngood: good.length };
  }

  function estimateShift(a, b) {
    // 与 Python est_translation 一致：原图 / 局部增强各算一次，按内点率选
    let r = matchFeatures(a.feat[0], b.feat[0]);
    let rate = r ? r.ninl / Math.max(1, r.ngood) : 0;
    const r2 = matchFeatures(a.feat[1], b.feat[1]);
    const rate2 = r2 ? r2.ninl / Math.max(1, r2.ngood) : 0;
    if (rate2 > rate) { r = r2; rate = rate2; }
    if (!r || r.ninl < MIN_INLIERS || rate < 0.18) return null;
    const sx = (a.feat[0].sx + b.feat[0].sx) / 2;
    const sy = (a.feat[0].sy + b.feat[0].sy) / 2;
    return { dx: r.dx * sx, dy: r.dy * sy, ninl: r.ninl, ngood: r.ngood };
  }

  // ---------- 单帧暗边修剪（Python trim_dark_edges：按近黑占比而非整行均值） ----------
  function trimFrameEdges(im) {
    let { w, h, data } = im;
    let x0 = 0, y0 = 0, x1 = w - 1, y1 = h - 1;
    const dark = (x, y) => {
      const p = (y * w + x) * 4;
      return data[p] < 20 && data[p + 1] < 20 && data[p + 2] < 20;
    };
    for (let k = 0; k < 6; k++) {
      let hit = false, c;
      c = 0; for (let x = x0; x <= x1; x++) if (dark(x, y0)) c++;
      if (c / (x1 - x0 + 1) > 0.35 && y1 - y0 > 8) { y0++; hit = true; }
      c = 0; for (let x = x0; x <= x1; x++) if (dark(x, y1)) c++;
      if (c / (x1 - x0 + 1) > 0.35 && y1 - y0 > 8) { y1--; hit = true; }
      c = 0; for (let y = y0; y <= y1; y++) if (dark(x0, y)) c++;
      if (c / (y1 - y0 + 1) > 0.35 && x1 - x0 > 8) { x0++; hit = true; }
      c = 0; for (let y = y0; y <= y1; y++) if (dark(x1, y)) c++;
      if (c / (y1 - y0 + 1) > 0.35 && x1 - x0 > 8) { x1--; hit = true; }
      if (!hit) break;
    }
    // 黑边往画面内常有 2~3px 的暗渐变行，融合后会变成横贯全幅的暗线；统一再削掉
    const PAD = 3;
    if (x1 - x0 > 40 && y1 - y0 > 40) { x0 += PAD; x1 -= PAD; y0 += PAD; y1 -= PAD; }
    const nw = x1 - x0 + 1, nh = y1 - y0 + 1;
    if (nw === w && nh === h) return im;
    const out = new Uint8ClampedArray(nw * nh * 4);
    for (let y = 0; y < nh; y++) {
      out.set(data.subarray(((y + y0) * w + x0) * 4, ((y + y0) * w + x0 + nw) * 4), y * nw * 4);
    }
    return { w: nw, h: nh, data: out };
  }

  // ---------- 贴边黑块：用行内镜像像素替换（letterbox / 未覆盖残留） ----------
  function fixEdgeBlack(data, w, h) {
    const dark = p => data[p] < 26 && data[p + 1] < 26 && data[p + 2] < 26;
    const lim = Math.floor(w * 0.25);
    const mark = new Uint8Array(w * h), todo = [];
    for (let y = 0; y < h; y++) {
      const row = y * w;
      let k = 0;
      while (k < lim && dark((row + k) * 4)) k++;
      for (let x = 0; x < k; x++) { mark[row + x] = 1; todo.push(row + x); }
      let m = 0;
      while (m < lim && dark((row + w - 1 - m) * 4)) m++;
      for (let x = 0; x < m; x++) {
        const p = row + w - 1 - x;
        if (!mark[p]) { mark[p] = 1; todo.push(p); }
      }
    }
    // 从已填好的边界逐层向内扩散，避免镜像/拉伸造成的可见对称线
    let left = todo;
    for (let iter = 0; iter < 300 && left.length; iter++) {
      const next = [];
      for (const p of left) {
        const x = p % w, y = (p / w) | 0;
        let s0 = 0, s1 = 0, s2 = 0, n = 0;
        const add = q => {
          if (mark[q]) return;
          const o = q * 4;
          s0 += data[o]; s1 += data[o + 1]; s2 += data[o + 2]; n++;
        };
        if (x > 0) add(p - 1);
        if (x + 1 < w) add(p + 1);
        if (y > 0) add(p - w);
        if (y + 1 < h) add(p + w);
        if (n) {
          const o = p * 4;
          data[o] = s0 / n; data[o + 1] = s1 / n; data[o + 2] = s2 / n;
          mark[p] = 0;
        } else next.push(p);
      }
      left = next;
    }
  }

  // ---------- 锐度（Laplacian 方差），同帧去重时挑最清晰一帧 ----------
  function sharpness(im) {
    const { w, h, data } = im;
    const g = new Float32Array(w * h);
    for (let i = 0; i < w * h; i++) {
      const p = i * 4;
      g[i] = 0.299 * data[p] + 0.587 * data[p + 1] + 0.114 * data[p + 2];
    }
    let s = 0, s2 = 0, n = 0;
    for (let y = 2; y < h - 2; y += 3) {
      for (let x = 2; x < w - 2; x += 3) {
        const i = y * w + x;
        const v = 4 * g[i] - g[i - 1] - g[i + 1] - g[i - w] - g[i + w];
        s += v; s2 += v * v; n++;
      }
    }
    return n ? s2 / n - (s / n) * (s / n) : 0;
  }

  function dedupe(imgs, pos) {
    const n = imgs.length;
    const parent = Array.from({ length: n }, (_, i) => i);
    const find = x => { while (parent[x] !== x) { parent[x] = parent[parent[x]]; x = parent[x]; } return x; };
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        if (Math.abs(pos[i].x - pos[j].x) + Math.abs(pos[i].y - pos[j].y) < 2) {
          parent[find(i)] = find(j);
        }
      }
    }
    const groups = {};
    for (let i = 0; i < n; i++) (groups[find(i)] || (groups[find(i)] = [])).push(i);
    const keep = Object.values(groups).map(g =>
      g.reduce((best, i) => sharpness(imgs[i]) > sharpness(imgs[best]) ? i : best, g[0]));
    keep.sort((a, b) => a - b);
    return {
      imgs: keep.map(i => imgs[i]),
      pos: keep.map(i => pos[i]),
      keep
    };
  }

  // ---------- 重叠最大生成树曝光补偿（Python exposure_chain） ----------
  function exposureChain(imgs, pos) {
    const n = imgs.length;
    const ox = pos.map(p => Math.round(p.x)), oy = pos.map(p => Math.round(p.y));
    const minx = Math.min(...ox), miny = Math.min(...oy);
    const xs = ox.map(v => v - minx), ys = oy.map(v => v - miny);
    const rel = {}, edges = [];
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const x0 = Math.max(xs[i], xs[j]), x1 = Math.min(xs[i] + imgs[i].w, xs[j] + imgs[j].w);
        const y0 = Math.max(ys[i], ys[j]), y1 = Math.min(ys[i] + imgs[i].h, ys[j] + imgs[j].h);
        if ((x1 - x0) * (y1 - y0) < 20000) continue;
        const step = 4;
        const a = [[], [], []], b = [[], [], []];
        for (let y = y0; y < y1; y += step) {
          for (let x = x0; x < x1; x += step) {
            const pa = ((y - ys[i]) * imgs[i].w + x - xs[i]) * 4;
            const pb = ((y - ys[j]) * imgs[j].w + x - xs[j]) * 4;
            const va = imgs[i].data, vb = imgs[j].data;
            let ok = true;
            for (let c = 0; c < 3; c++) {
              if (va[pa + c] > 250 || vb[pb + c] > 250 || va[pa + c] < 8 || vb[pb + c] < 8) { ok = false; break; }
            }
            if (!ok) continue;
            for (let c = 0; c < 3; c++) { a[c].push(va[pa + c]); b[c].push(vb[pb + c]); }
          }
        }
        if (a[0].length < 1000) continue;
        const gain = [1, 1, 1], off = [0, 0, 0];
        for (let c = 0; c < 3; c++) {
          const A = a[c], B = b[c], m = A.length;
          let ma = 0, mb = 0, mab = 0, mb2 = 0;
          for (let k = 0; k < m; k++) { ma += A[k]; mb += B[k]; mab += A[k] * B[k]; mb2 += B[k] * B[k]; }
          ma /= m; mb /= m; mab /= m; mb2 /= m;
          const cov = mab - ma * mb, vb = Math.max(1, mb2 - mb * mb);
          const ls = cov / vb;
          gain[c] = clamp(1 + 0.85 * (ls - 1), 0.70, 1.40);
          const dif = [];
          for (let k = 0; k < m; k++) dif.push(A[k] - gain[c] * B[k]);
          off[c] = clamp(medianOf(dif), -40, 40);
        }
        rel[i + ',' + j] = { g: gain, o: off };
        edges.push([a[0].length, i, j]);
      }
    }
    const A = Array.from({ length: n }, () => [1, 1, 1]);
    const B = Array.from({ length: n }, () => [0, 0, 0]);
    if (!edges.length) return { A, B };
    edges.sort((p, q) => q[0] - p[0]);
    const par = Array.from({ length: n }, (_, i) => i);
    const find = x => { while (par[x] !== x) { par[x] = par[par[x]]; x = par[x]; } return x; };
    const adj = Array.from({ length: n }, () => []);
    for (const [, i, j] of edges) {
      const ri = find(i), rj = find(j);
      if (ri === rj) continue;
      par[ri] = rj;
      adj[i].push([j, true]); adj[j].push([i, false]);
    }
    const seen = new Uint8Array(n); seen[0] = 1;
    const q = [0];
    while (q.length) {
      const p = q.shift();
      for (const [c, forward] of adj[p]) {
        if (seen[c]) continue;
        seen[c] = 1;
        if (forward) {
          const { g, o } = rel[p + ',' + c];
          for (let k = 0; k < 3; k++) { A[c][k] = A[p][k] * g[k]; B[c][k] = A[p][k] * o[k] + B[p][k]; }
        } else {
          const { g, o } = rel[c + ',' + p];
          for (let k = 0; k < 3; k++) { A[c][k] = A[p][k] / g[k]; B[c][k] = B[p][k] - A[p][k] * o[k] / g[k]; }
        }
        q.push(c);
      }
    }
    return { A, B };
  }

  // ---------- 图割式接缝：低分辨率 ICM 最小化「标签切换落在低梯度处」 ----------
  async function seamFuse(imgs, pos, expo, onProgress) {
    const n = imgs.length, S = 4;
    const ox = pos.map(p => Math.round(p.x)), oy = pos.map(p => Math.round(p.y));
    const minx = Math.min(...ox), miny = Math.min(...oy);
    const W = Math.ceil(Math.max(...ox.map((v, i) => v + imgs[i].w)) - minx);
    const H = Math.ceil(Math.max(...oy.map((v, i) => v + imgs[i].h)) - miny);
    const xs = ox.map(v => v - minx), ys = oy.map(v => v - miny);
    const sw = Math.ceil(W / S), sh = Math.ceil(H / S);
    const P = sw * sh;
    const cover = new Uint8Array(P * n);
    const low = new Uint8Array(P * n * 3);
    for (let y = 0; y < sh; y++) {
      for (let x = 0; x < sw; x++) {
        const p = y * sw + x, cx = x * S, cy = y * S;
        for (let i = 0; i < n; i++) {
          const px = cx - xs[i], py = cy - ys[i];
          if (px < 0 || py < 0 || px >= imgs[i].w || py >= imgs[i].h) continue;
          cover[p * n + i] = 1;
          const s = (py * imgs[i].w + px) * 4, d = (p * n + i) * 3;
          for (let c = 0; c < 3; c++) {
            low[d + c] = clamp(imgs[i].data[s + c] * expo.A[i][c] + expo.B[i][c], 0, 255);
          }
        }
      }
    }
    // 平均颜色与梯度：接缝切换代价 = 1/(1+色差)，让边界藏到内容边缘
    const avg = new Float32Array(P * 3), gx = new Float32Array(P * 2);
    for (let p = 0; p < P; p++) {
      let cnt = 0;
      for (let i = 0; i < n; i++) {
        if (!cover[p * n + i]) continue;
        const d = (p * n + i) * 3;
        for (let c = 0; c < 3; c++) avg[p * 3 + c] += low[d + c];
        cnt++;
      }
      if (cnt) for (let c = 0; c < 3; c++) avg[p * 3 + c] /= cnt;
    }
    for (let y = 0; y < sh; y++) {
      for (let x = 0; x < sw; x++) {
        const p = y * sw + x;
        const qx = x + 1 < sw ? p + 1 : p, qy = y + 1 < sh ? p + sw : p;
        for (let c = 0; c < 3; c++) {
          gx[p * 2] += Math.abs(avg[p * 3 + c] - avg[qx * 3 + c]);
          gx[p * 2 + 1] += Math.abs(avg[p * 3 + c] - avg[qy * 3 + c]);
        }
        gx[p * 2] /= 3; gx[p * 2 + 1] /= 3;
      }
    }
    // 初始化：离帧中心最近（Voronoi），避免一开始就是矩形边
    const labels = new Int8Array(P).fill(-1);
    for (let y = 0; y < sh; y++) {
      for (let x = 0; x < sw; x++) {
        const p = y * sw + x, cx = x * S, cy = y * S;
        let best = -1, bd = Infinity;
        for (let i = 0; i < n; i++) {
          if (!cover[p * n + i]) continue;
          const dx = cx - xs[i] - imgs[i].w / 2, dy = cy - ys[i] - imgs[i].h / 2;
          const d = dx * dx + dy * dy;
          if (d < bd) { bd = d; best = i; }
        }
        labels[p] = best;
      }
    }
    for (let iter = 0; iter < 4; iter++) {
      for (let y = 0; y < sh; y++) {
        for (let x = 0; x < sw; x++) {
          const p = y * sw + x;
          let bl = labels[p], bc = Infinity;
          for (let i = 0; i < n; i++) {
            if (!cover[p * n + i]) continue;
            const d = (p * n + i) * 3;
            let cost = 0.02 * (Math.abs(low[d] - avg[p * 3]) + Math.abs(low[d + 1] - avg[p * 3 + 1])
              + Math.abs(low[d + 2] - avg[p * 3 + 2])) / 3;
            if (x > 0) { const q = p - 1; if (labels[q] >= 0 && labels[q] !== i) cost += 6 / (1 + gx[q * 2]); }
            if (x + 1 < sw) { const q = p + 1; if (labels[q] >= 0 && labels[q] !== i) cost += 6 / (1 + gx[p * 2]); }
            if (y > 0) { const q = p - sw; if (labels[q] >= 0 && labels[q] !== i) cost += 6 / (1 + gx[q * 2 + 1]); }
            if (y + 1 < sh) { const q = p + sw; if (labels[q] >= 0 && labels[q] !== i) cost += 6 / (1 + gx[p * 2 + 1]); }
            if (cost < bc) { bc = cost; bl = i; }
          }
          labels[p] = bl;
        }
      }
      if (onProgress) { onProgress('seam', iter + 1, 4); await tick(); }
    }
    const data = new Uint8ClampedArray(W * H * 4), valid = new Uint8Array(W * H);
    for (let y = 0; y < H; y++) {
      const ly = Math.min(sh - 1, (y / S) | 0);
      for (let x = 0; x < W; x++) {
        const lx = Math.min(sw - 1, (x / S) | 0), p = ly * sw + lx;
        let f = labels[p];
        if (f < 0 || !cover[p * n + f]) {
          f = -1;
          for (let i = 0; i < n; i++) if (cover[p * n + i]) { f = i; break; }
        }
        if (f < 0) continue;
        const px = x - xs[f], py = y - ys[f];
        if (px < 0 || py < 0 || px >= imgs[f].w || py >= imgs[f].h) continue;
        const s = (py * imgs[f].w + px) * 4, o = (y * W + x) * 4;
        for (let c = 0; c < 3; c++) data[o + c] = clamp(imgs[f].data[s + c] * expo.A[f][c] + expo.B[f][c], 0, 255);
        data[o + 3] = 255; valid[y * W + x] = 1;
      }
      if (onProgress && y % 200 === 0) { onProgress('fuse', y, H); await tick(); }
    }
    return { w: W, h: H, data, valid };
  }

  // ---------- 外接矩形 + 水平/垂直插值补洞 + 裁暗边 ----------
  function finish2(fused) {
    const { w: W, h: H, data, valid } = fused;
    let x0 = W, x1 = -1, y0 = H, y1 = -1;
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        if (!valid[y * W + x]) continue;
        if (x < x0) x0 = x; if (x > x1) x1 = x;
        if (y < y0) y0 = y; if (y > y1) y1 = y;
      }
    }
    if (x1 < 0) return { w: 1, h: 1, data: new Uint8ClampedArray(4), diag: { holePct: 100 } };
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
    // 水平插值 + 两端镜像外推：斜向运镜留下的阶梯黑块全部填满
    for (let y = 0; y < nh; y++) {
      const row = y * nw;
      let first = -1, last = -1;
      for (let x = 0; x < nw; x++) if (mask[row + x]) { if (first < 0) first = x; last = x; }
      if (first < 0) continue;
      for (let x = first; x <= last; x++) {
        if (mask[row + x]) continue;
        let l = x, r = x;
        while (l >= 0 && !mask[row + l]) l--;
        while (r < nw && !mask[row + r]) r++;
        if (l < 0 || r >= nw) continue;
        const t = (x - l) / (r - l), a = (row + l) * 4, b = (row + r) * 4, d = (row + x) * 4;
        for (let c = 0; c < 3; c++) out[d + c] = out[a + c] * (1 - t) + out[b + c] * t;
      }
      for (let x = 0; x < first; x++) {
        const a = (row + clamp(2 * first - x, first, last)) * 4, d = (row + x) * 4;
        for (let c = 0; c < 3; c++) out[d + c] = out[a + c];
      }
      for (let x = last + 1; x < nw; x++) {
        const a = (row + clamp(2 * last - x, first, last)) * 4, d = (row + x) * 4;
        for (let c = 0; c < 3; c++) out[d + c] = out[a + c];
      }
      for (let x = 0; x < nw; x++) mask[row + x] = 1;
    }
    // 整行都无效时复制最近的有效行
    for (let y = 0; y < nh; y++) {
      const row = y * nw;
      if (mask[row]) continue;
      let sy = -1;
      for (let d = 1; d < nh && sy < 0; d++) {
        if (y - d >= 0 && mask[(y - d) * nw]) sy = y - d;
        else if (y + d < nh && mask[(y + d) * nw]) sy = y + d;
      }
      if (sy >= 0) {
        out.set(out.subarray(sy * nw * 4, (sy + 1) * nw * 4), row * nw * 4);
        for (let x = 0; x < nw; x++) mask[row + x] = 1;
      }
    }
    // 四周 1~2px 暗边
    let cx0 = 0, cy0 = 0, cw = nw, ch = nh;
    for (let k = 0; k < 8; k++) {
      const darkRow = y => {
        let c = 0;
        for (let x = cx0; x < cx0 + cw; x++) {
          const p = (y * nw + x) * 4;
          if (out[p] < 20 && out[p + 1] < 20 && out[p + 2] < 20) c++;
        }
        return c / cw > 0.35;
      };
      const darkCol = x => {
        let c = 0;
        for (let y = cy0; y < cy0 + ch; y++) {
          const p = (y * nw + x) * 4;
          if (out[p] < 20 && out[p + 1] < 20 && out[p + 2] < 20) c++;
        }
        return c / ch > 0.35;
      };
      let hit = false;
      if (ch > 8 && darkRow(cy0)) { cy0++; ch--; hit = true; }
      if (ch > 8 && darkRow(cy0 + ch - 1)) { ch--; hit = true; }
      if (cw > 8 && darkCol(cx0)) { cx0++; cw--; hit = true; }
      if (cw > 8 && darkCol(cx0 + cw - 1)) { cw--; hit = true; }
      if (!hit) break;
    }
    let fw = nw, fh = nh, fdata = out;
    if (cw !== nw || ch !== nh) {
      const cropped = new Uint8ClampedArray(cw * ch * 4);
      for (let y = 0; y < ch; y++) {
        cropped.set(out.subarray(((y + cy0) * nw + cx0) * 4, ((y + cy0) * nw + cx0 + cw) * 4), y * cw * 4);
      }
      fw = cw; fh = ch; fdata = cropped;
    }
    fixEdgeBlack(fdata, fw, fh);
    return { w: fw, h: fh, data: fdata, diag: { holePct: +holePct.toFixed(2) } };
  }

  // ---------- 主流程 ----------
  async function process(images, opts) {
    opts = opts || {};
    const t0 = (typeof performance !== 'undefined' ? performance : Date).now();
    const cropped = images.map(im => trimFrameEdges(base.cropBlackBorder(im)));
    const n = cropped.length;
    const frames = cropped.map(im => ({
      im, feat: [buildFeatures(im, false), buildFeatures(im, true)], fft: null
    }));
    for (let i = 0; i < n; i++) {
      frames[i].fft = base.prepare(cropped[i]);
      if (opts.onProgress) opts.onProgress('fft', i + 1, n);
      await tick();
    }
    const pairs = [];
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const f = estimateShift(frames[i], frames[j]);
        const ph = base.phaseShift(frames[i].fft, frames[j].fft);
        let dx, dy, ninl, src;
        if (f) {
          dx = f.dx; dy = f.dy; ninl = f.ninl; src = 'feat';
        } else {
          dx = ph.dx; dy = ph.dy; ninl = Math.max(1, Math.round(ph.resp / 10)); src = 'phase';
        }
        pairs.push({ i, j, dx, dy, ninl, resp: 100 / (1 + ph.mad), src });
      }
      if (opts.onProgress) opts.onProgress('pair', i + 1, n);
      await tick();
    }
    // 内点数最大生成树 + BFS 传播
    const edges = pairs.slice().sort((a, b) => b.ninl - a.ninl);
    const parent = Array.from({ length: n }, (_, i) => i);
    const find = x => { while (parent[x] !== x) { parent[x] = parent[parent[x]]; x = parent[x]; } return x; };
    const adj = Array.from({ length: n }, () => []);
    for (const e of edges) {
      if (e.ninl < MIN_INLIERS) continue;
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
    const ded = dedupe(cropped, pos);
    const imgs = ded.imgs, pos2 = ded.pos;
    const blend = opts.blend || 'seam';
    let fused;
    const expo = exposureChain(imgs, pos2);
    if (blend === 'mean' || blend === 'median') {
      const adjusted = imgs.map((im, i) => {
        const d = new Uint8ClampedArray(im.data.length);
        d.set(im.data);
        for (let p = 0; p < d.length; p += 4) {
          for (let c = 0; c < 3; c++) d[p + c] = clamp(d[p + c] * expo.A[i][c] + expo.B[i][c], 0, 255);
        }
        return { w: im.w, h: im.h, data: d };
      });
      fused = await base.fuse(adjusted, pos2, blend, opts.onProgress);
    } else {
      fused = await seamFuse(imgs, pos2, expo, opts.onProgress);
    }
    const result = finish2(fused);
    const t1 = (typeof performance !== 'undefined' ? performance : Date).now();
    return {
      image: result,
      diag: {
        frames: images.length,
        inputSizes: images.map(im => [im.w, im.h]),
        croppedSizes: cropped.map(im => [im.w, im.h]),
        pairs: pairs.map(p => ({ ...p, dx: +p.dx.toFixed(1), dy: +p.dy.toFixed(1), resp: +p.resp.toFixed(1) })),
        positions: pos2.map(p => [+p.x.toFixed(1), +p.y.toFixed(1)]),
        kept: ded.keep,
        output: [result.w, result.h],
        blend, ms: Math.round(t1 - t0),
        ...result.diag
      }
    };
  }

  return Object.assign({}, base, {
    buildFeatures, matchFeatures, estimateShift, sharpness, dedupe,
    exposureChain, seamFuse, finish2, process
  });
});
